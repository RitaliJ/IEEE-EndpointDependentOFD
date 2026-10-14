"""
Spread-and-Navigate (SN) Policy
================================

Assignment
----------
On each OrderReadyEvent, drivers are ranked by travel cost from their *landing
point* to the restaurant that just became ready.  The landing point of an idle
driver is its current position; for a busy driver it is the destination of its
current task (the zone it will occupy when it next becomes free).

Let A = the globally closest driver (idle or busy).
Let B = the closest *idle* driver.

Case 1 — A is idle:
    Assign A to the restaurant via batch_decision.

Case 2 — A is busy, and A's remaining time < B's travel time to the restaurant:
    A will arrive before B could; reserve A for this restaurant so no other
    OrderReadyEvent redirects it.  When A finishes its current task, it goes
    directly to the reserved restaurant.

Case 3 — A is busy, and A's remaining time >= B's travel time to the restaurant:
    Dispatch B to the restaurant immediately.  A is left to find work naturally
    when it becomes free.

Chain repositioning (Cases 1–3)
    After the primary assignment is decided, the remaining idle drivers are
    repositioned in a spreading chain to fill the positional gap left by each
    departing driver:

        A  →  restaurant          (or reserved for it)
        B  →  A's vacated zone
        C  →  B's vacated zone
        D  →  C's vacated zone
        …

    In Case 2 (A reserved, busy) the chain anchor is A's *landing zone* — the
    zone A is heading toward and will soon vacate.  In Cases 1 and 3 the anchor
    is the zone the dispatched driver physically departs from.

    The chain stops when:
      (a) The next driver's zone already contains a restaurant with ready orders
          (pulling it away would abandon available work), or
      (b) The next driver is already in the hole zone (no meaningful move).

    Only idle drivers participate; busy drivers cannot be repositioned.

Batch decision
--------------
Once a driver arrives at a restaurant, it selects the delivery zone with the
highest priority score:

    score = oldest_wait + time_since_last_arrival - driver_cost * adjuster

Where:
    oldest_wait          = time since the oldest ready order in the zone arrived
    time_since_last_arrival = time since the most recent ready order in the zone
                              arrived  (rewards neglected zones)
    driver_cost          = travel cost from the driver's current position to a
                           representative order in the zone  (penalises far zones)
    adjuster             = tunable weight on driver_cost (default 1.0)

The formula naturally delays dispatching to distant zones: a far zone only wins
if its orders are old enough that urgency outweighs the travel cost.

Parameters
----------
adjuster : float
    Weight applied to driver_cost in the batch priority score.  Lower values
    favour far zones more aggressively.  Default is 1.0.
"""

from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
from mvp_sim.core.restaurant import Restaurant
from ..base import Policy


