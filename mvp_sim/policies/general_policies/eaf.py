from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
import random
from ..base import Policy

# POLICY_WAIT_DISTRIBUTION_HANDLER; the only case that is handled right now is uniform
MAX_POLICY_WAIT = 5

class EAF(Policy):

    def __init__(self, seed: int = 0, max_policy_wait: int = MAX_POLICY_WAIT):
        # See ERF.__init__ -- retry jitter is drawn from an explicitly seeded
        # instance stream so the experiment seed fully determines the run.
        self.seed = seed
        self.max_policy_wait = max_policy_wait
        self._rng = random.Random(seed)

    def _anticipation_time(self, order: Order, environment: Environment, driver: Driver) -> float:
        r = order.arrival_time
        d = environment.compute_orders_travel_cost([order], driver)
        return r + sum(d)
    
    def _eaf_algo(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler, restaurant: Restaurant) -> None:        
        assert driver.is_idle(), "trying to assign a driver that is busy"
        # collect all ready orders across all destination zones
        queue: list[Order] = []
        for order_ids in restaurant.ready_subqueues.values():
            for oid in order_ids:
                queue.append(environment.orders[oid])
        assert len(queue) > 0

        earliest_anticipation = self._anticipation_time(queue[0], environment, driver)
        earliest_order = queue[0]
        for i in range(1, len(queue)):
            order = queue[i]
            anticipation = self._anticipation_time(order, environment, driver)
            if (anticipation < earliest_anticipation):
                earliest_anticipation = anticipation
                earliest_order = queue[i]
        
        # batch all orders going to earliest anticipation destination zone
        batch = []
        for order in queue:
            if order.destination_zone_id == earliest_order.destination_zone_id:
                batch.append(order)

        # create event
        assign_event = OrdersAssignEvent(time, batch, restaurant, driver)
        event_handler.handle_event(assign_event)
        return
    
    def _find_closest_waiting_rest(self, driver: Driver, env: Environment) -> Restaurant | None:
        """
        Finds the resturant with ready orders closest to the driver

        closeness is based on env's travel cost function, so could be zone based or 2d plane pos based
        
        the resutrant must be in the same zone as the driver

        Returns None if there is no restaurant satisfying that condition
        """
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
    
    def _begin_wait(self, env: Environment, event_handler: EventHandler, time:float, driver:Driver) -> None:
        """
        Pushes a wait to the system to try to reassign the driver again
        """
        val = self._rng.randint(1, self.max_policy_wait)
        new_time = time + val
        if new_time <= env.horizon: # guards against infinite runs
            waitEvent = PolicyWaitEvent(time=new_time, driver=driver)
            event_handler.push_event(waitEvent)

    def _find_global_waiting_rest(self, driver: Driver, env: Environment) -> Restaurant | None:
        """
        Searches all zones (not just the driver's current zone) for the closest
        restaurant that has ready orders. Uses the same save/restore pattern as
        _find_closest_waiting_rest so driver state is not mutated.
        """
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

    def _assign_drivers(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler) -> None:
        """
        Tries to assign the driver to a restaurant in their current zone first.
        If none, searches globally and repositions to the closest zone with ready orders.
        If nothing anywhere, begins a policy wait.
        """
        if not driver.is_idle(): # gate for policy wait
            return
        res = self._find_closest_waiting_rest(driver, environment)
        if res is not None:
            self._eaf_algo(time=time, driver=driver, environment=environment,
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
                # same zone but _find_closest_waiting_rest missed it — shouldn't happen
                self._eaf_algo(time=time, driver=driver, environment=environment,
                               event_handler=event_handler, restaurant=res)
            else:
                earliest = min(environment.drivers.values(), key=lambda d: d.next_available_time)
                self._begin_wait(env=environment, event_handler=event_handler, time=earliest.next_available_time, driver=driver)

    def _assign_drivers_order_ready(self, event: OrderReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        """
        triggered by order ready event, the idle drivers of the env are found

        if there is no idle drivers, then put in a policywait event for the
        earliest available driver by sorting on driver.next_available_time

        if there is 1 or more idle drivers,
        check if any of them are in the zone of the orderreadyevent
            if they are: trigger _assign_drivers on that driver
            else: put in a repositionassignevent for the driver closest to the resturant that triggered the orderreadyevent

        for the rest of the idle drivers, trigger _assign_drivers

        Potential issue identified by claude:
        Once in-zone drivers consume the ready orders, every out-zone driver calls 
        _find_closest_waiting_rest, finds nothing in their zone, and pushes a PolicyWaitEvent. 
        With N out-of-zone idle drivers, this fires N redundant wait events that each return early. 
        Over a long horizon with many drivers this accumulates. Out-zone drivers should not 
        be bothered here — they have their own DriverRepositionArriveEvent/DriverReadyEvent path
        """
        idles = environment.idle_drivers()

        if not idles:
            earliest = min(environment.drivers.values(), key=lambda d: d.next_available_time)
            self._begin_wait(env=environment,event_handler=event_handler, time=earliest.next_available_time, driver=earliest)
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
            # no idle driver in triggering zone — reposition the closest one
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
        # resposition_arrive is the last event that is triggered after all orders of a driver has been deivered
        # so this event is really useless atm
        return
    
    def _handle_order_ready(self, event: OrderReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers_order_ready(event, environment, event_handler)
        return

    def _handle_driver_reposition_arrive(self, event: DriverRepositionArriveEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers(event.time, event.driver, environment, event_handler)
        return
    
    def _handle_driver_ready(self, event: DriverReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers(event.time, event.driver, environment, event_handler)
        return
    
    def _handle_policy_wait(self, event: PolicyWaitEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_drivers(event.time, event.driver, environment, event_handler)
        return

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
                return
            elif isinstance(event, DriverRepositionAssignEvent):
                return
            elif isinstance(event, DriverRepositionArriveEvent):
                self._handle_driver_reposition_arrive(event, environment, event_handler)
            else:
                raise TypeError("Unhandled event")
        else:
            raise TypeError("Non-event type")
