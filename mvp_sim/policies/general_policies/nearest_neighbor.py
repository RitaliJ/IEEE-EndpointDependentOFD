from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
import random
from ..base import Policy

MAX_POLICY_WAIT = 5

class NearestNeighbor(Policy):

    def __init__(self, seed: int = 0, max_policy_wait: int = MAX_POLICY_WAIT):
        # See ERF.__init__ -- retry jitter is drawn from an explicitly seeded
        # instance stream so the experiment seed fully determines the run.
        self.seed = seed
        self.max_policy_wait = max_policy_wait
        self._rng = random.Random(seed)

    def _nn_algo(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler, restaurant: Restaurant) -> None:
        assert driver.is_idle(), "trying to assign a driver that is busy"

        queue: list[Order] = []
        for order_ids in restaurant.ready_subqueues.values():
            for oid in order_ids:
                queue.append(environment.orders[oid])
        assert len(queue) > 0

        # find the nearest destination zone by computing driver travel cost to each zone
        saved_dest_zone = driver.dest_zone_id
        saved_dest_pt   = driver.dest_pt

        best_dest_zone: int | None = None
        best_cost = float('inf')

        for dest_zone_id, order_ids in restaurant.ready_subqueues.items():
            if not order_ids:
                continue
            rep_order = environment.orders[order_ids[0]]
            driver.dest_zone_id = dest_zone_id
            driver.dest_pt      = rep_order.destination
            cost = environment.travel_cost.driver_cost(driver, environment.ainfo)
            if best_dest_zone is None or cost < best_cost or (cost == best_cost and dest_zone_id < best_dest_zone):
                best_cost      = cost
                best_dest_zone = dest_zone_id

        driver.dest_zone_id = saved_dest_zone
        driver.dest_pt      = saved_dest_pt

        batch = [o for o in queue if o.destination_zone_id == best_dest_zone]

        assign_event = OrdersAssignEvent(time, batch, restaurant, driver)
        event_handler.handle_event(assign_event)

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

    def _begin_wait(self, env: Environment, event_handler: EventHandler, time: float, driver: Driver) -> None:
        val = self._rng.randint(1, self.max_policy_wait)
        new_time = time + val
        if new_time <= env.horizon:
            event_handler.push_event(PolicyWaitEvent(time=new_time, driver=driver))

    def _assign_drivers(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler) -> None:
        if not driver.is_idle():
            return
        res = self._find_closest_waiting_rest(driver, environment)
        if res is not None:
            self._nn_algo(time=time, driver=driver, environment=environment,
                          event_handler=event_handler, restaurant=res)
        else:
            res = self._find_global_waiting_rest(driver, environment)
            if res is not None and res.zone_id != driver.curr_zone_id:
                event_handler.handle_event(DriverRepositionAssignEvent(
                    time,
                    driver,
                    environment.zones[res.zone_id],
                    res.position,
                ))
            elif res is not None:
                self._nn_algo(time=time, driver=driver, environment=environment,
                          event_handler=event_handler, restaurant=res)
            else:
                earliest = min(environment.drivers.values(), key=lambda d: d.next_available_time)
                self._begin_wait(env=environment, event_handler=event_handler, time=earliest.next_available_time, driver=driver)

    def _assign_drivers_order_ready(self, event: OrderReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        idles = environment.idle_drivers()

        if not idles:
            earliest = min(environment.drivers.values(), key=lambda d: d.next_available_time)
            self._begin_wait(env=environment, event_handler=event_handler, time=earliest.next_available_time, driver=earliest)
            return

        triggering_rest    = event.restaurant
        triggering_zone_id = triggering_rest.zone_id

        in_zone  = [d for d in idles if d.curr_zone_id == triggering_zone_id]
        out_zone = [d for d in idles if d.curr_zone_id != triggering_zone_id]

        if in_zone:
            for driver in in_zone:
                self._assign_drivers(event.time, driver, environment, event_handler)
            for driver in out_zone:
                self._assign_drivers(event.time, driver, environment, event_handler)
        else:
            saved = {d.driver_id: (d.dest_zone_id, d.dest_pt) for d in out_zone}
            best_driver: Driver | None = None
            best_cost = float('inf')

            for driver in out_zone:
                driver.dest_zone_id = triggering_zone_id
                driver.dest_pt      = triggering_rest.position
                cost = environment.travel_cost.driver_cost(driver, environment.ainfo)
                if best_driver is None or cost < best_cost or (cost == best_cost and driver.driver_id < best_driver.driver_id):
                    best_cost   = cost
                    best_driver = driver

            for driver in out_zone:
                driver.dest_zone_id, driver.dest_pt = saved[driver.driver_id]

            if best_driver is not None:
                event_handler.handle_event(DriverRepositionAssignEvent(
                    event.time,
                    best_driver,
                    environment.zones[triggering_zone_id],
                    triggering_rest.position,
                ))

            for driver in out_zone:
                if driver is not best_driver:
                    self._assign_drivers(event.time, driver, environment, event_handler)

    def _handle_order_delivered(self, event: OrderDeliveredEvent, environment: Environment, event_handler: EventHandler) -> None:
        return

    def _handle_order_ready(self, event: OrderReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers_order_ready(event, environment, event_handler)

    def _handle_driver_reposition_arrive(self, event: DriverRepositionArriveEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers(event.time, event.driver, environment, event_handler)

    def _handle_driver_ready(self, event: DriverReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers(event.time, event.driver, environment, event_handler)

    def _handle_policy_wait(self, event: PolicyWaitEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers(event.time, event.driver, environment, event_handler)

    def tick(self, event: Event, environment: Environment, event_handler: EventHandler) -> None:
        if issubclass(type(event), Event):
            if isinstance(event, OrderArriveEvent):
                return
            elif isinstance(event, OrderReadyEvent):
                self._handle_order_ready(event, environment, event_handler)
            elif isinstance(event, OrdersAssignEvent):
                return
            elif isinstance(event, OrderDeliveredEvent):
                self._handle_order_delivered(event, environment, event_handler)
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
