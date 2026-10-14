import argparse
import logging
import os
import random
import numpy

import math
from mvp_sim.core.environment import Environment
from mvp_sim.core.order import Order, OrderStatus
from mvp_sim.core.driver import Driver
from mvp_sim.core.restaurant import Restaurant
from mvp_sim.core.zone import Zone
from mvp_sim.cost_functions.travel_time import (zone_fixed_cost_matrix, 
                                                AuxInfo, 
                                                TravelCost, 
                                                floyd_warshall,
                                                )
from mvp_sim.logger.logger import configure_logging
from mvp_sim.policies.general_policies import erf
from mvp_sim.policies.general_policies import eaf
from mvp_sim.results.results import Results
from mvp_sim.simulator.engine import SimEngine
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.simulator.events import OrderArriveEvent, DriverReadyEvent
from mvp_sim.stats.metrics import compute_metrics
from mvp_sim.tools.visualize_timeline import build_timeline, render, _strip_ansi
from mvp_sim.tools.filter_events import save_filtered
from mvp_sim.tools.plot_timeline import plot_all
from mvp_sim.arrivals.generators import uniform_arr, poisson_arr, normal_arr, ArrivalAuxInfo
from mvp_sim.order_spreads.gens import uniform_spread, closest_spread, furtherest_spread
from typing import Callable 

"""
Multiple zones with multiple resturants with poisson arrivals and multiple drivers.

Models a newtork specified by a cost matrix. 

If policy sends a driver from zone A to zone B and there is no direct connection,
then the cost matrix selects the shortest path.

The cost matrix must specify a graph that is connected.

Topology
--------
- 

Running from the command line
------------------------------
    python -m mvp_sim.experiments.poisson --output <dir> [--seed <int>]

    --output   Directory to write results into. A subdirectory called "star"
               is created automatically (e.g. experimental_results/star/).
    --seed     Integer random seed (default: 42).

    Example:
        python -m mvp_sim.experiments.poisson --output experimental_results

Output files (written to <output>/star/)
-----------------------------------------
    metrics.json           Aggregate metrics (flow time, travel time, etc.)
    experiment_config.json Seed, policy, horizon, branch distances.
    orders.json            All orders with arrival time and destination.
    completed_orders.json  Orders that were delivered, with completion time.
    drivers.json           Final driver state.
    batches.json           Each dispatched batch: driver and order ids.
    events.log             Full event log, one event per line.
    filtered_events.log    Subset of events.log (OrderArriveEvent, OrderReadyEvent).
    timeline.txt           Human-readable text timeline of events.
    overview.png           3-panel chart: order Gantt, event scatter, driver swim-lane.
    driver_activity.png    Full-width swim-lane for all drivers.
    driver_<id>.png        Per-driver order Gantt and activity swim-lane.

Visualizing results
--------------------
    python -m mvp_sim.tools.visualize_timeline <output>/poisson
    python -m mvp_sim.tools.plot_timeline <output>/poisson

Using from Python
-----------------
    from mvp_sim.experiments.poisson import run_baseline
    results = run_baseline(seed=7, output="experimental_results")
    print(results.metrics)

Policies
--------
    EAF  Earliest Anticipation First — dispatches toward the order
              whose estimated completion time (arrival + travel) is soonest.
    ERF  Earliest Ready First — dispatches toward the order that
              arrived (and became ready) earliest.
    For both policies, all ready orders going to the same destination zone
    are batched together into one dispatch.
    To swap policy, change the policy= line in run_baseline().
"""

INF = math.inf

POLICY_NAME: str = "erf" # remember to change this!
EXPERIMENT_NAME: str = "poisson"
HORIZON: float = 20
WARMUP_DURATION = 5

RUN_SEED:int = 42
LIST_OF_METRICS:list[str] = ["total_orders", "undelivered_orders", "flow_time", "travel_time",
                             "avg_batch_size", "batch_efficiency", "driver_utilization"]
TRAVEL_COST_CLASS: TravelCost = zone_fixed_cost_matrix() # options: anything that's not star lol

