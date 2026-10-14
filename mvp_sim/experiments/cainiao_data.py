"""
Real-data experiment mirroring poisson.py but built from the four JSON files
produced by real_data_helpers/.

Pipeline:
    1. Run real_data_helpers/ scripts to produce:
           zones.json, cost_matrix.json, orders.json, drivers.json
    2. Run this experiment:
           python -m mvp_sim.experiments.cainiao_data --zones <zones.json>
               --cost-matrix <cost_matrix.json> --output <dir> [--seed <int>]

Differences from poisson.py:
    - Zone/restaurant/driver layout comes from JSON, not hardcoded config.
    - cost_matrix.json (haversine km) replaces the hardcoded COST_MATRIX.
    - Arrival generator and order spread are still synthetic — assign them
      per restaurant below via ARRIVAL_GEN and ORDER_SPREAD.
"""

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time

from mvp_sim.core.driver import Driver
from mvp_sim.core.environment import Environment
from mvp_sim.core.order import Order, OrderStatus
from mvp_sim.core.restaurant import Restaurant
from mvp_sim.core.zone import Zone
from mvp_sim.cost_functions.travel_time import (
    AuxInfo,
    TravelCost,
    zone_fixed_cost_matrix,
    sublinear_intrazone,
    floyd_warshall,
)
from mvp_sim.experiments.scenario import (
    CANONICAL_DAY,
    Scenario,
    WARMUP_FRACTION,
    build_scenario,
    clean_and_filter_csv,
    roster_prefix,
)
from mvp_sim.experiments.real_data_helpers import cost_maker, order_maker, resturant_and_zone_maker
from mvp_sim.logger.logger import configure_logging
from mvp_sim.policies.general_policies import eaf, erf, klapp, nearest_neighbor, sn, sn_NoReposition, cals
from mvp_sim.results.results import Results
from mvp_sim.simulator.engine import SimEngine
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.simulator.events import OrderArriveEvent, DriverReadyEvent
from mvp_sim.stats.metrics import compute_metrics
from mvp_sim.tools.visualize_timeline import build_timeline, render, _strip_ansi
from mvp_sim.tools.filter_events import save_filtered
from mvp_sim.tools.plot_timeline import plot_all
from mvp_sim.experiments.real_data_helpers import (
    drivers_maker,
)

import math
import numpy as np

SN_SWEEP_ADJUSTERS: list[float] = [0.2, 0.5, 1.0, 2.0, 4.0]
DRIVER_SWEEP_FRACTIONS: list[float] = [0.10, 0.25, 0.50, 0.75, 1.00]
# Supply levels are nested prefixes of the scenario's once-shuffled roster; see
# scenario.roster_prefix. There is deliberately no separate subsample seed -- the
# old one re-sampled independently at each level, so the levels were not nested.

INF = math.inf

POLICY_NAME: str = "eaf"
EXPERIMENT_NAME: str = "cainiao_data"

# Orders arriving before this time are excluded from every metric. Note that the
# horizon is the last *arrival*, and arrivals are dense early (per restaurant the
# times are a cumulative sum of Exp(lambda) draws), so a warm-up of 5 discards a
# large share of a small city's orders -- roughly 80% of Jilin's 213 and 63% of
# Yantai's 1051, versus about a third in Chongqing. It is applied identically to
# every policy, so comparisons stay valid, but it costs statistical power. Expose
# it as --warmup and record it with every run rather than leaving it implicit.
WARMUP_DURATION: float = 5  # legacy explicit-minute override

LIST_OF_METRICS: list[str] = [
    "total_orders", "arrived_orders", "delivered_orders", "undelivered_orders",
    "completion_rate", "flow_time", "travel_time", "makespan",
    "avg_batch_size", "batch_efficiency",
    "driver_utilization", "driver_utilization_makespan",
]

# The paper's service model is tau(i,j,k) = D[z(i),j] + c(j)k^alpha, which is
# sublinear_intrazone. zone_fixed_cost_matrix charges the matrix diagonal per
# additional stop, making batch cost *linear* in k -- it is kept only so older
# runs remain reproducible, and must not be used for headline results.
_TRAVEL_COSTS: dict[str, TravelCost] = {
    "sublinear_intrazone": sublinear_intrazone(),
    "zone_fixed_cost_matrix": zone_fixed_cost_matrix(),
}
DEFAULT_COST_FUNCTION: str = "sublinear_intrazone"


