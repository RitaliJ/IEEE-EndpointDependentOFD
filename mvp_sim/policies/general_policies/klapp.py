from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
from ..base import Policy

"""
Anticipatory Dispatch Waves Policy — Klapp, Erera & Toriello (2018).

Paper: Klapp, M. A., Erera, A. L., & Toriello, A. (2018).
       "The Dynamic Dispatch Waves Problem."
       Transportation Science, 52(6), 1302-1322.
       https://doi.org/10.1287/trsc.2017.0792

Paper summary:
    The paper models a SINGLE-VEHICLE depot problem. At each dispatch epoch
    (wave), if the vehicle is available, the operator makes one decision:
    dispatch a route serving some subset S of open orders, or wait (S = ∅).
    The decision is "global" only in the sense that it considers all open
    orders simultaneously for that one vehicle — there is no fleet coordination
    problem. Multi-vehicle extension is noted as future work but not formally
    developed in the paper.

    The paper assumes the arrival distribution is known and uses it inside a
    stochastic DP to compute the expected value of holding vs. dispatching.
    Because the exact DP is intractable, the paper's heuristic substitutes
    expected future arrivals (deterministic approximation) in place of the
    stochastic draw, then solves the resulting routing problem.

Core idea (this implementation):
    Rather than dispatching the moment an order is ready, the policy fires a
    periodic "wave" every wave_interval time units. At each wave, for every
    destination zone with ready orders, it asks:

        Should I dispatch this zone's batch now, or hold and wait for a
        better batch in the next wave?

    The hold/dispatch decision mirrors the paper's cost-benefit comparison:

        HOLD if  E[batching_savings] > flow_cost_of_waiting
        i.e.     min(expected_companions, 1) * route_cost > n * wave_interval

    where:
        expected_companions = estimated_zone_rate(zone) * wave_interval
        route_cost          = max delivery travel cost for the current batch
        n                   = number of orders currently ready in this zone

    Urgency and batch-size effects emerge naturally from the inequality:
    large n or small route_cost tips toward dispatching; high expected arrival
    rate or expensive route tips toward holding.

    Among zones decided to dispatch, the most urgent (oldest waiting order) is
    selected first.

Parameters:
    wave_interval (float) : Time between waves (delta t). Larger values batch
                            more aggressively at the cost of higher flow time.

Differences from the paper:
    1. Multi-vehicle. The paper is single-vehicle; multi-vehicle is not
       formally developed. This implementation runs one independent wave per
       driver. Each driver selects its nearest restaurant and best zone without
       coordinating with other drivers at wave time. This is an unspecified
       extension — the paper offers no guidance on how to handle it.

    2. No distributional knowledge. The paper assumes the arrival distribution
       is known and plugs E[future arrivals] directly into the DP. This
       implementation estimates the per-zone arrival rate online from observed
       OrderArriveEvents, keeping it on equal informational footing with EAF,
       ERF, and NearestNeighbor.

    3. Driver-triggered waves. The paper fires waves on a fixed external clock
       only. This implementation also runs a wave immediately when a driver
       becomes idle (DriverReadyEvent, DriverRepositionArriveEvent), inserting
       an unscheduled check so idle drivers do not wait a full wave_interval
       before looking for work.

    4. Per-zone hold/dispatch. The paper selects a subset S of all open orders
       to dispatch in one route. This implementation makes an independent
       hold/dispatch decision per destination zone and dispatches at most one
       zone per wave per driver, reflecting the simulator's single-destination
       dispatch model.
"""


