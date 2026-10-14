"""Sublinear batch service cost (FEEDBACK-V2 P0 item 2).

The paper defines batch service time as

    tau(i, j, k) = D[z(i), j] + c(j) * k**alpha,    0 < alpha < 1,

so the marginal cost of the k-th stop must be positive but decreasing in k. The
previously configured zone_fixed_cost_matrix charges the matrix diagonal per
extra stop, which is linear in k and therefore rewards batching far less.
"""

import math

import pytest

from mvp_sim.core.driver import Driver
from mvp_sim.core.order import Order
from mvp_sim.cost_functions.travel_time import (
    AuxInfo,
    sublinear_intrazone,
    zone_fixed_cost_matrix,
)
from mvp_sim.experiments.scenario import BHH_CONSTANT, build_cost_params, compute_zone_areas


C_MATRIX = [[1.0, 4.0], [4.0, 1.0]]


def make_order(dest_zone: int, order_id: int = 1) -> Order:
    return Order(restaurant_id=1, destination_zone_id=dest_zone,
                 destination=(120.0, 30.0), arrival_time=0.0, prep_time=0.0,
                 deadline=None, profit=0.0, order_id=order_id)


def make_driver(zone: int = 1) -> Driver:
    return Driver(zone_id=zone, position=(120.0, 30.0), driver_id=1)


def ainfo(c_j: float = 2.0, alpha: float = 0.5) -> AuxInfo:
    return AuxInfo(C_MATRIX, None, None, None,
                   batch_alpha=alpha, zone_scale={1: c_j, 2: c_j})


class TestHandCalculatedCosts:
    def test_batch_of_one_matches_the_hand_calculation(self):
        """Driver in zone 1, batch destined for zone 2, c(j)=2, alpha=0.5.

            tau = D[1][2] + 2 * 1**0.5 = 4.0 + 2.0 = 6.0
        """
        costs = sublinear_intrazone.orders_cost(
            [make_order(2)], make_driver(zone=1), ainfo(c_j=2.0, alpha=0.5)
        )
        assert costs == [pytest.approx(6.0)]

    def test_batch_of_four_matches_the_hand_calculation(self):
        """Cumulative cost after k stops is D + c(j)*k**0.5 with D=4, c=2:

            k=1 -> 4 + 2*1 = 6.0     k=2 -> 4 + 2*1.41421 = 6.82843
            k=3 -> 4 + 2*1.73205 = 7.46410
            k=4 -> 4 + 2*2 = 8.0
        """
        orders = [make_order(2, order_id=i) for i in range(1, 5)]
        costs = sublinear_intrazone.orders_cost(orders, make_driver(zone=1), ainfo(2.0, 0.5))
        assert costs == pytest.approx([6.0, 6.828427, 7.464102, 8.0], abs=1e-5)

    def test_within_zone_batch_uses_the_matrix_diagonal(self):
        # Driver already in zone 1 delivering to zone 1: D[1][1] = 1.0.
        costs = sublinear_intrazone.orders_cost(
            [make_order(1)], make_driver(zone=1), ainfo(c_j=2.0, alpha=0.5)
        )
        assert costs == [pytest.approx(1.0 + 2.0)]

    def test_alpha_is_respected(self):
        orders = [make_order(2, order_id=i) for i in range(1, 4)]
        costs = sublinear_intrazone.orders_cost(orders, make_driver(1), ainfo(2.0, alpha=0.3))
        expected = [4.0 + 2.0 * (k ** 0.3) for k in (1, 2, 3)]
        assert costs == pytest.approx(expected)


