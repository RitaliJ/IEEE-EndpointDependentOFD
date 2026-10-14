from mvp_sim.simulator.events import *
from mvp_sim.simulator.event_handler import EventHandler
from mvp_sim.core.environment import Environment
from ..base import Policy

"""
Policy only works on num_drivers = 1 bc
driverready events are popped after orderarrive
so the only thing that activates _assign_driver is order_ready which is hard coded for
driver[0]


This is EAF:= "earleist anticipation first" policy defined in 
https://www.sciencedirect.com/science/article/pii/S0304397522003607?fr=RR-2&rr=9f692339dfa455da
"""

class Star_EAF(Policy):

    def _anticipation_time(self, order: Order, environment: Environment) -> float:
        r = order.arrival_time
        d = environment.compute_orders_travel_cost([order], list(environment.drivers.values())[0])
        return r + sum(d)

    def _assign_driver(self, time: float, driver: Driver, environment: Environment, event_handler: EventHandler) -> None:
        if not driver.is_idle():
            return
        restaurant = list(environment.restaurants.values())[0]

        # collect all ready orders across all destination zones
        queue: list[Order] = []
        for order_ids in restaurant.ready_subqueues.values():
            for oid in order_ids:
                queue.append(environment.orders[oid])

        # get earliest anticipation
        if len(queue) == 0:
            if driver.curr_pt != restaurant.position:
                center_zone = environment.zones[restaurant.zone_id]
                reposition_assign_event = DriverRepositionAssignEvent(time,
                                                                      driver,
                                                                      center_zone,
                                                                      restaurant.position)
                event_handler.handle_event(reposition_assign_event)
            return
        earliest_anticipation = self._anticipation_time(queue[0], environment)
        earliest_order = queue[0]
        for i in range(1, len(queue)):
            order = queue[i]
            anticipation = self._anticipation_time(order, environment)
            if (anticipation < earliest_anticipation):
                earliest_anticipation = anticipation
                earliest_order = queue[i]
        
        # batch all orders going to earliest anticipation destination
        batch = []
        for order in queue:
            if order.destination == earliest_order.destination:
                batch.append(order)

        # create event
        assign_event = OrdersAssignEvent(time, batch, restaurant, driver)
        event_handler.handle_event(assign_event)
        return

    def _handle_order_delivered(self, event: OrderDeliveredEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_driver(event.time, event.driver, environment, event_handler)
        return
    
    def _handle_order_ready(self, event: OrderReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_driver(event.time, list(environment.drivers.values())[0], environment, event_handler)
        return

    def _handle_driver_reposition_arrive(self, event: DriverRepositionArriveEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_driver(event.time, event.driver, environment, event_handler)
        return
    
    def _handle_driver_ready(self, event: DriverReadyEvent, environment: Environment, event_handler: EventHandler) -> None:
        self._assign_driver(event.time, event.driver, environment, event_handler)
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
                return
            elif isinstance(event, DriverRepositionAssignEvent):
                return
            elif isinstance(event, DriverRepositionArriveEvent):
                self._handle_driver_reposition_arrive(event, environment, event_handler)
            else:
                raise TypeError("Unhandled event")
        else:
            raise TypeError("Non-event type")