def resolve_travel_cost(name: str) -> TravelCost:
    if name not in _TRAVEL_COSTS:
        raise ValueError(f"Unknown cost function {name!r}. Valid: {sorted(_TRAVEL_COSTS)}")
    return _TRAVEL_COSTS[name]

# NOTE: arrival generation now lives in experiments/scenario.py, where it happens
# once per (city, seed) and is replayed. The local poisson_arr that used to be
# here was called per policy from a shared advancing RNG, which is what gave every
# policy a different trace. mvp_sim.arrivals.generators still has a poisson_arr
# for the synthetic poisson.py/star.py experiments.

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


def build_real_data_environment(
    zones_path: str,
    scenario: Scenario,
    c_m: list[list[float]],
    drivers_override: list[dict] | None = None,
) -> tuple[Environment, EventHandler]:
    """Build a fully wired environment by replaying a Scenario.

    Takes no RNG. Every stochastic quantity -- arrival times, driver placement,
    roster ordering -- was drawn once when the Scenario was built, so two calls
    with the same Scenario produce byte-identical inputs. This is what makes a
    cross-policy comparison valid.

    drivers_override: the roster subset for a supply level (see roster_prefix).
    Defaults to the scenario's full roster.
    """

    with open(zones_path) as f:
        zones_json: dict = json.load(f)

    # --- zones and restaurants ---
    zones: dict[int, Zone] = {}

    for zid_str, zone_data in sorted(zones_json.items(), key=lambda x: int(x[0])):
        rests: dict[int, Restaurant] = {}
        for rest_data in sorted(zone_data["restaurants"].values(), key=lambda r: r["restaurant_id"]):
            rest = Restaurant(
                zone_id=int(zid_str),
                position=tuple(rest_data["position"]),
                capacity=None,
                restaurant_id=rest_data["restaurant_id"],
            )
            rests[rest.restaurant_id] = rest

        zone = Zone(
            restaurants=rests,
            idle_drivers={},
            busy_drivers={},
            zone_centriod=tuple(zone_data["zone_centriod"]),
            zone_id=int(zid_str),
        )
        zones[zone.zone_id] = zone

    restaurants: dict[int, Restaurant] = {}
    for zone in zones.values():
        restaurants |= zone.restaurants

    # --- drivers ---
    # Driver ids come from the scenario roster, so the same physical driver keeps
    # the same id across policies and across supply levels.
    drivers: dict[int, Driver] = {}
    drivers_json = scenario.roster if drivers_override is None else drivers_override

    for d_data in drivers_json:
        driver = Driver(
            zone_id=d_data["curr_zone_id"],
            position=tuple(d_data["curr_pt"]),
            driver_id=d_data["driver_id"],
        )
        zones[d_data["curr_zone_id"]].idle_drivers[driver.driver_id] = driver
        drivers[driver.driver_id] = driver

    # --- environment ---
    cp = scenario.cost_params
    environment = Environment(
        zones=zones,
        restaurants=restaurants,
        drivers=drivers,
        orders={},
        travel_cost=resolve_travel_cost(cp.cost_function),
        obj_function=None,
        warmup_duration=scenario.warmup_duration,
        horizon=scenario.horizon,
        ainfo=AuxInfo(
            c_m,
            None,
            None,
            None,
            batch_alpha=cp.batch_alpha,
            zone_scale=cp.zone_scale,
        ),
    )

    event_handler = EventHandler(environment=environment, timeline=[])

    # --- orders replayed verbatim from the scenario trace ---
    orders: dict[int, Order] = {}
    for o_data in scenario.orders:
        order = Order(restaurant_id=o_data["restaurant_id"],
                    destination_zone_id=o_data["destination_zone_id"],
                    destination=tuple(o_data["destination"]),
                    arrival_time=o_data["arrival_time"],
                    prep_time=0,
                    deadline=None,
                    profit=0,
                    order_id=o_data["order_id"])
        orders[order.order_id] = order

    environment.orders = orders

    for o in orders.values():
        event_handler.push_event(
            OrderArriveEvent(
                time=o.arrival_time,
                order=o,
                restaurant=environment.restaurants[o.restaurant_id],
            )
        )

    # --- driver ready events ---
    for d in environment.drivers.values():
        event_handler.push_event(
            DriverReadyEvent(
                time=0.0,
                driver=d,
                zone=environment.zones[d.curr_zone_id],
                location=d.curr_pt,
            )
        )

    return environment, event_handler


