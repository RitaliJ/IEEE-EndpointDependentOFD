import argparse
import logging
import os
import random
import numpy

from mvp_sim.core.environment import Environment
from mvp_sim.core.order import Order, OrderStatus
from mvp_sim.core.driver import Driver
from mvp_sim.core.restaurant import Restaurant
from mvp_sim.core.zone import Zone
from mvp_sim.cost_functions.travel_time import star_graph_cost, AuxInfo, TravelCost
from mvp_sim.logger.logger import configure_logging
from mvp_sim.policies.star_policies import erf
from mvp_sim.policies.star_policies import eaf
from mvp_sim.results.results import Results
from mvp_sim.simulator.engine import SimEngine
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.simulator.events import OrderArriveEvent, DriverReadyEvent
from mvp_sim.stats.metrics import compute_metrics
from mvp_sim.tools.visualize_timeline import build_timeline, render, _strip_ansi
from mvp_sim.tools.filter_events import save_filtered
from mvp_sim.tools.plot_timeline import plot_all

"""
Star graph experiment.

Models a star-shaped road network: one central hub connected to N branches.
Travel cost between any two points always routes through the hub, so
cost(A → B) = dist(A) + dist(B), where dist is each vertex's distance to center.

Topology
--------
- One zone per physical vertex: center zone (dist=0) + one zone per branch.
- One restaurant at the center zone.  Drivers start at the center.
- Orders arrive at the restaurant and are destined for a random branch vertex.
- Order inter-arrival count is Poisson(lam = horizon / avg_branch_distance).

Running from the command line
------------------------------
    python -m mvp_sim.experiments.star --output <dir> [--seed <int>]

    --output   Directory to write results into. A subdirectory called "star"
               is created automatically (e.g. experimental_results/star/).
    --seed     Integer random seed (default: 42).

    Example:
        python -m mvp_sim.experiments.star --output experimental_results

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
    python -m mvp_sim.tools.visualize_timeline <output>/star
    python -m mvp_sim.tools.plot_timeline <output>/star

Using from Python
-----------------
    from mvp_sim.experiments.star import run_baseline
    results = run_baseline(seed=7, output="experimental_results")
    print(results.metrics)

Policies
--------
    Star_EAF  Earliest Anticipation First — dispatches toward the order
              whose estimated completion time (arrival + travel) is soonest.
    Star_ERF  Earliest Ready First — dispatches toward the order that
              arrived (and became ready) earliest.
    For both policies, all ready orders going to the same destination zone
    are batched together into one dispatch.
    To swap policy, change the policy= line in run_baseline().
"""

POLICY_NAME: str = "erf" # remember to change this!
EXPERIMENT_NAME: str = "star"
HORIZON: float = 50
WARMUP_DURATION = 5
NUM_DRIVERS:int = 1 
assert NUM_DRIVERS == 1, "policy star_eaf and star_erf policy only allows 1 driver"
MAX_BRANCHES:int = 5
RUN_SEED:int = 42
LIST_OF_METRICS:list[str] = ["total_orders", "flow_time", "travel_time",
                             "avg_batch_size", "batch_efficiency", "driver_utilization"]
TRAVEL_COST_CLASS: TravelCost = star_graph_cost() # travel cost class for star must be star_graph_cost

def build_star_graph(rng: random.Random, max_branches: int) -> dict[int, int]:
    """Return a random star graph as {vertex: distance_to_center}.

    Vertex 0 is the center (distance 0). The number of branches is drawn
    uniformly from [2, max_branches] and each branch distance from [1, max_branches].
    """
    branches = rng.randint(2, max_branches)
    distances: dict[int, int]= {0: 0}
    for i in range(branches):
        distances[i+1] = rng.randint(1, max_branches)
    return distances

def build_star_zones(star_graph: dict[int, int]) -> tuple[dict[int, Zone], dict[int, int]]:
    """Create one Zone per vertex in star_graph.

    Returns (zones, vertex_to_zone_id). The center (vertex 0) is placed at
    (0, 0) and branch i at (i, 0).
    """
    zones: dict[int, Zone] = {}
    vertex_to_zone_id: dict[int, int] = {}

    # one zone per vertex; center (vertex 0) at (0,0), branch i at (i,0)
    for vertex in star_graph:
        position = (vertex, 0)
        zone = Zone(restaurants={}, idle_drivers={}, busy_drivers={}, zone_centriod=position)
        zones[zone.zone_id] = zone
        vertex_to_zone_id[vertex] = zone.zone_id

    return zones, vertex_to_zone_id

def build_star_resturants(zones: dict[int, Zone],
                          vertex_to_zone_id: dict[int, int]) -> dict[int, Restaurant]:
    """Create one restaurant at the center zone (vertex 0) and register it in that zone."""
    center_zone_id = vertex_to_zone_id[0]
    center_zone = zones[center_zone_id]

    # restaurant lives at center
    restaurant = Restaurant(zone_id=center_zone_id, position=(0, 0))
    restaurants = {restaurant.restaurant_id: restaurant}
    center_zone.restaurants[restaurant.restaurant_id] = restaurant
    return restaurants