class TestSublinearity:
    @staticmethod
    def marginals(k_max: int = 12, alpha: float = 0.5):
        orders = [make_order(2, order_id=i) for i in range(1, k_max + 1)]
        costs = sublinear_intrazone.orders_cost(orders, make_driver(1), ainfo(2.0, alpha))
        return [costs[i] - costs[i - 1] for i in range(1, len(costs))]

    def test_total_cost_is_increasing_in_batch_size(self):
        orders = [make_order(2, order_id=i) for i in range(1, 11)]
        costs = sublinear_intrazone.orders_cost(orders, make_driver(1), ainfo())
        assert all(b > a for a, b in zip(costs, costs[1:])), "adding a stop must cost something"

    def test_marginal_cost_is_positive(self):
        assert all(m > 0 for m in self.marginals())

    def test_marginal_cost_is_strictly_diminishing(self):
        marginals = self.marginals()
        assert all(b < a for a, b in zip(marginals, marginals[1:])), (
            "the k-th stop must cost less than the (k-1)-th"
        )

    @pytest.mark.parametrize("alpha", [0.2, 0.4, 0.5, 0.7, 0.9])
    def test_diminishing_for_every_admissible_alpha(self, alpha):
        marginals = self.marginals(alpha=alpha)
        assert all(m > 0 for m in marginals)
        assert all(b < a for a, b in zip(marginals, marginals[1:]))

    def test_per_order_cost_falls_with_batch_size(self):
        """The property that makes batching worthwhile: cost per delivered order."""
        per_order = []
        for k in range(1, 11):
            orders = [make_order(2, order_id=i) for i in range(1, k + 1)]
            total = sublinear_intrazone.orders_cost(orders, make_driver(1), ainfo())[-1]
            per_order.append(total / k)
        assert all(b < a for a, b in zip(per_order, per_order[1:]))

    def test_strictly_cheaper_than_the_linear_model_for_large_batches(self):
        orders = [make_order(2, order_id=i) for i in range(1, 11)]
        sub = sublinear_intrazone.orders_cost(orders, make_driver(1), ainfo())[-1]
        lin = zone_fixed_cost_matrix.orders_cost(
            orders, make_driver(1), AuxInfo(C_MATRIX, None, None, None)
        )[-1]
        assert sub < lin


class TestGuardsAndFallbacks:
    def test_empty_batch_costs_nothing(self):
        assert sublinear_intrazone.orders_cost([], make_driver(1), ainfo()) == []

    def test_mixed_destination_batch_is_rejected(self):
        orders = [make_order(1, order_id=1), make_order(2, order_id=2)]
        with pytest.raises(ValueError, match="zone-homogeneous"):
            sublinear_intrazone.orders_cost(orders, make_driver(1), ainfo())

    def test_missing_zone_scale_entry_is_reported(self):
        info = AuxInfo(C_MATRIX, None, None, None, batch_alpha=0.5, zone_scale={1: 2.0})
        with pytest.raises(KeyError):
            sublinear_intrazone.orders_cost([make_order(2)], make_driver(1), info)

    def test_legacy_bhh_parameterisation_still_reproduces_old_behaviour(self):
        """alpha*sqrt(k*A) must equal (alpha*sqrt(A)) * k**0.5."""
        legacy = AuxInfo(C_MATRIX, 0.7124, 9.0, None)
        orders = [make_order(2, order_id=i) for i in range(1, 6)]
        got = sublinear_intrazone.orders_cost(orders, make_driver(1), legacy)
        expected = [4.0 + 0.7124 * math.sqrt(k * 9.0) for k in range(1, 6)]
        assert got == pytest.approx(expected)


class TestCostParameterRecording:
    def test_canonical_beta_is_the_approved_two_dimensional_value(self):
        assert BHH_CONSTANT == pytest.approx(0.714)

    @staticmethod
    def zones_and_orders():
        zones = {"1": {"zone_id": 1, "zone_centriod": [120.0, 30.0], "restaurants": {}},
                 "2": {"zone_id": 2, "zone_centriod": [120.05, 30.05], "restaurants": {}}}
        orders = [
            {"order_id": 1, "restaurant_id": 1, "destination_zone_id": 1, "destination": [120.00, 30.00]},
            {"order_id": 2, "restaurant_id": 1, "destination_zone_id": 1, "destination": [120.01, 30.01]},
            {"order_id": 3, "restaurant_id": 1, "destination_zone_id": 2, "destination": [120.05, 30.05]},
            {"order_id": 4, "restaurant_id": 1, "destination_zone_id": 2, "destination": [120.06, 30.06]},
        ]
        return zones, orders

    def test_every_cost_parameter_is_recorded(self):
        zones, orders = self.zones_and_orders()
        params = build_cost_params(orders, zones, C_MATRIX,
                                   cost_function="sublinear_intrazone",
                                   speed_km_per_min=0.5)
        payload = params.to_json()
        for key in ("cost_function", "batch_alpha", "bhh_constant", "speed_km_per_min",
                    "zone_area_estimator", "zone_areas_km2", "zone_scale", "matrix_diagonal"):
            assert key in payload, f"{key} must be recorded with every run"
        assert payload["speed_km_per_min"] == 0.5
        assert payload["matrix_diagonal"] == 1.0

    def test_zone_scale_follows_from_area_and_speed(self):
        zones, orders = self.zones_and_orders()
        params = build_cost_params(orders, zones, C_MATRIX,
                                   cost_function="sublinear_intrazone",
                                   speed_km_per_min=2.0, bhh_constant=0.7124)
        for zid, area in params.zone_areas_km2.items():
            assert params.zone_scale[zid] == pytest.approx(0.7124 * math.sqrt(area) / 2.0)

    def test_every_zone_gets_a_positive_scale(self):
        """A zero c(j) would make batching free in that zone."""
        zones, orders = self.zones_and_orders()
        areas, _ = compute_zone_areas(orders, zones)
        assert set(areas) == {1, 2}
        assert all(a > 0 for a in areas.values())

    @pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.1])
    def test_batch_alpha_must_be_strictly_sublinear(self, alpha):
        zones, orders = self.zones_and_orders()
        with pytest.raises(ValueError, match="batch_alpha"):
            build_cost_params(orders, zones, C_MATRIX,
                              cost_function="sublinear_intrazone",
                              speed_km_per_min=1.0, batch_alpha=alpha)

    def test_zones_without_orders_still_get_an_area(self):
        zones, orders = self.zones_and_orders()
        zones["3"] = {"zone_id": 3, "zone_centriod": [120.1, 30.1], "restaurants": {}}
        areas, _ = compute_zone_areas(orders, zones)
        assert 3 in areas and areas[3] > 0


