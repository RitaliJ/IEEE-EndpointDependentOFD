from __future__ import annotations
from functools import total_ordering
from mvp_sim.core.driver import Driver
from mvp_sim.core.environment import Environment
from mvp_sim.core.order import Order
from mvp_sim.core.restaurant import Restaurant
from mvp_sim.core.zone import Zone
from enum import Enum, auto


_event_counter = 0

class EventType(Enum):
    EVENT = auto()
    ORDER_ARRIVE = auto()              # order arrives at restaurant
    ORDER_READY = auto()               # order is prepared at restaurant
    ORDER_ASSIGN = auto()              # order is assigned to driver
    ORDER_DELIVERED = auto()           # driver arrives with order at location
    ORDER_EXPIRED = auto()             # order expires
    DRIVER_ARRIVE = auto()             # driver arrives at restaurant
    DRIVER_READY = auto()              # driver becomes idle
    POLICY_WAIT = auto()               # filler to retrigger policy tick
    DRIVER_REPOSITION_ASSIGN = auto()  # driver is assigned to a new location
    DRIVER_REPOSITION_ARRIVE = auto()  # driver arrives at new location
    

def _next_id() -> int:
    global _event_counter
    _event_counter += 1
    return _event_counter

@total_ordering
class Event():
    time: float
    event_id: int
    event_type: EventType

    def __init__(self, time: float, event_type: EventType):
        self.time = time
        self.event_type = event_type
        self.event_id = _next_id()

    def __lt__(self, other: Event) -> bool:
        if self.time == other.time:
            return self.event_id < other.event_id
        else:
            return self.time < other.time
    
    def __eq__(self, other: Event) -> bool:
        return self.event_id == other.event_id
    
    def __repr__(self) -> str:
        return f"{type(self).__name__}(time={self.time:.3f}, id={self.event_id})"

class OrderArriveEvent(Event):
    order: Order
    restaurant: Restaurant

    def __init__(self, time: float, order: Order, restaurant: Restaurant):
        super().__init__(time, EventType.ORDER_ARRIVE)
        assert(order.restaurant_id == restaurant.restaurant_id)
        self.order = order
        self.restaurant = restaurant

    def __repr__(self) -> str:
        return (f"OrderArriveEvent(time={self.time:.3f}, id={self.event_id}, "
                f"order_id={self.order.order_id})")

class OrderReadyEvent(Event):
    order: Order
    restaurant: Restaurant

    def __init__(self, time: float, order: Order, restaurant: Restaurant):
        super().__init__(time, EventType.ORDER_READY)
        assert(order.restaurant_id == restaurant.restaurant_id)
        self.order = order
        self.restaurant = restaurant

    def __repr__(self) -> str:
        return (f"OrderReadyEvent(time={self.time:.3f}, id={self.event_id}, "
                f"order_id={self.order.order_id})")

class OrdersAssignEvent(Event):
    orders: list[Order]
    restaurant: Restaurant
    driver: Driver

    def __init__(self, time: float, orders: list[Order], restaurant: Restaurant, driver: Driver):
        super().__init__(time, EventType.ORDER_ASSIGN)
        for order in orders:
            assert(order.restaurant_id == restaurant.restaurant_id)
        self.orders = orders
        self.restaurant = restaurant
        self.driver = driver

    def __repr__(self) -> str:
        oids = [o.order_id for o in self.orders]
        return (f"OrdersAssignEvent(time={self.time:.3f}, id={self.event_id}, "
                f"driver_id={self.driver.driver_id}, order_ids={oids})")

class OrderDeliveredEvent(Event):
    """
    Delievered food to house
    """
    order: Order
    driver: Driver

    def __init__(self, time: float, order: Order, driver: Driver):
        super().__init__(time, EventType.ORDER_DELIVERED)
        self.order = order
        self.driver = driver

    def __repr__(self) -> str:
        return (f"OrderDeliveredEvent(time={self.time:.3f}, id={self.event_id}, "
                f"order_id={self.order.order_id}, driver_id={self.driver.driver_id})")

class OrderExpiredEvent(Event):
    order: Order

    def __init__(self, time: float, order: Order):
        super().__init__(time, EventType.ORDER_EXPIRED)
        self.order = order

    def __repr__(self) -> str:
        return (f"OrderExpiredEvent(time={self.time:.3f}, id={self.event_id}, "
                f"order_id={self.order.order_id})")

class DriverArriveEvent(Event):
    """
    Arrives at resturant
    """
    restaurant: Restaurant
    driver: Driver

    def __init__(self, time: float, restaurant: Restaurant, driver: Driver):
        super().__init__(time, EventType.DRIVER_ARRIVE)
        self.restaurant = restaurant
        self.driver = driver

    def __repr__(self) -> str:
        return (f"DriverArriveEvent(time={self.time:.3f}, id={self.event_id}, "
                f"driver_id={self.driver.driver_id}, restaurant_id={self.restaurant.restaurant_id})")

class DriverReadyEvent(Event):
    driver: Driver
    zone: Zone
    location: tuple[float, float]

    def __init__(self, time: float, driver: Driver, zone: Zone, location: tuple[float, float]):
        super().__init__(time, EventType.DRIVER_READY)
        self.driver = driver
        self.zone = zone
        self.location = location

class PolicyWaitEvent(Event):
    driver: Driver
    time: float
    def __init__(self, time: float, driver: Driver):
        super().__init__(time, EventType.POLICY_WAIT)
        self.time = time
        self.driver = driver


class DriverRepositionAssignEvent(Event):
    driver: Driver
    zone: Zone
    location: tuple[float,float]

    def __init__(self, time: float, driver: Driver, zone: Zone, location: tuple[float, float]):
        super().__init__(time, EventType.DRIVER_REPOSITION_ASSIGN)
        self.driver = driver
        self.zone = zone
        self.location = location

    def __repr__(self) -> str:
        return (f"DriverRepositionAssignEvent(time={self.time:.3f}, id={self.event_id}, "
                f"driver_id={self.driver.driver_id}, zone_id={self.zone.zone_id}, "
                f"location={list(self.location)})")

class DriverRepositionArriveEvent(Event):
    driver: Driver
    zone: Zone
    location: tuple[float,float]

    def __init__(self, time: float, driver: Driver, zone: Zone, location: tuple[float, float]):
        super().__init__(time, EventType.DRIVER_REPOSITION_ARRIVE)
        self.driver = driver
        self.zone = zone
        self.location = location

    def __repr__(self) -> str:
        return (f"DriverRepositionArriveEvent(time={self.time:.3f}, id={self.event_id}, "
                f"driver_id={self.driver.driver_id}, zone_id={self.zone.zone_id}, "
                f"location={list(self.location)})")