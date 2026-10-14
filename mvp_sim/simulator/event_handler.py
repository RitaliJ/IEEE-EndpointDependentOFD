from mvp_sim.core.driver import Driver
from mvp_sim.core.environment import Environment
from mvp_sim.core.order import Order, OrderStatus
from mvp_sim.core.restaurant import Restaurant
from mvp_sim.core.zone import Zone
from .events import *
import heapq
import logging

logger = logging.getLogger(__name__)

class EventHandler():
    event_timeline: list[Event]
    handled_events: list[Event]
    environment: Environment
    
    def __init__(self, environment: Environment, timeline: list[Event] = []):
        self.event_timeline = timeline
        heapq.heapify(self.event_timeline)
        self.handled_events = []
        self.environment = environment

    def push_event(self, event: Event) -> None:
        heapq.heappush(self.event_timeline, event)
        return
    
    def pop_next_event(self) -> Event:
        return heapq.heappop(self.event_timeline)
    
    def has_events(self) -> bool:
        return len(self.event_timeline) > 0
    
    def handle_policy_wait(self, event: PolicyWaitEvent) -> None:
        logger.debug(
            "policy_wait at %f", event.time)

    def handle_order_arrival(self, event: OrderArriveEvent) -> None:
        """
        Order arrives into the system and makes a order ready event
        also makes a order expire event
        """
        env = self.environment
        order = event.order
        order.prep_ready_time = event.time + order.prep_time
        added = event.restaurant.add_order(event.order)
        if not added:
            logger.warning(
                "order %s dropped - restaurant %s at capacity",
                order.order_id, event.restaurant.restaurant_id,
            )
            return
        env.orders[order.order_id] = order
        
        readyEvent = OrderReadyEvent(time = order.prep_ready_time,
                                    order = event.order,
                                    restaurant= event.restaurant)
        self.push_event(readyEvent)
        if order.deadline is not None:
            self.push_event(OrderExpiredEvent(
                time = event.time + order.deadline,
                order = order,
            ))

        logger.debug("order %s arrived at restaurant %s", order.order_id, event.restaurant.restaurant_id)


    def handle_order_ready(self, event: OrderReadyEvent) -> None:
        """
        Order is ready for pikcup and the policy gets activated
        """
        event.restaurant.prep_order(event.order)
        event.order.order_status = OrderStatus.READY
        logger.debug("order %s ready at restaurant %s", event.order.order_id, event.restaurant.restaurant_id)

        
    def handle_orders_assign(self, event: OrdersAssignEvent) -> None:
        """
        Makes the driver go to the resturant
        """
        env = self.environment
        assert len(event.orders) > 0
        env.add_batch(event.driver, event.orders)

        for order in event.orders:
            order.assigned_driver = event.driver.driver_id
            order.order_status = OrderStatus.ASSIGNED

        event.restaurant.assign_orders(orders = event.orders, driver = event.driver)
        event.driver.set_delivering()
        # set driver to busy, remove from idle in zone, add to busy in restaurant zone; good accounting
        env.zones[event.driver.curr_zone_id].idle_drivers.pop(event.driver.driver_id)
        env.zones[event.restaurant.zone_id].busy_drivers[event.driver.driver_id] = event.driver

        event.driver.dest_pt = event.restaurant.position
        event.driver.dest_zone_id = event.restaurant.zone_id

        travel_time = env.compute_driver_travel_cost(event.driver)
        env.driver_pickup_and_reposition_time.append(travel_time)
        driverArriveEvent = DriverArriveEvent(time = event.time + travel_time,
                                                  restaurant = event.restaurant,
                                                  driver = event.driver)
        self.push_event(driverArriveEvent)

        event.driver.next_available_time = event.time + travel_time
        # Travelling to the restaurant is busy time: the driver is unavailable.
        event.driver.mark_busy(event.time, event.time + travel_time)

        logger.debug(
            "driver %s assigned %d orders from restaurant %s, arrives in %.1fs",
            event.driver.driver_id, len(event.orders),
            event.restaurant.restaurant_id, travel_time,
        )
        return
    
    def handle_driver_arrive(self, event: DriverArriveEvent) -> None:
        """
        Driver arrives and picksup all the orders from the resturant
        """
        env = self.environment
        driver = event.driver
        restaurant = event.restaurant
        
        driver.curr_pt = restaurant.position
        driver.curr_zone_id = restaurant.zone_id

        order_ids = restaurant.pickup_orders(driver)
        orders = list(map(lambda x : env.orders[x] ,order_ids))
        order_travel_times = env.compute_orders_travel_cost(orders, driver)
        driver.next_available_time = event.time + sum(order_travel_times)
        if len(orders) > 0:
            for i in range(len(orders)):
                order, travel_time = orders[i], order_travel_times[i]
                order.order_status = OrderStatus.PICKED_UP
                driver.processed_orders.append(order.order_id)

                orderDelivered = OrderDeliveredEvent(time = event.time + travel_time,
                                                        order = order,
                                                        driver = event.driver)
                self.push_event(orderDelivered)

            driver.next_available_time = event.time + order_travel_times[-1]
            # Serving the batch is busy time. Record the raw span; clipping to the
            # measurement window and merging overlaps happens once, in the metric.
            driver.mark_busy(event.time, event.time + order_travel_times[-1])

            warmup = self.environment.warmup_duration
            horizon = self.environment.horizon
            post_warmup = max(0.0, min(event.time + order_travel_times[-1], horizon) - max(event.time, warmup))
            driver.cum_delivering_time += post_warmup

            logger.debug(
                "driver %s picked up %d orders; first delivery in %.1f; next avaible_time: %.1f",
                driver.driver_id, len(orders), order_travel_times[0], driver.next_available_time
            )

            last_order = orders[-1]

            # drivers arrives at the ending zone event:
            arriving_at_end_loc_event = DriverRepositionArriveEvent(time = driver.next_available_time,
                                                driver = driver,
                                                zone = env.zones[last_order.destination_zone_id],
                                                location = last_order.destination)
            self.push_event(arriving_at_end_loc_event)

            env.zones[event.driver.curr_zone_id].busy_drivers.pop(driver.driver_id)
            env.zones[last_order.destination_zone_id].busy_drivers[driver.driver_id] = driver

            driver.dest_pt = last_order.destination
            driver.dest_zone_id = last_order.destination_zone_id
        else:
            driver.next_available_time = event.time
            driver.set_idle()
            env.zones[driver.curr_zone_id].busy_drivers.pop(driver.driver_id)
            env.zones[driver.curr_zone_id].idle_drivers[driver.driver_id] = driver
            driver.dest_pt = None
            driver.dest_zone_id = None
            logger.debug(
                "driver %s is now idle; driver current zone: %s; driver current pt: %s",
                driver.driver_id, driver.curr_zone_id, driver.curr_pt
            )

    def handle_order_delivered(self, event: OrderDeliveredEvent) -> None:
        """
        Doesn't need driver next avaiable time because it was taken care of during
        pickup
        """
        driver = event.driver
        order = event.order
        order.completion_time = event.time
        order.order_status = OrderStatus.DELIVERED
        driver.curr_zone_id = order.destination_zone_id
        driver.curr_pt = order.destination

        logger.debug(
            "order %s delivered by driver %s at t=%.2f",
            order.order_id, driver.driver_id, event.time,
        )

    def handle_driver_reposition_assign(self, event: DriverRepositionAssignEvent) -> None:
        driver = event.driver
        if not driver.is_idle():
            raise ValueError(
                f"DriverRepositionAssignEvent for driver {driver.driver_id} "
                f"but status is {driver.status.name}, expected Idle"
            )

        driver.set_repositioning()
        
        env = self.environment
        env.zones[driver.curr_zone_id].idle_drivers.pop(driver.driver_id)
        event.zone.busy_drivers[driver.driver_id] = driver

        driver.dest_pt = event.zone.zone_centriod
        driver.dest_zone_id = event.zone.zone_id

        travel_time = env.compute_driver_travel_cost(driver)
        env.driver_pickup_and_reposition_time.append(travel_time)
        driverRepositionArriveEvent = DriverRepositionArriveEvent(time = event.time + travel_time,
                                                                      driver = driver,
                                                                      zone = event.zone,
                                                                      location = event.location)
        self.push_event(driverRepositionArriveEvent)

        driver.next_available_time = event.time + travel_time
        # Repositioning is busy time: the driver cannot take work while in transit.
        driver.mark_busy(event.time, event.time + travel_time)

        logger.debug(
            "driver %s repositioning to zone %s, arrives in %.1fs",
            driver.driver_id, event.zone.zone_id, travel_time,
        )

    def handle_driver_reposition_arrive(self, event: DriverRepositionArriveEvent) -> None:
        env = self.environment
        driver = event.driver
        driver.set_idle()
        event.zone.idle_drivers[driver.driver_id] = driver
        assert driver.dest_zone_id
        env.zones[driver.dest_zone_id].busy_drivers.pop(driver.driver_id)
        driver.curr_pt = event.location
        driver.curr_zone_id = event.zone.zone_id

        driver.dest_pt = None
        driver.dest_zone_id = None

        logger.debug(
            "driver %s arrived at zone %s after reposition",
            driver.driver_id, event.zone.zone_id,
        )

    def handle_driver_ready(self, event: DriverReadyEvent) -> None:
        """Start of the sim, driver is ready"""
        driver = event.driver
        driver.set_idle()
        event.zone.idle_drivers[driver.driver_id] = driver
        driver.curr_pt = event.location
        driver.curr_zone_id = event.zone.zone_id

        driver.dest_pt = None
        driver.dest_zone_id = None

        logger.debug(
            "driver %s is ready at zone %s at location: %s",
            driver.driver_id, event.zone.zone_id, event.location
        )

    def _handle_order_expired(self, event: OrderExpiredEvent) -> None:
        env = self.environment
        order = event.order
        restaurant = env.restaurants[order.restaurant_id]
        # No-op if the order was already picked up or delivered
        if order.order_status in (OrderStatus.PICKED_UP, OrderStatus.DELIVERED):
            return
        removed = restaurant.expire_order(order)
        if removed:
            order.order_status = OrderStatus.EXPIRED
            logger.info(
                "order %s expired at t=%.2f (deadline=%.2f)",
                order.order_id, event.time, order.deadline,
            )

    def handle_event(self, event) -> None:
        if issubclass(type(event), Event):
            if isinstance(event, OrderArriveEvent):
                self.handle_order_arrival(event)
            elif isinstance(event, OrderReadyEvent):
                self.handle_order_ready(event)
            elif isinstance(event, OrdersAssignEvent):
                self.handle_orders_assign(event)
            elif isinstance(event, OrderDeliveredEvent):
                self.handle_order_delivered(event)
            elif isinstance(event, OrderExpiredEvent):
                self._handle_order_expired(event)
            elif isinstance(event, DriverArriveEvent):
                self.handle_driver_arrive(event)
            elif isinstance(event, DriverReadyEvent):
                self.handle_driver_ready(event)
            elif isinstance(event, PolicyWaitEvent):
                self.handle_policy_wait(event)
            elif isinstance(event, DriverRepositionAssignEvent):
                self.handle_driver_reposition_assign(event)
            elif isinstance(event, DriverRepositionArriveEvent):
                self.handle_driver_reposition_arrive(event)
            else:
                raise TypeError("Unhandled event")
        else:
            raise TypeError("Non-event type")
        
        self.handled_events.append(event)