class TestPolicyAndSimulatorAgreeOnCost:
    """FEEDBACK-V2 item 2: "Confirm that CALS uses the same service-cost
    definition as the simulator."

    CALS scores candidate batches by tau(i,j,|Q_ij|)/|Q_ij|. If its notion of tau
    differs from what the simulator charges, the experiment measures the mismatch
    rather than the policy. CALS previously reimplemented the formula against
    legacy AuxInfo fields and, once those became unset, scored batching as free.
    """

    @staticmethod
    def env_stub(info):
        class _Env:
            ainfo = info
            travel_cost = sublinear_intrazone()
        return _Env()

    @pytest.mark.parametrize("k", [1, 2, 3, 5, 10, 25])
    def test_cals_tau_equals_the_simulator_charge(self, k):
        from mvp_sim.policies.general_policies import cals

        info = ainfo(c_j=2.0, alpha=0.5)
        env = self.env_stub(info)

        # What CALS scores with.
        scored = cals.CALS(w_a=2.0, w_c=5.0)._tau(1, 2, k, env)

        # What the simulator actually charges for that same batch.
        orders = [make_order(2, order_id=i) for i in range(1, k + 1)]
        charged = sublinear_intrazone.orders_cost(orders, make_driver(zone=1), info)[-1]

        assert scored == pytest.approx(charged)

    @pytest.mark.parametrize("k", [1, 4, 9])
    def test_agreement_holds_for_the_linear_model_too(self, k):
        from mvp_sim.policies.general_policies import cals

        info = AuxInfo(C_MATRIX, None, None, None)

        class _Env:
            ainfo = info
            travel_cost = zone_fixed_cost_matrix()

        scored = cals.CALS()._tau(1, 2, k, _Env())
        orders = [make_order(2, order_id=i) for i in range(1, k + 1)]
        charged = zone_fixed_cost_matrix.orders_cost(orders, make_driver(zone=1), info)[-1]
        assert scored == pytest.approx(charged)

    def test_cals_does_not_treat_batching_as_free(self):
        """The regression itself: tau must grow with k."""
        from mvp_sim.policies.general_policies import cals

        env = self.env_stub(ainfo(c_j=2.0, alpha=0.5))
        policy = cals.CALS()
        taus = [policy._tau(1, 2, k, env) for k in range(1, 8)]
        assert all(b > a for a, b in zip(taus, taus[1:])), (
            "CALS scored a larger batch as no more expensive than a smaller one"
        )

    def test_service_time_matches_orders_cost_for_every_prefix(self):
        """orders_cost[i] is the service time of the first i+1 stops."""
        info = ainfo(c_j=3.0, alpha=0.4)
        orders = [make_order(2, order_id=i) for i in range(1, 9)]
        costs = sublinear_intrazone.orders_cost(orders, make_driver(zone=1), info)
        for i, cumulative in enumerate(costs):
            assert cumulative == pytest.approx(
                sublinear_intrazone.service_time(1, 2, i + 1, info)
            )

    def test_unsupported_cost_functions_refuse_rather_than_guess(self):
        from mvp_sim.cost_functions.travel_time import euclidean

        with pytest.raises(NotImplementedError):
            euclidean.service_time(1, 2, 3, ainfo())