# Driver starting positions are sampled uniformly in the zone bounding box and
# snapped to the nearest centroid. That draw belongs to the city layout, not to a
# replicate, so it uses a fixed seed: prepared data is then a pure function of
# (csv, day, speed) and can be shared by every seed and policy.
DRIVER_POSITION_SEED: int = 20240610


def prepare_data(
    csv_path: str,
    out_dir: str,
    data_day: str = CANONICAL_DAY,
    speed_km_per_min: float = 1.0,
) -> tuple[str, str, str, str, dict]:
    """Produce the four JSON inputs from a raw city CSV.

    The raw feed spans months and contains rows with missing GPS, neither of which
    the maker scripts tolerate, so it is cleaned and filtered to a single day
    first. Returns the four paths plus a summary of what the filter did, for the
    run manifest.
    """
    os.makedirs(out_dir, exist_ok=True)
    filtered_csv    = os.path.join(out_dir, "filtered.csv")
    zones_path      = os.path.join(out_dir, "zones.json")
    orders_path     = os.path.join(out_dir, "orders.json")
    drivers_path    = os.path.join(out_dir, "drivers.json")
    cost_matrix_path = os.path.join(out_dir, "cost_matrix.json")

    data_summary = clean_and_filter_csv(csv_path, filtered_csv, data_day=data_day)

    orig_argv = sys.argv
    try:
        sys.argv = ["", filtered_csv, zones_path]
        resturant_and_zone_maker.main()

        sys.argv = ["", filtered_csv, zones_path, orders_path]
        order_maker.main()

        sys.argv = ["", filtered_csv, zones_path, drivers_path]
        drivers_maker.main(random.Random(DRIVER_POSITION_SEED))

        sys.argv = ["", zones_path, cost_matrix_path, "--speed", str(speed_km_per_min)]
        cost_maker.main()
    finally:
        sys.argv = orig_argv

    data_summary["driver_position_seed"] = DRIVER_POSITION_SEED
    data_summary["speed_km_per_min"] = speed_km_per_min
    return zones_path, cost_matrix_path, drivers_path, orders_path, data_summary


def run_baseline(
    zones_path: str,
    cost_matrix_path: str,
    scenario: Scenario,
    output: str | None = None,
    per_driver_plots: bool = True,
    order_gantt_plot: bool = True,
    policy=None,
    policy_name: str | None = None,
    drivers_override: list[dict] | None = None,
    experiment_name: str | None = None,
    supply_fraction: float = 1.0,
    save_dir_override: str | None = None,
    make_plots: bool = True,
    light: bool = False,
) -> Results:
    """Run one policy against one scenario at one supply level."""
    configure_logging(level=logging.INFO)

    exp_name = experiment_name if experiment_name is not None else EXPERIMENT_NAME

    with open(cost_matrix_path) as f:
        raw_cm: list[list[float]] = json.load(f)

    val, c_m = verify_cost_matrix(raw_cm)
    assert val, "cost_matrix must be symmetric, nxm, and connected"

    environment, event_handler = build_real_data_environment(
        zones_path, scenario, c_m,
        drivers_override=drivers_override,
    )

    if policy is None:
        policy = eaf.EAF()
    if policy_name is None:
        policy_name = POLICY_NAME
    engine = SimEngine(environment=environment, event_handler=event_handler, policy=policy)
    simulation_started = time.perf_counter()
    engine.run()
    simulation_runtime_seconds = time.perf_counter() - simulation_started

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
            "experiment":       exp_name,
            "policy":           policy_name,
            "policy_config":    describe_policy(policy),
            "horizon":          environment.horizon,
            "warmup_duration":  scenario.warmup_duration,
            "warmup_fraction":  scenario.warmup_fraction,
            "simulation_runtime_seconds": simulation_runtime_seconds,
            "num_drivers":      len(environment.drivers),
            "num_zones":        len(environment.zones),
            "num_restaurants":  len(environment.restaurants),
            # Provenance: everything needed to prove two runs are comparable.
            "supply_fraction":  supply_fraction,
            "driver_ids":       sorted(environment.drivers.keys()),
            "scenario":         scenario.manifest(),
            # The matrix itself is identical for every run of a city and is stored
            # once under prepared/<city>/cost_matrix.json. Three copies per run
            # added ~190 KB to each config for no information; keep a digest so a
            # run can still be proved to have used the expected matrix.
            "cost_matrix_path": os.path.abspath(cost_matrix_path),
            "cost_matrix_sha":  hashlib.sha256(
                json.dumps(raw_cm, sort_keys=True).encode()).hexdigest()[:16],
            "cost_matrix_dim":  len(raw_cm),
        },
        seed=scenario.experiment_seed,
        event_log=[repr(e) for e in event_handler.handled_events],
        orders=list(environment.orders.values()),
        drivers=list(environment.drivers.values()),
        batches=environment.batches,
    )

    if output is not None:
        save_dir = save_dir_override or os.path.join(output, exp_name, policy_name)
        # The plotting tools read events.log and orders.json, which `light` skips,
        # so plotting always forces the full artifact set rather than failing on a
        # missing file partway through a long suite.
        results.save(save_dir, light=light and not make_plots)

        if make_plots:
            timeline = build_timeline(save_dir)
            viz = render(timeline, results.config | {"seed": scenario.experiment_seed})
            with open(os.path.join(save_dir, "timeline.txt"), "w") as f:
                f.write(_strip_ansi(viz))

            save_filtered(save_dir)
            plot_all(save_dir, per_driver=per_driver_plots, order_gantt=order_gantt_plot)

    return results

