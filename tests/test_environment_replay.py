"""End-to-end replay through the real environment builder (P0 item 1).

FEEDBACK-V2's acceptance check for item 1 asks specifically for a test that
"compares the serialized input orders for two different policies and requires
them to match". This exercises the actual code path a policy run takes --
build_real_data_environment -- rather than only the Scenario object, and drives
it once per policy exactly as the runner does.
"""

import json

import pytest

from mvp_sim.experiments.cainiao_data import build_real_data_environment
from mvp_sim.experiments.scenario import build_scenario, roster_prefix
from mvp_sim.policies.general_policies import cals, eaf, erf, nearest_neighbor, sn
from mvp_sim.simulator.engine import SimEngine

C_MATRIX = [[1.0, 4.0], [4.0, 1.0]]


@pytest.fixture
def city(tmp_path):
    zones = {
        "1": {"zone_id": 1, "zone_centriod": [120.0, 30.0],
              "restaurants": {"1": {"restaurant_id": 1, "zone_id": 1, "position": [120.001, 30.001]},
                              "2": {"restaurant_id": 2, "zone_id": 1, "position": [120.002, 30.002]}}},
        "2": {"zone_id": 2, "zone_centriod": [120.05, 30.05],
              "restaurants": {"3": {"restaurant_id": 3, "zone_id": 2, "position": [120.051, 30.051]}}},
    }
    orders, oid = [], 1
    for rest_id in (1, 2, 3):
        for k in range(5):
            orders.append({"order_id": oid, "restaurant_id": rest_id,
                           "destination_zone_id": 1 + (k % 2),
                           "destination": [120.0 + 0.001 * k, 30.0 + 0.001 * k]})
            oid += 1
    drivers = [{"driver_id": i, "curr_zone_id": 1 + (i % 2), "curr_pt": [120.0, 30.0]}
               for i in range(1, 9)]

    paths = {}
    for name, payload in (("zones", zones), ("orders", orders), ("drivers", drivers)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(payload))
        paths[name] = str(p)
    return paths


@pytest.fixture
def scenario(city):
    return build_scenario(
        zones_path=city["zones"], orders_path=city["orders"],
        drivers_path=city["drivers"], cost_matrix=C_MATRIX,
        city="test", experiment_seed=1, roster_seed=1, warmup_duration=1.0,
    )


def serialize_inputs(env) -> str:
    """The input side of a run: what each policy was actually given."""
    return json.dumps(
        [
            {"order_id": o.order_id, "restaurant_id": o.restaurant_id,
             "destination_zone_id": o.destination_zone_id,
             "destination": list(o.destination),
             "arrival_time": round(o.arrival_time, 9)}
            for o in sorted(env.orders.values(), key=lambda o: o.order_id)
        ],
        sort_keys=True,
    )


POLICIES = [
    ("erf", lambda: erf.ERF(seed=1)),
    ("eaf", lambda: eaf.EAF(seed=1)),
    ("nn", lambda: nearest_neighbor.NearestNeighbor(seed=1)),
    ("cals", lambda: cals.CALS(w_a=2.0, w_c=5.0)),
    ("sn", lambda: sn.SN(adjuster=1.0)),
]


class TestEveryPolicyReceivesTheSameInputs:
    def test_serialized_input_orders_match_across_policies(self, city, scenario):
        """The literal acceptance check for P0 item 1."""
        serialized = {}
        for name, make_policy in POLICIES:
            env, handler = build_real_data_environment(city["zones"], scenario, C_MATRIX)
            SimEngine(environment=env, event_handler=handler, policy=make_policy()).run(progress=False)
            serialized[name] = serialize_inputs(env)

        distinct = set(serialized.values())
        assert len(distinct) == 1, (
            "policies received different input orders: "
            f"{ {n: hash(s) for n, s in serialized.items()} }"
        )

    def test_order_count_arrivals_and_horizon_match_across_policies(self, city, scenario):
        counts, arrivals, horizons = set(), set(), set()
        for _name, make_policy in POLICIES:
            env, handler = build_real_data_environment(city["zones"], scenario, C_MATRIX)
            SimEngine(environment=env, event_handler=handler, policy=make_policy()).run(progress=False)
            counts.add(len(env.orders))
            arrivals.add(tuple(sorted(round(o.arrival_time, 9) for o in env.orders.values())))
            horizons.add(env.horizon)

        assert len(counts) == 1, f"input-order counts differ: {counts}"
        assert len(arrivals) == 1, "arrival timestamps differ across policies"
        assert len(horizons) == 1, f"simulation horizons differ: {horizons}"

    def test_running_a_policy_does_not_mutate_the_scenario(self, city, scenario):
        """A run must not perturb the trace for whichever policy runs next."""
        before = (scenario.trace_hash, json.dumps(scenario.orders, sort_keys=True))
        env, handler = build_real_data_environment(city["zones"], scenario, C_MATRIX)
        SimEngine(environment=env, event_handler=handler, policy=erf.ERF(seed=1)).run(progress=False)
        after = (scenario.trace_hash, json.dumps(scenario.orders, sort_keys=True))
        assert before == after

    def test_order_ids_are_stable_across_sequential_runs(self, city, scenario):
        """Order and Driver ids come from module-global counters by default.

        Two runs in one process must still agree on ids, or per-order joins and the
        order_id tie-breakers inside policies silently diverge.
        """
        id_sets = []
        for _ in range(3):
            env, _handler = build_real_data_environment(city["zones"], scenario, C_MATRIX)
            id_sets.append(sorted(env.orders.keys()))
        assert id_sets[0] == id_sets[1] == id_sets[2]

    def test_driver_ids_are_stable_across_sequential_runs(self, city, scenario):
        id_sets = []
        for _ in range(3):
            env, _handler = build_real_data_environment(city["zones"], scenario, C_MATRIX)
            id_sets.append(sorted(env.drivers.keys()))
        assert id_sets[0] == id_sets[1] == id_sets[2]

    def test_supply_levels_give_every_policy_the_same_roster(self, city, scenario):
        subset = roster_prefix(scenario, 0.5)
        rosters = set()
        for _name, make_policy in POLICIES:
            env, handler = build_real_data_environment(
                city["zones"], scenario, C_MATRIX, drivers_override=subset,
            )
            SimEngine(environment=env, event_handler=handler, policy=make_policy()).run(progress=False)
            rosters.add(tuple(sorted(env.drivers.keys())))
        assert len(rosters) == 1
        assert len(next(iter(rosters))) == len(subset)


class TestUtilizationStaysBoundedOnRealRuns:
    @pytest.mark.parametrize("name,make_policy", POLICIES, ids=[p[0] for p in POLICIES])
    def test_utilization_within_bounds_after_a_real_run(self, city, scenario, name, make_policy):
        from mvp_sim.stats.metrics import busy_time_in_window

        env, handler = build_real_data_environment(city["zones"], scenario, C_MATRIX)
        SimEngine(environment=env, event_handler=handler, policy=make_policy()).run(progress=False)

        window = env.horizon - env.warmup_duration
        for driver in env.drivers.values():
            busy = busy_time_in_window(driver.busy_intervals, env.warmup_duration, env.horizon)
            assert 0.0 <= busy <= window + 1e-9, (
                f"{name}: driver {driver.driver_id} busy {busy} exceeds window {window}"
            )