# for the cost_matrix, put INF if there is no direct path between the two zones
# then the cost_matrix will try to find the shortest path between the two and sum it up
# the cost_matrix must specify a graph that is connected
# the cost_matrix must be symmetric
COST_MATRIX: list[list[float]] = [
    [1,   4,   INF, 1],
    [4,   1,   2,   INF],
    [INF, 2,   1,   3],
    [1,   INF, 3,   1]
]

NUM_ZONES = len(COST_MATRIX[0])

ZONE_INFO: dict[int, list[tuple[tuple[float, float], Callable, Callable]]] = {
    1: [((0,  0),  uniform_arr,  uniform_spread)], # zone_id : [rest_config1, rest_config2...]
    2: [((2,  1),  poisson_arr,  closest_spread),
        ((2,  2),  uniform_arr,  closest_spread)],
    3: [((-1, -1), normal_arr,   uniform_spread),
        ((-1,  0), poisson_arr,  closest_spread),
        ((-1, -2), normal_arr,   furtherest_spread)],
    4: [((-1,  2), uniform_arr,  closest_spread),
        ((-1,  1), normal_arr,   furtherest_spread),
        ((0,   1), uniform_arr,  uniform_spread),
        ((-2,  2), poisson_arr,  uniform_spread)], 
}

## may need an functin to assert that none of the locs are the same

DRIVER_INFO: list[tuple[int, tuple[float, float]]] = [
    (1, (0, 0)), # (zone_id, pos)
    (1, (0, 0)),
    (1, (0, 0)),
    (1, (0, 0)),
    (1, (0, 0)),
    (1, (0, 0)),
]

def verify_cost_matrix(c_m: list[list[float]]) -> tuple[bool, list[list[float]]]:
    """
    Cost matrix must be symmetric, square, and be connected
    """
    n = len(c_m)
    if not c_m:
        return (False, [])
    num_cols = len(c_m[0])
    # the n x m check
    if any(len(row) != num_cols for row in c_m):
        return (False, [])
    # square check required for symmetry
    if n != num_cols:
        return (False, [])
    # the symm check
    for i in range(n):
        for j in range(num_cols):
            if c_m[i][j] != c_m[j][i]:
                return (False, [])
    dist = floyd_warshall(c_m)[0]
    # the connected check
    return all(dist[i][j] != INF for i in range(n) for j in range(num_cols)), dist