class SN(Policy):

    def __init__(self, adjuster: float = 1.0):
        self.adjuster = adjuster
        # driver_id -> restaurant_id: driver is reserved for that restaurant
        self._reserved: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Landing-point helpers
    # ------------------------------------------------------------------

    def _landing(self, driver: Driver) -> tuple[int, tuple[float, float]]:
        """Return (zone_id, pt) where driver will be when it next becomes idle."""
        if driver.is_idle() or driver.dest_zone_id is None:
            return (driver.curr_zone_id, driver.curr_pt)
        assert driver.dest_pt is not None
        return (driver.dest_zone_id, driver.dest_pt)

    def _cost_from_landing(
        self,
        driver: Driver,
        dest_zone_id: int,
        dest_pt: tuple[float, float],
        env: Environment,
    ) -> float:
        """Travel cost from driver's landing point to (dest_zone_id, dest_pt)."""
        s_curr_zone, s_curr_pt = driver.curr_zone_id, driver.curr_pt
        s_dest_zone, s_dest_pt = driver.dest_zone_id, driver.dest_pt

        lz, lp = self._landing(driver)
        driver.curr_zone_id = lz
        driver.curr_pt      = lp
        driver.dest_zone_id = dest_zone_id
        driver.dest_pt      = dest_pt
        cost = env.travel_cost.driver_cost(driver, env.ainfo)

        driver.curr_zone_id = s_curr_zone
        driver.curr_pt      = s_curr_pt
        driver.dest_zone_id = s_dest_zone
        driver.dest_pt      = s_dest_pt
        return cost

    def _rank_by_landing_cost(
        self,
        drivers: list[Driver],
        dest_zone_id: int,
        dest_pt: tuple[float, float],
        env: Environment,
    ) -> list[tuple[float, Driver]]:
        """Sort drivers by landing-point travel cost to destination, ascending."""
        ranked = [
            (self._cost_from_landing(d, dest_zone_id, dest_pt, env), d.driver_id, d)
            for d in drivers
        ]
        ranked.sort()
        return [(cost, d) for cost, _, d in ranked]

    # ------------------------------------------------------------------
    # Zone utilities
    # ------------------------------------------------------------------

    def _zone_has_ready_orders(self, zone_id: int, env: Environment) -> bool:
        return any(
            any(q for q in rest.ready_subqueues.values())
            for rest in env.zones[zone_id].restaurants.values()
        )

    # ------------------------------------------------------------------
    # Chain repositioning
    # ------------------------------------------------------------------

    def _chain_reposition(
        self,
        time: float,
        idle_chain: list[Driver],
        hole_zone_id: int,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        """Reposition idle drivers one by one into the spreading chain.

        Each driver fills the zone vacated by the driver ahead of it.
        Stops when a driver already has local work, or is already in the hole.
        """
        for driver in idle_chain:
            if self._zone_has_ready_orders(driver.curr_zone_id, env):
                break
            if driver.curr_zone_id == hole_zone_id:
                break
            new_hole_zone_id = driver.curr_zone_id
            event_handler.handle_event(DriverRepositionAssignEvent(
                time,
                driver,
                env.zones[hole_zone_id],
                env.zones[hole_zone_id].zone_centriod,
            ))
            hole_zone_id = new_hole_zone_id

    # ------------------------------------------------------------------
    # Restaurant search
    # ------------------------------------------------------------------

    def _find_waiting_rest(self, driver: Driver, env: Environment) -> Restaurant | None:
        """Return the nearest restaurant with ready orders (zone-local first)."""
        saved_dest_zone = driver.dest_zone_id
        saved_dest_pt   = driver.dest_pt

        best_rest: Restaurant | None = None
        best_cost = float('inf')

        in_zone = list(env.zones[driver.curr_zone_id].restaurants.values())
        candidates = (
            in_zone
            if any(any(q for q in r.ready_subqueues.values()) for r in in_zone)
            else [r for z in env.zones.values() for r in z.restaurants.values()]
        )

        for rest in candidates:
            if not any(q for q in rest.ready_subqueues.values()):
                continue
            driver.dest_zone_id = rest.zone_id
            driver.dest_pt      = rest.position
            cost = env.travel_cost.driver_cost(driver, env.ainfo)
            if cost < best_cost or (
                cost == best_cost
                and best_rest is not None
                and rest.restaurant_id < best_rest.restaurant_id
            ):
                best_cost = cost
                best_rest = rest

        driver.dest_zone_id = saved_dest_zone
        driver.dest_pt      = saved_dest_pt
        return best_rest

    # ------------------------------------------------------------------
    # Batch decision
    # ------------------------------------------------------------------

    def _batch_decision(
        self,
        time: float,
        driver: Driver,
        restaurant: Restaurant,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        """Select the highest-priority delivery zone and assign that batch."""
        best_zone: int | None = None
        best_score = float('-inf')

        saved_dest_zone = driver.dest_zone_id
        saved_dest_pt   = driver.dest_pt

        for zone_id, order_ids in restaurant.ready_subqueues.items():
            if not order_ids:
                continue
            orders = [env.orders[oid] for oid in order_ids]

            oldest_wait             = max(time - o.arrival_time for o in orders)
            time_since_last_arrival = time - max(o.arrival_time for o in orders)

            driver.dest_zone_id = zone_id
            driver.dest_pt      = orders[0].destination
            driver_cost = env.travel_cost.driver_cost(driver, env.ainfo)

            score = oldest_wait + time_since_last_arrival - driver_cost * self.adjuster

            if best_zone is None or score > best_score or (
                score == best_score and zone_id < best_zone
            ):
                best_score = score
                best_zone  = zone_id

        driver.dest_zone_id = saved_dest_zone
        driver.dest_pt      = saved_dest_pt

        if best_zone is None:
            return

        batch = [env.orders[oid] for oid in restaurant.ready_subqueues[best_zone]]
        event_handler.handle_event(OrdersAssignEvent(time, batch, restaurant, driver))

    # ------------------------------------------------------------------
    # General idle-driver assignment
    # ------------------------------------------------------------------

    def _assign_driver(
        self,
        time: float,
        driver: Driver,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        """Find work for an idle driver, or schedule a wait if none exists."""
        if not driver.is_idle():
            return
        rest = self._find_waiting_rest(driver, env)
        if rest is not None:
            self._batch_decision(time, driver, rest, env, event_handler)
        else:
            earliest = min(env.drivers.values(), key=lambda d: d.next_available_time)
            next_t = earliest.next_available_time
            if next_t > time and next_t <= env.horizon:
                event_handler.push_event(PolicyWaitEvent(time=next_t, driver=driver))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_order_ready(
        self,
        event: OrderReadyEvent,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        rest = event.restaurant
        if not any(rest.ready_subqueues.values()):
            return

        all_drivers  = list(env.drivers.values())
        idle_drivers = list(env.idle_drivers())

        if not all_drivers:
            return

        ranked_all  = self._rank_by_landing_cost(all_drivers, rest.zone_id, rest.position, env)
        driver_a    = ranked_all[0][1]

        ranked_idle = self._rank_by_landing_cost(idle_drivers, rest.zone_id, rest.position, env)

        if driver_a.is_idle():
            # Case 1: closest driver is idle — assign directly.
            self._batch_decision(event.time, driver_a, rest, env, event_handler)
            chain = [d for _, d in ranked_idle if d.driver_id != driver_a.driver_id]
            self._chain_reposition(event.time, chain, driver_a.curr_zone_id, env, event_handler)
            return

        # A is busy.
        if not ranked_idle:
            event_handler.push_event(PolicyWaitEvent(time=driver_a.next_available_time, driver=driver_a))
            return

        driver_b, cost_b = ranked_idle[0][1], ranked_idle[0][0]
        a_remaining = (driver_a.next_available_time - event.time) + self._cost_from_landing(driver_a, rest.zone_id, rest.position, env)

        if a_remaining < cost_b:
            # Case 2: A's total ETA (remaining busy time + drive from landing to restaurant)
            # beats B's travel time — reserve A.
            self._reserved[driver_a.driver_id] = rest.restaurant_id
            chain = [d for _, d in ranked_idle]
            anchor_zone = self._landing(driver_a)[0]
            self._chain_reposition(event.time, chain, anchor_zone, env, event_handler)
        else:
            # Case 3: B is faster — dispatch B.
            b_depart_zone = driver_b.curr_zone_id
            self._batch_decision(event.time, driver_b, rest, env, event_handler)
            chain = [d for _, d in ranked_idle if d.driver_id != driver_b.driver_id]
            self._chain_reposition(event.time, chain, b_depart_zone, env, event_handler)

    def _handle_driver_reposition_arrive(
        self,
        event: DriverRepositionArriveEvent,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        driver = event.driver
        if driver.driver_id in self._reserved:
            rest_id = self._reserved.pop(driver.driver_id)
            rest = env.restaurants[rest_id]
            if any(rest.ready_subqueues.values()):
                self._batch_decision(event.time, driver, rest, env, event_handler)
                return
        self._assign_driver(event.time, driver, env, event_handler)

    def _handle_driver_ready(
        self,
        event: DriverReadyEvent,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        self._assign_driver(event.time, event.driver, env, event_handler)

    def _handle_policy_wait(
        self,
        event: PolicyWaitEvent,
        env: Environment,
        event_handler: EventHandler,
    ) -> None:
        self._assign_driver(event.time, event.driver, env, event_handler)

    def tick(self, event: Event, environment: Environment, event_handler: EventHandler) -> None:
        if issubclass(type(event), Event):
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
        else:
            raise TypeError("Non-event type")
