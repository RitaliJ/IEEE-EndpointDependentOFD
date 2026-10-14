from __future__ import annotations
from .order import Order
from .driver import Driver

_restaurant_counter = 0

def _next_restaurant() -> int:
    global _restaurant_counter
    _restaurant_counter += 1
    return _restaurant_counter

class Restaurant:
    """
    Restaurant class

    The restaurant class is in charge of keeping track of its orders
    and which zones they belong to.

    Flow:
        order arrives in restaurant -> goes to prep_subqueue[zone]
        order is ready -> goes to ready_subqueue[zone]
        order is assigned -> goes to assigned_orders[driver_id]
        order is picked up -> order is no longer tracked by restaurant
    
    TODO: define capacity, do orders that are completed but not
          picked up contribute? Currently, yes
    """
    restaurant_id:  int
    zone_id:        int
    position:  tuple[float, float]
    orders_in_progress: int
    capacity: int | None
    prep_subqueues: dict[int, list[int]] # zone to unprepared order id
    ready_subqueues: dict[int, list[int]] # zone to ready order ids
    assigned_orders: dict[int, list[int]] # driver to order ids

    def __init__(self,
                 zone_id: int,
                 position: tuple[float, float],
                 capacity: int | None = None,
                 restaurant_id: int | None = None):
        self.restaurant_id = restaurant_id if restaurant_id is not None else _next_restaurant()
        self.zone_id = zone_id
        self.position = position
        self.orders_in_progress = 0
        self.capacity = capacity
        self.prep_subqueues = {}
        self.ready_subqueues = {}
        self.assigned_orders = {}

    def add_order(self, order: Order) -> bool:
        """
        places order in prep_subqueue for zone
        increases orders_in_progress
        """
        if self.capacity is not None and self.orders_in_progress >= self.capacity:
            return False
        self.orders_in_progress += 1
        order_id = order.order_id
        zone_id = order.destination_zone_id
        if zone_id not in self.prep_subqueues.keys():
            self.prep_subqueues[zone_id] = []
        self.prep_subqueues[zone_id].append(order_id)
        return True
    
    def prep_order(self, order: Order) -> None:
        """
        moves order from prep_subqueue for zone to ready_subqueue for zone
        returns True if successful (can fail if order was not in prep_subqueue)
        """
        order_id = order.order_id
        zone_id = order.destination_zone_id
        if order_id not in self.prep_subqueues[zone_id]:
            raise KeyError(
                f"order {order.order_id!r} not found in prep_subqueues for zone {zone_id}"
                f"of restaurant {self.restaurant_id}"
            )
        self.prep_subqueues[zone_id].remove(order_id)
        if zone_id not in self.ready_subqueues.keys():
            self.ready_subqueues[zone_id] = []
        self.ready_subqueues[zone_id].append(order_id)
        return None
    
    def assign_orders(self, orders: list[Order], driver: Driver) -> None:
        """
        moves orders from ready_subqueues to assigned_order
        returns True if successful (can fail if orders were not in ready_subqueues)
        """
        for order in orders:
            zone_id = order.destination_zone_id
            if order.order_id not in self.ready_subqueues.get(zone_id, []):
                raise ValueError(
                    f"order {order.order_id!r} not in ready_subqueues for zone {zone_id}"
                    f"of restaurant {self.restaurant_id}"
                )
        if driver.driver_id not in self.assigned_orders.keys():
            self.assigned_orders[driver.driver_id] = []
        for order in orders:
            self.ready_subqueues[order.destination_zone_id].remove(order.order_id)
            self.assigned_orders[driver.driver_id].append(order.order_id)
        return
    
    def pickup_orders(self, driver: Driver) -> list[int]:
        """
        removes orders from assigned order and decreases orders in progress
        returns the removed order_ids
        """
        orders = self.assigned_orders.pop(driver.driver_id, [])
        self.orders_in_progress -= len(orders)
        return orders
    
    def expire_order(self, order: Order) -> bool:
        """Remove an expired order from prep_subqueues or ready_subqueues.

        Returns True if the order was found and removed, False if it was already
        assigned or picked up (in which case expiry is a no-op — too late to cancel).
        Raises nothing; a not-found order that is ASSIGNED/PICKED_UP is silently skipped.
        """
        zone_id = order.destination_zone_id
        for subqueue in (self.prep_subqueues, self.ready_subqueues):
            lst = subqueue.get(zone_id, [])
            if order.order_id in lst:
                self.orders_in_progress -= 1
                lst.remove(order.order_id)
                return True
        return False


    def ready_order_ids(self, zone_id: int) -> list[int]:
        """
        returns the order_ids of all unassigned ready orders in a zone
        """
        return self.ready_subqueues.get(zone_id, [])

    def ready_subqueue_size(self, zone_id: int) -> int:
        """
        returns the number of unassigned ready orders there are for a zone
        """
        return len(self.ready_subqueues.get(zone_id, []))