def describe_policy(policy) -> dict:
    """Every tunable a policy was constructed with, for the result config.

    Read off the instance rather than a hand-maintained table so a parameter can
    never be added to a policy and silently omitted from the record.
    """
    desc: dict = {"class": type(policy).__name__}
    for name, value in sorted(vars(policy).items()):
        if name.startswith("_"):
            continue                      # private mutable run state, not a tunable
        if isinstance(value, (int, float, str, bool)) or value is None:
            desc[name] = value
    return desc


# The canonical comparison, frozen. CALS weights and the SN travel-cost adjuster
# below are the configurations reported in the paper; any tuning must happen in a
# separate validation sweep (--sweep-sn) and must not be selected from the same
# runs used for headline numbers.
CANONICAL_CALS_MIXED: dict[str, float] = {"w_a": 2.0, "w_c": 5.0}
CANONICAL_SN_ADJUSTER: float = 1.0


def _build_policies(
    sweep_sn: bool = False,
    no_baselines: bool = False,
    seed: int = 0,
) -> list[tuple[str, object]]:
    """Instantiate the canonical policy set.

    `seed` is threaded into every policy that makes stochastic retry decisions so
    that the master experiment seed fully determines the run.
    """
    policies: list[tuple[str, object]] = []
    if not no_baselines:
        policies += [
            # --- temporal and spatial greedy baselines ---
            ("erf",              erf.ERF(seed=seed)),
            ("eaf",              eaf.EAF(seed=seed)),
            ("nearest_neighbor", nearest_neighbor.NearestNeighbor(seed=seed)),
            # --- CALS weight ablation: none / urgency only / coverage only / mixed ---
            ("cals_noweights",   cals.CALS(w_a=0.0, w_c=0.0)),
            ("cals_urgency",     cals.CALS(w_a=2.0, w_c=0.0)),
            ("cals_coverage",    cals.CALS(w_a=0.0, w_c=2.0)),
            ("cals_mixed",       cals.CALS(**CANONICAL_CALS_MIXED)),
        ]
    if sweep_sn:
        policies += [(f"sn_adj_{adj}", sn.SN(adjuster=adj)) for adj in SN_SWEEP_ADJUSTERS]
    else:
        policies += [
            ("sn",               sn.SN(adjuster=CANONICAL_SN_ADJUSTER)),
            # Repositioning ablation: isolates the value of the chain-repositioning
            # mechanism from the value of projected-availability matching.
            ("sn_noreposition",  sn_NoReposition.SNNoReposition(adjuster=CANONICAL_SN_ADJUSTER)),
        ]
    return policies


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Run {EXPERIMENT_NAME} experiment")
    parser.add_argument("--csv", 
                        required=True,
                        help="Path to raw delivery CSV")
    parser.add_argument("--output", 
                        required=True,
                        help="Directory to write results into")
    parser.add_argument("--seed", 
                        type=int,
                        required=True,
                        help=f"Random seed)")
    parser.add_argument("--no-per-driver-plots", 
                        action="store_true", 
                        help="Skip per-driver PNG generation (~8 min for 671 drivers)")
    parser.add_argument("--no-order-gantt", 
                        action="store_true", 
                        help="Skip order_gantt.png (slow with 14k+ orders)")
    parser.add_argument("--sweep-sn", 
                        action="store_true",
                        help=f"Run SN at adjuster values {SN_SWEEP_ADJUSTERS} instead of a single default run")
    parser.add_argument("--no-baselines", 
                        action="store_true",
                        help="Skip EAF/ERF/Klapp/NearestNeighbor; run only SN (or the SN sweep)")
    parser.add_argument("--driver-sweep", 
                        action="store_true",
                        help=f"Run all policies at driver fractions {DRIVER_SWEEP_FRACTIONS}; "
                             f"saves to <output>/cainiao_data_driver_sweep/frac_NNN/")
    parser.add_argument("--day",
                        default=CANONICAL_DAY,
                        help=f"ds (MMDD) subset to model (default: {CANONICAL_DAY}, reproduces Table I)")
    parser.add_argument("--cost-function",
                        default=DEFAULT_COST_FUNCTION,
                        choices=sorted(_TRAVEL_COSTS),
                        help=f"Batch service-time model (default: {DEFAULT_COST_FUNCTION})")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="km per minute used to convert haversine km to travel minutes")
    parser.add_argument("--batch-alpha", type=float, default=0.5,
                        help="Sublinear within-zone batch exponent (default: 0.5)")
    warmup = parser.add_mutually_exclusive_group()
    warmup.add_argument("--warmup", type=float, default=None,
                        help="Explicit warm-up duration in simulation minutes")
    warmup.add_argument("--warmup-fraction", type=float, default=WARMUP_FRACTION,
                        help=f"Fraction of the arrival horizon excluded from metrics "
                             f"(default: {WARMUP_FRACTION})")
    args = parser.parse_args()

    prep_dir = os.path.join(args.output, "prepared_data")

    zones_path, cost_matrix_path, drivers_path, orders_path, data_summary = prepare_data(
        args.csv, prep_dir, data_day=args.day, speed_km_per_min=args.speed,
    )

    with open(cost_matrix_path) as f:
        raw_cm = json.load(f)

    # One trace and one roster for this (city, seed), replayed by every policy below.
    scenario = build_scenario(
        zones_path=zones_path,
        orders_path=orders_path,
        drivers_path=drivers_path,
        cost_matrix=raw_cm,
        city=os.path.basename(args.csv),
        experiment_seed=args.seed,
        roster_seed=args.seed,
        data_day=args.day,
        warmup_duration=args.warmup,
        warmup_fraction=args.warmup_fraction,
        cost_function=args.cost_function,
        speed_km_per_min=args.speed,
        batch_alpha=args.batch_alpha,
    )
    scenario.save(os.path.join(prep_dir, f"scenario_seed{args.seed}.json"))
    print(f"scenario: trace={scenario.trace_hash} roster={scenario.roster_hash} "
          f"orders={len(scenario.orders)} horizon={scenario.horizon}")

    per_driver_plots: bool = not args.no_per_driver_plots
    order_gantt_plot: bool = not args.no_order_gantt

    if args.driver_sweep:
        for frac in DRIVER_SWEEP_FRACTIONS:
            subsample = roster_prefix(scenario, frac)
            pct = round(frac * 100)
            exp_name = f"cainiao_data_driver_sweep/frac_{pct:03d}/cainiao_data"
            print(f"\n=== Driver sweep: {pct}% ({len(subsample)}/{len(scenario.roster)} drivers) ===")
            for pname, pol in _build_policies(args.sweep_sn, args.no_baselines, seed=args.seed):
                run_baseline(
                    zones_path=zones_path,
                    cost_matrix_path=cost_matrix_path,
                    scenario=scenario,
                    output=args.output,
                    per_driver_plots=per_driver_plots,
                    order_gantt_plot=order_gantt_plot,
                    policy=pol,
                    policy_name=pname,
                    drivers_override=subsample,
                    experiment_name=exp_name,
                    supply_fraction=frac,
                )
    else:
        for pname, pol in _build_policies(args.sweep_sn, args.no_baselines, seed=args.seed):
            run_baseline(
                zones_path=zones_path,
                cost_matrix_path=cost_matrix_path,
                scenario=scenario,
                output=args.output,
                per_driver_plots=per_driver_plots,
                order_gantt_plot=order_gantt_plot,
                policy=pol,
                policy_name=pname,
            )