def cal_centriod(points: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


def build_poisson_environment(rng: random.Random, c_m : list[list[float]]) -> tuple[Environment, EventHandler]:
    """Build a fully wired star environment and return (environment, event_handler).

    Creates zones, restaurant, drivers, and seeds the event_handler with
    OrderArriveEvents and DriverReadyEvents. 
    """

    # --- zone and resturants ---
    zones: dict[int, Zone] = {}
    rest_list: list[Restaurant] = []

    for zone_id, rests_info in ZONE_INFO.items():
        rests: dict[int, Restaurant] = {}
        for rest_info in rests_info:
            res = Restaurant(zone_id=zone_id,
                             position=rest_info[0],
                             capacity=None)
            rests[res.restaurant_id] = res
            rest_list.append(res)
        zone = Zone(restaurants= rests,
                    idle_drivers={},
                    busy_drivers={},
                    zone_centriod=cal_centriod([info[0] for info in rests_info]),)
        zones[zone_id] = zone

    restaurants: dict[int, Restaurant] = {}
    for zone in zones.values():
        restaurants |= zone.restaurants

    # --- drivers, creating and putting the event in ---
    drivers: dict[int, Driver] = {}

    for d_info in DRIVER_INFO:
        zone_id, pos = d_info[0], d_info[1]
        driver = Driver(zone_id=zone_id,
                        position=pos)
        zones[zone_id].idle_drivers[driver.driver_id] = driver
        drivers[driver.driver_id] = driver

    environment = Environment(zones=zones,
                              restaurants=restaurants,
                              drivers=drivers,
                              orders={},
                              travel_cost=TRAVEL_COST_CLASS,
                              obj_function=None,
                              warmup_duration=WARMUP_DURATION,
                              horizon=HORIZON,
                              ainfo=AuxInfo(c_m, None, None, None))
    
    event_handler = EventHandler(environment=environment, timeline=[])

    # --- orders ---
    orders: dict[int, Order] = {}
    rest_idx = 0
    for zone_id, vals in ZONE_INFO.items():
        for rest_config in vals:
            _, arrival_gen, order_spread = rest_config[0], rest_config[1], rest_config[2]
            orders |= arrival_gen(rng,
                                  HORIZON,
                                  rest_list[rest_idx],
                                  order_spread,
                                  environment.zones,
                                  ArrivalAuxInfo(1, 1, 1),
                                  environment)
            rest_idx += 1
    
    environment.orders = orders

    for o in orders.values():
        orderArrive = OrderArriveEvent(time = o.arrival_time,
                                   order = o,
                                   restaurant=environment.restaurants[o.restaurant_id])
        event_handler.push_event(orderArrive)


    # --- finishing drivers ---

    for d in environment.drivers.values():
        driverStart = DriverReadyEvent(time=0.0,
                                       driver=d,
                                       zone=environment.zones[d.curr_zone_id],
                                       location=d.curr_pt)
        event_handler.push_event(driverStart)
    
    return environment, event_handler

def run_baseline(seed: int, output: str | None = None) -> Results:
    """Run the poisson baseline experiment and return a Results object."""
    configure_logging(level=logging.INFO) # can change to logging.DEBUG

    val, c_m = verify_cost_matrix(COST_MATRIX)
    assert val, "cost_matrix must be symmetric, nxm, and connected"

    rng: random.Random = random.Random(seed)

    environment, event_handler = build_poisson_environment(rng, c_m)

    policy = None
    if POLICY_NAME == "eaf":
        policy = eaf.EAF()
    elif POLICY_NAME == "erf":
        policy = erf.ERF()
    else:
        raise ValueError(
            "unhandled policy"
        )
    assert policy
    engine = SimEngine(environment=environment,
                       event_handler=event_handler,
                       policy=policy)
    engine.run()

    metrics = compute_metrics(
        env=environment,
        metric_names=LIST_OF_METRICS,
        ainfo=environment.ainfo,
    )

    completed = [o for o in environment.orders.values()
                 if o.order_status == OrderStatus.DELIVERED]

    results = Results(
        metrics=metrics,
        completed_orders=completed,
        config={
            "experiment":      EXPERIMENT_NAME,
            "policy":          POLICY_NAME, # remember to change this!
            "horizon":         HORIZON,
            "warmup_duration": WARMUP_DURATION,
            "num_drivers":     len(environment.drivers),
            "num_zones":    len(environment.zones),
            "num_restaurants": len(environment.restaurants),
            "distances":       c_m,
            "input_cost_matrix": COST_MATRIX,
            "computed_distances_from_cost_matrix": environment.ainfo.c_matrix,
        },
        seed=seed,
        event_log=[repr(e) for e in event_handler.handled_events],
        orders=list(environment.orders.values()),
        drivers=list(environment.drivers.values()),
        batches=environment.batches,
    )

    if output is not None:
        save_dir = os.path.join(output, EXPERIMENT_NAME)
        results.save(save_dir)

        timeline = build_timeline(save_dir)
        viz = render(timeline, results.config | {"seed": seed})
        with open(os.path.join(save_dir, "timeline.txt"), "w") as f:
            f.write(_strip_ansi(viz))

        save_filtered(save_dir)

        plot_all(save_dir)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Run {EXPERIMENT_NAME} graph baseline experiment")
    parser.add_argument("--output", default="/home/jinhuangzhou/cs145/old/experimental_results", help="Directory to write to")
    parser.add_argument("--seed", type=int, default=RUN_SEED, help=f"Random seed {RUN_SEED}")
    args = parser.parse_args()

    run_baseline(seed=args.seed, output=args.output)

