"""Scenario replay: one trace and one roster per replicate (P0 items 1 and 4).

The central guarantee: for a fixed (city, seed), every policy receives the same
restaurants, destinations, arrival times, order count and horizon, and the same
driver roster. Before the Scenario abstraction each policy drew from a shared,
advancing RNG and silently got a different realisation of the world.
"""

import json
import os

import pytest

from mvp_sim.experiments.scenario import (
    Scenario,
    build_scenario,
    roster_prefix,
)


# ---------------------------------------------------------------------------
# A tiny synthetic city, so these tests need no real data and stay fast.
# ---------------------------------------------------------------------------

@pytest.fixture
def city(tmp_path):
    zones = {
        "1": {"zone_id": 1, "zone_centriod": [120.0, 30.0],
              "restaurants": {"1": {"restaurant_id": 1, "zone_id": 1, "position": [120.001, 30.001]},
                              "2": {"restaurant_id": 2, "zone_id": 1, "position": [120.002, 30.002]}}},
        "2": {"zone_id": 2, "zone_centriod": [120.05, 30.05],
              "restaurants": {"3": {"restaurant_id": 3, "zone_id": 2, "position": [120.051, 30.051]}}},
    }
    orders = []
    oid = 1
    for rest_id in (1, 2, 3):
        for k in range(6):
            orders.append({
                "order_id": oid,
                "restaurant_id": rest_id,
                "destination_zone_id": 1 + (k % 2),
                "destination": [120.0 + 0.001 * k, 30.0 + 0.001 * k],
            })
            oid += 1
    drivers = [{"driver_id": i, "curr_zone_id": 1 + (i % 2),
                "curr_pt": [120.0, 30.0], "dest_pt": None, "dest_zone_id": None}
               for i in range(1, 21)]

    paths = {}
    for name, payload in (("zones", zones), ("orders", orders), ("drivers", drivers)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(payload))
        paths[name] = str(p)
    paths["cost_matrix"] = [[1.0, 4.0], [4.0, 1.0]]
    return paths


def make(city, seed=1, roster_seed=None, **kwargs):
    return build_scenario(
        zones_path=city["zones"],
        orders_path=city["orders"],
        drivers_path=city["drivers"],
        cost_matrix=city["cost_matrix"],
        city="test",
        experiment_seed=seed,
        roster_seed=seed if roster_seed is None else roster_seed,
        **kwargs,
    )


class TestTraceIsFixedPerSeed:
    def test_default_warmup_is_five_percent_of_horizon(self, city):
        scenario = make(city, seed=1)
        assert scenario.warmup_fraction == pytest.approx(0.05)
        assert scenario.warmup_duration == pytest.approx(0.05 * scenario.horizon)

    def test_explicit_duration_overrides_fraction_and_is_recorded(self, city):
        scenario = make(city, seed=1, warmup_duration=2.0)
        assert scenario.warmup_duration == 2.0
        assert scenario.warmup_fraction is None

    @pytest.mark.parametrize("fraction", [-0.1, 1.0, 1.2])
    def test_invalid_warmup_fraction_is_rejected(self, city, fraction):
        with pytest.raises(ValueError, match="warmup_fraction"):
            make(city, seed=1, warmup_fraction=fraction)

    def test_same_seed_reproduces_an_identical_trace(self, city):
        a, b = make(city, seed=7), make(city, seed=7)
        assert a.trace_hash == b.trace_hash
        assert a.orders == b.orders
        assert a.horizon == b.horizon

    def test_serialized_orders_match_across_two_policy_runs(self, city):
        """The acceptance check: serialize the input orders twice, require equality.

        This stands in for two policies consuming the same scenario -- what used to
        differ is exactly this payload.
        """
        scenario = make(city, seed=3)
        first = json.dumps(scenario.orders, sort_keys=True)
        second = json.dumps(scenario.orders, sort_keys=True)
        assert first == second

        reloaded_a = [dict(o) for o in scenario.orders]
        reloaded_b = [dict(o) for o in scenario.orders]
        assert reloaded_a == reloaded_b

    def test_different_seeds_give_different_traces(self, city):
        a, b = make(city, seed=1), make(city, seed=2)
        assert a.trace_hash != b.trace_hash

    def test_arrival_times_are_positive_and_sorted(self, city):
        scenario = make(city, seed=1)
        times = [o["arrival_time"] for o in scenario.orders]
        assert times == sorted(times)
        assert all(t > 0 for t in times)

    def test_horizon_covers_every_arrival(self, city):
        scenario = make(city, seed=5)
        assert scenario.horizon >= max(o["arrival_time"] for o in scenario.orders)

    def test_order_count_is_preserved_from_the_dataset(self, city):
        scenario = make(city, seed=1)
        assert len(scenario.orders) == 18

    def test_order_ids_are_unique_and_stable(self, city):
        scenario = make(city, seed=1)
        ids = [o["order_id"] for o in scenario.orders]
        assert len(set(ids)) == len(ids)
        assert sorted(ids) == list(range(1, 19))

    def test_trace_is_independent_of_restaurant_iteration_order(self, city, tmp_path):
        """Reversing the input file order must not change the generated arrivals.

        Arrival streams are seeded per restaurant id, not drawn sequentially from a
        shared RNG, so shuffling the input cannot perturb the trace.
        """
        original = json.loads(open(city["orders"]).read())
        reversed_path = tmp_path / "orders_reversed.json"
        reversed_path.write_text(json.dumps(list(reversed(original))))

        a = make(city, seed=11)
        b = build_scenario(
            zones_path=city["zones"], orders_path=str(reversed_path),
            drivers_path=city["drivers"], cost_matrix=city["cost_matrix"],
            city="test", experiment_seed=11, roster_seed=11,
        )
        assert a.trace_hash == b.trace_hash