def build_star_drivers(zones: dict[int, Zone], vertex_to_zone_id: dict[int, int],
                       num_drivers: int) -> dict[int, Driver]:
    """Create num_drivers drivers, all starting idle at the center zone (vertex 0)."""
    center_zone_id = vertex_to_zone_id[0]
    center_zone = zones[center_zone_id]

    # driver starts at center
    drivers: dict[int, Driver] = {}
    for _ in range(num_drivers):
        driver = Driver(zone_id=center_zone_id, position=(0, 0))
        center_zone.idle_drivers[driver.driver_id] = driver
        drivers[driver.driver_id] = driver
    return drivers

def build_star_environment(star_graph: dict[int, int],
                           num_drivers: int,
                           rng: random.Random) -> tuple[Environment, EventHandler]:
    """Build a fully wired star environment and return (environment, event_handler).

    Creates zones, restaurant, drivers, and seeds the event_handler with
    OrderArriveEvents and DriverReadyEvents. 
    """
    zones, vertex_to_zone_id = build_star_zones(star_graph)

    restaurants= build_star_resturants(zones, vertex_to_zone_id)

    drivers = build_star_drivers(zones, vertex_to_zone_id, num_drivers)

    # ainfo graph keyed by zone_id
    zone_graph = {vertex_to_zone_id[v]: dist for v, dist in star_graph.items()}

    environment = Environment(zones=zones,
                              restaurants=restaurants,
                              drivers=drivers,
                              orders={},
                              travel_cost=TRAVEL_COST_CLASS,
                              obj_function=None,
                              warmup_duration=WARMUP_DURATION,
                              horizon=HORIZON,
                              ainfo=AuxInfo(None, None, None, zone_graph))
    
    event_handler = EventHandler(environment=environment, timeline=[])
    
    add_star_orders(environment, star_graph, vertex_to_zone_id, int(environment.horizon), 
                    rng, event_handler)
    
    add_drivers(environment, event_handler)
    
    return environment, event_handler


def add_star_orders(environment: Environment, distances: dict[int, int],
                    vertex_to_zone_id: dict[int, int], time_range: int, rng: random.Random,
                    event_handler: EventHandler) -> None:
    """Generate orders and push OrderArriveEvents into event_handler.

    Order count is Poisson(lam = time_range / avg_branch_distance). Each order
    has a uniformly random arrival time in [0, time_range] and is destined for
    a uniformly random branch vertex (never the center).
    """
    restaurant = list(environment.restaurants.values())[0]

    orders = {}
    avg_distance = sum(distances.values()) / (len(distances) - 1)
    num_orders = numpy.random.default_rng(rng.randint(0, 2**32 - 1)).poisson(lam=time_range / avg_distance)
    for i in range(num_orders):
        target = rng.randint(1, len(distances) - 1)
        time = rng.randint(0, time_range)
        order = Order(restaurant_id=restaurant.restaurant_id,
                      destination_zone_id=vertex_to_zone_id[target],
                      destination=(target, 0),
                      arrival_time=time,
                      prep_time=0,
                      deadline=None,
                      profit=0)
        orders[order.order_id] = order

    environment.orders = orders

    for order in environment.orders.values():
        orderArrive = OrderArriveEvent(time = order.arrival_time,
                                   order = order,
                                   restaurant=environment.restaurants[order.restaurant_id])
        event_handler.push_event(orderArrive)


def add_drivers(environment: Environment, event_handler: EventHandler) -> None:
    """Push a DriverReadyEvent at t=0 for every driver in environment."""
    for d in environment.drivers.values():
        driverStart = DriverReadyEvent(time=0.0,
                                       driver=d,
                                       zone=environment.zones[d.curr_zone_id],
                                       location=d.curr_pt)
        event_handler.push_event(driverStart)


def run_baseline(seed: int, output: str | None = None) -> Results:
    """Run the star baseline experiment and return a Results object."""
    configure_logging(level=logging.INFO) # can change to logging.DEBUG
    rng: random.Random = random.Random(seed)

    distances = build_star_graph(rng, MAX_BRANCHES)
    environment, event_handler = build_star_environment(distances, NUM_DRIVERS, rng)

    policy = None
    if POLICY_NAME == "eaf":
        policy = eaf.Star_EAF()
    elif POLICY_NAME == "erf":
        policy = erf.Star_ERF()
    else:
        raise ValueError(
            "star only takes eaf and erf as policies"
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
            "horizon":         environment.horizon,
            "warmup_duration": environment.warmup_duration,
            "num_drivers":     environment.drivers,
            "num_branches":    len(distances) - 1,
            "distances":       distances,
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
