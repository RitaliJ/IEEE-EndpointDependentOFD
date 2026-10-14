"""
Coverage-Aware Local Scoring (CALS) Dispatch Policy
=====================================================

When a driver goes idle in zone A, score every eligible subqueue (i, j)
(restaurant i, destination zone j with >= 1 prepared order) with:

    C(i, j) = travel + deliver_per_order - w_a * urgency + w_c * coverage

All terms are in seconds. Assign to argmin C. Details in
CALS_policy_implementation_plan.md.

Parameters
----------
w_a : float
    Urgency weight. w_a=0 ignores order age; w_a>1 is tail-averse.
w_c : float
    Coverage weight. w_c=0 gives pure local greedy; large w_c enforces
    spatial spreading.
"""

from __future__ import annotations

import math

from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
from ..base import Policy

_INF = float("inf")


class CALS(Policy):

    def __init__(self, w_a: float = 0.0, w_c: float = 0.0):
        self.w_a = w_a
        self.w_c = w_c
        # zone_id -> number of drivers whose covered zone is that zone
        self._n: dict[int, int] = {}
        # driver_id -> current covered zone_id
        self._covered: dict[int, int] = {}
        # driver_ids with an outstanding PolicyWaitEvent (at most one per driver)
        self._pending_wait: set[int] = set()

    # ------------------------------------------------------------------
    # Coverage counter helpers
    # ------------------------------------------------------------------

    def _cov_init(self, driver: Driver, zone_id: int) -> None:
        """Transition a driver to covered-zone = zone_id (called on idle arrival)."""
        old = self._covered.get(driver.driver_id)
        if old is not None:
            new_val = self._n.get(old, 0) - 1
            if new_val > 0:
                self._n[old] = new_val
            else:
                self._n.pop(old, None)
        self._n[zone_id] = self._n.get(zone_id, 0) + 1
        self._covered[driver.driver_id] = zone_id

    def _cov_assign(self, driver: Driver, dest_zone_id: int) -> None:
        """Transition covered zone from driver's current covered zone to dest_zone_id."""
        old = self._covered.get(driver.driver_id, driver.curr_zone_id)
        new_val = self._n.get(old, 0) - 1
        if new_val > 0:
            self._n[old] = new_val
        else:
            self._n.pop(old, None)
        self._n[dest_zone_id] = self._n.get(dest_zone_id, 0) + 1
        self._covered[driver.driver_id] = dest_zone_id

    # ------------------------------------------------------------------
    # Travel / batch time helpers
    # ------------------------------------------------------------------

    def _d(self, from_zone: int, to_zone: int, env: Environment) -> float:
        """Interzone travel time D[from_zone, to_zone] via c_matrix (1-indexed)."""
        c_matrix = env.ainfo.c_matrix
        assert c_matrix is not None
        return c_matrix[from_zone - 1][to_zone - 1]

    def _tau(self, rest_zone: int, dest_zone: int, k: int, env: Environment) -> float:
        """Batch service time, delegated to the simulator's own cost function.

        CALS used to reimplement this against the legacy ainfo.alpha/zone_area
        fields. Once the sublinear model moved to batch_alpha/zone_scale those were
        None, so the local formula silently returned transit only -- CALS scored
        batching as free while the simulator charged c(j)*k**alpha for it. Scoring
        against a different cost than the one being measured makes the comparison
        meaningless, so the definition now lives in exactly one place.
        """
        return env.travel_cost.service_time(rest_zone, dest_zone, k, env.ainfo)

    # ------------------------------------------------------------------
    # Core CALS assignment
    # ------------------------------------------------------------------

    def _assign_idle_driver(
        self,
        time: float,
        driver: Driver,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        if not driver.is_idle():
            return

        A = self._covered.get(driver.driver_id, driver.curr_zone_id)
        n_A = self._n.get(A, 0)

        best_cost = _INF
        best_rest_id: int | None = None
        best_j: int | None = None
        best_k = 0
        best_travel = _INF

        for rest in env.restaurants.values():
            for j, order_ids in rest.ready_subqueues.items():
                if not order_ids:
                    continue
                k = len(order_ids)
                orders = [env.orders[oid] for oid in order_ids]

                a_ij = time - min(o.arrival_time for o in orders)
                tau = self._tau(rest.zone_id, j, k, env)
                travel = self._d(A, rest.zone_id, env)
                deliver_per_order = tau / k
                urgency = a_ij

                n_j = self._n.get(j, 0)
                leaving_penalty = tau if n_A == 1 else 0.0
                relieving_bonus = tau if n_j == 0 else 0.0
                coverage = leaving_penalty - relieving_bonus

                cost = (travel + deliver_per_order
                        - self.w_a * urgency
                        + self.w_c * coverage)

                # deterministic tie-breaking: lower cost > larger k > smaller travel > lower ids
                if cost < best_cost - 1e-9:
                    better = True
                elif abs(cost - best_cost) <= 1e-9:
                    if k != best_k:
                        better = k > best_k
                    elif travel != best_travel:
                        better = travel < best_travel
                    else:
                        better = (rest.restaurant_id, j) < (best_rest_id, best_j)
                else:
                    better = False

                if better:
                    best_cost = cost
                    best_rest_id = rest.restaurant_id
                    best_j = j
                    best_k = k
                    best_travel = travel

        if best_rest_id is None:
            # no eligible subqueue; wake up when the next driver finishes
            busy = [d for d in env.drivers.values() if not d.is_idle()]
            if busy:
                next_t = min(d.next_available_time for d in busy)
                if next_t > time and next_t <= env.horizon:
                    if driver.driver_id not in self._pending_wait:
                        event_handler.push_event(PolicyWaitEvent(time=next_t, driver=driver))
                        self._pending_wait.add(driver.driver_id)
            return

        rest = env.restaurants[best_rest_id]
        orders = [env.orders[oid] for oid in rest.ready_subqueues[best_j]]

        # update coverage immediately so subsequent drivers scored this tick see accurate n[]
        self._cov_assign(driver, best_j)
        self._pending_wait.discard(driver.driver_id)

        event_handler.handle_event(OrdersAssignEvent(time, orders, rest, driver))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_driver_ready(
        self, event: DriverReadyEvent, env: Environment, eh: EventHandler
    ) -> None:
        self._cov_init(event.driver, event.zone.zone_id)
        self._assign_idle_driver(event.time, event.driver, env, eh)

    def _handle_driver_reposition_arrive(
        self, event: DriverRepositionArriveEvent, env: Environment, eh: EventHandler
    ) -> None:
        self._cov_init(event.driver, event.zone.zone_id)
        self._assign_idle_driver(event.time, event.driver, env, eh)

    def _handle_order_ready(
        self, event: OrderReadyEvent, env: Environment, eh: EventHandler
    ) -> None:
        for driver in list(env.idle_drivers()):
            self._assign_idle_driver(event.time, driver, env, eh)

    def _handle_policy_wait(
        self, event: PolicyWaitEvent, env: Environment, eh: EventHandler
    ) -> None:
        # Discard before rescoring so _assign_idle_driver can re-register if needed
        self._pending_wait.discard(event.driver.driver_id)
        self._assign_idle_driver(event.time, event.driver, env, eh)

    # ------------------------------------------------------------------
    # Policy interface
    # ------------------------------------------------------------------

    def tick(self, event: Event, environment: Environment, event_handler: EventHandler) -> None:
        if not issubclass(type(event), Event):
            raise TypeError("Non-event type")
        if isinstance(event, OrderArriveEvent):
            return
        elif isinstance(event, OrderReadyEvent):
            self._handle_order_ready(event, environment, event_handler)
        elif isinstance(event, OrdersAssignEvent):
            return
        elif isinstance(event, OrderDeliveredEvent):
            return
        elif isinstance(event, DriverArriveEvent):
            return
        elif isinstance(event, DriverReadyEvent):
            self._handle_driver_ready(event, environment, event_handler)
        elif isinstance(event, PolicyWaitEvent):
            self._handle_policy_wait(event, environment, event_handler)
        elif isinstance(event, DriverRepositionAssignEvent):
            return
        elif isinstance(event, DriverRepositionArriveEvent):
            self._handle_driver_reposition_arrive(event, environment, event_handler)
        else:
            raise TypeError("Unhandled event")