class KlappWaves(Policy):

    def __init__(self, wave_interval: float):
        self.wave_interval = wave_interval

        self._arrivals_seen: int = 0
        self._first_arrival_time: float | None = None
        self._zone_arrival_counts: dict[int, int] = {}

        # driver_ids that already have a PolicyWaitEvent queued
        self._wave_pending: set[int] = set()

    # ------------------------------------------------------------------
    # Online rate estimation
    # ------------------------------------------------------------------

    def _record_arrival(self, order: Order, time: float) -> None:
        if self._first_arrival_time is None:
            self._first_arrival_time = time
        self._arrivals_seen += 1
        zid = order.destination_zone_id
        self._zone_arrival_counts[zid] = self._zone_arrival_counts.get(zid, 0) + 1

    def _estimated_zone_rate(self, zone_id: int, current_time: float) -> float:
        """Arrivals per unit time to zone_id, estimated from observations so far."""
        if self._first_arrival_time is None or self._arrivals_seen == 0:
            return 0.0
        elapsed = current_time - self._first_arrival_time
        if elapsed <= 0:
            return 0.0
        overall_rate = self._arrivals_seen / elapsed
        zone_fraction = self._zone_arrival_counts.get(zone_id, 0) / self._arrivals_seen
        return overall_rate * zone_fraction

    # ------------------------------------------------------------------
    # Hold / dispatch decision
    # ------------------------------------------------------------------

    def _should_dispatch_now(self, orders: list[Order], zone_id: int, current_time: float,
                             driver: Driver, environment: Environment) -> bool:
        expected_companions = self._estimated_zone_rate(zone_id, current_time) * self.wave_interval
        route_cost = max(environment.compute_orders_travel_cost(orders, driver))
        expected_savings = min(expected_companions, 1.0) * route_cost
        flow_cost_of_waiting = len(orders) * self.wave_interval
        return expected_savings < flow_cost_of_waiting

    # ------------------------------------------------------------------
    # Restaurant helpers (same save/restore pattern as general EAF)
    # ------------------------------------------------------------------

    def _find_closest_waiting_rest(self, driver: Driver, env: Environment) -> Restaurant | None:
        zone = env.zones[driver.curr_zone_id]
        saved_dest_zone = driver.dest_zone_id
        saved_dest_pt   = driver.dest_pt

        best_rest: Restaurant | None = None
        best_cost = float('inf')

        for rest in zone.restaurants.values():
            if not any(q for q in rest.ready_subqueues.values()):
                continue
            driver.dest_zone_id = rest.zone_id
            driver.dest_pt      = rest.position
            cost = env.travel_cost.driver_cost(driver, env.ainfo)
            if best_rest is None or cost < best_cost or (cost == best_cost and rest.restaurant_id < best_rest.restaurant_id):
                best_cost = cost
                best_rest = rest

        driver.dest_zone_id = saved_dest_zone
        driver.dest_pt      = saved_dest_pt
        return best_rest

    def _find_global_waiting_rest(self, driver: Driver, env: Environment) -> Restaurant | None:
        saved_dest_zone = driver.dest_zone_id
        saved_dest_pt   = driver.dest_pt

        best_rest: Restaurant | None = None
        best_cost = float('inf')

        for zone in env.zones.values():
            for rest in zone.restaurants.values():
                if not any(q for q in rest.ready_subqueues.values()):
                    continue
                driver.dest_zone_id = rest.zone_id
                driver.dest_pt      = rest.position
                cost = env.travel_cost.driver_cost(driver, env.ainfo)
                if best_rest is None or cost < best_cost or (cost == best_cost and rest.restaurant_id < best_rest.restaurant_id):
                    best_cost = cost
                    best_rest = rest

        driver.dest_zone_id = saved_dest_zone
        driver.dest_pt      = saved_dest_pt
        return best_rest

    # ------------------------------------------------------------------
    # Wave scheduling and execution
    # ------------------------------------------------------------------

    def _schedule_wave(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler) -> None:
        """Push a PolicyWaitEvent for driver at time + wave_interval, if not already pending."""
        if driver.driver_id in self._wave_pending:
            return
        next_time = time + self.wave_interval
        if next_time <= environment.horizon:
            event_handler.push_event(PolicyWaitEvent(time=next_time, driver=driver))
            self._wave_pending.add(driver.driver_id)

    def _run_wave(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler) -> None:
        """Execute one dispatch wave for driver at current time."""
        self._wave_pending.discard(driver.driver_id)

        if not driver.is_idle():
            return

        rest = self._find_closest_waiting_rest(driver, environment)
        if rest is None:
            rest = self._find_global_waiting_rest(driver, environment)
        if rest is None:
            self._schedule_wave(time, driver, environment, event_handler)
            return

        by_zone: dict[int, list[Order]] = {
            zone_id: [environment.orders[oid] for oid in order_ids]
            for zone_id, order_ids in rest.ready_subqueues.items()
            if order_ids
        }

        dispatch_zones = {
            zid: orders 
            for zid, orders in by_zone.items()
            if self._should_dispatch_now(orders, zid, time, driver, environment)
        }

        if not dispatch_zones:
            self._schedule_wave(time, driver, environment, event_handler)
            return

        best_zone = max(
            dispatch_zones,
            key=lambda zid: max(time - o.arrival_time for o in dispatch_zones[zid])
        )
        batch = dispatch_zones[best_zone]
        event_handler.handle_event(OrdersAssignEvent(time, batch, rest, driver))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_order_arrive(self, event: OrderArriveEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._record_arrival(event.order, event.time)

    def _handle_order_ready(self, event: OrderReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        idles = environment.idle_drivers()
        if not idles:
            earliest = min(environment.drivers.values(), key=lambda d: d.next_available_time)
            self._schedule_wave(earliest.next_available_time, earliest, environment, event_handler)
            return
        for driver in idles:
            self._schedule_wave(event.time, driver, environment, event_handler)

    def _handle_policy_wait(self, event: PolicyWaitEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._run_wave(event.time, event.driver, environment, event_handler)

    def _handle_driver_ready(self, event: DriverReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._run_wave(event.time, event.driver, environment, event_handler)

    def _handle_driver_reposition_arrive(self, event: DriverRepositionArriveEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._run_wave(event.time, event.driver, environment, event_handler)

    def tick(self, event: Event, environment: Environment, event_handler: EventHandler) -> None:
        if issubclass(type(event), Event):
            if isinstance(event, OrderArriveEvent):
                self._handle_order_arrive(event, environment, event_handler)
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
        else:
            raise TypeError("Non-event type")