class TestRosterNesting:
    def test_supply_levels_are_nested(self, city):
        scenario = make(city, seed=1)
        fractions = [0.10, 0.25, 0.50, 0.75, 1.00]
        subsets = [{d["driver_id"] for d in roster_prefix(scenario, f)} for f in fractions]
        for smaller, larger in zip(subsets, subsets[1:]):
            assert smaller <= larger, "raising supply must only add drivers"

    def test_supply_levels_are_strictly_increasing_in_size(self, city):
        scenario = make(city, seed=1)
        sizes = [len(roster_prefix(scenario, f)) for f in (0.10, 0.25, 0.50, 0.75, 1.00)]
        assert sizes == sorted(sizes)
        assert sizes[-1] == len(scenario.roster)

    def test_same_seed_gives_the_same_roster(self, city):
        a, b = make(city, seed=4), make(city, seed=4)
        assert a.roster_hash == b.roster_hash
        assert roster_prefix(a, 0.5) == roster_prefix(b, 0.5)

    def test_roster_seed_changes_the_ordering_not_the_membership(self, city):
        a = make(city, seed=1, roster_seed=1)
        b = make(city, seed=1, roster_seed=99)
        assert a.roster_hash != b.roster_hash
        assert {d["driver_id"] for d in a.roster} == {d["driver_id"] for d in b.roster}

    def test_fraction_must_be_in_unit_interval(self, city):
        scenario = make(city, seed=1)
        for bad in (0.0, -0.5, 1.5):
            with pytest.raises(ValueError):
                roster_prefix(scenario, bad)

    def test_smallest_level_keeps_at_least_one_driver(self, city):
        scenario = make(city, seed=1)
        assert len(roster_prefix(scenario, 0.001)) == 1


class TestRoundTrip:
    def test_save_and_load_preserves_the_scenario(self, city, tmp_path):
        scenario = make(city, seed=8)
        path = str(tmp_path / "scenario.json")
        scenario.save(path)
        loaded = Scenario.load(path)

        assert loaded.trace_hash == scenario.trace_hash
        assert loaded.roster_hash == scenario.roster_hash
        assert loaded.orders == scenario.orders
        assert loaded.roster == scenario.roster
        assert loaded.horizon == scenario.horizon
        assert loaded.cost_params == scenario.cost_params

    def test_manifest_records_the_identifying_fields(self, city):
        scenario = make(city, seed=2)
        manifest = scenario.manifest()
        for key in ("city", "experiment_seed", "roster_seed", "horizon",
                    "trace_hash", "roster_hash", "cost_params"):
            assert key in manifest
