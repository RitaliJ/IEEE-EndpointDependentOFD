from __future__ import annotations
from enum import Enum, auto

_order_counter = 0

def _next_order() -> int:
    global _order_counter
    _order_counter += 1
    return _order_counter

class OrderStatus(Enum):
    PREPPING = auto()
    READY = auto()
    ASSIGNED = auto()
    PICKED_UP = auto()
    DELIVERED = auto()
    EXPIRED = auto()

class Order:
    """
    Order class

    The order class keeps track of its own data, but is also double accounted for in
    either restaurant subqueues, the timeline priority queue, or the list of
    completed orders.
    
    """
    order_id:         int    # set on creation
    restaurant_id:    int    # set on creation
    destination_zone_id: int    # set on creation
    destination:      tuple[float, float] # set on creation
    order_status:     OrderStatus
    arrival_time:     float  # set on creation
    prep_time:        float  # the time to get the order ready
    prep_ready_time:  float | None  # the time the order is ready
    completion_time:  float | None  # set on assign
    deadline:         float | None  # the time the order must be ready
    profit:           float  
    assigned_driver:  int | None   = None  # set on assign

    def __init__(self,
                 restaurant_id: int,
                 destination_zone_id: int,
                 destination: tuple[float, float],
                 arrival_time: float,
                 prep_time: float,
                 deadline: float | None,
                 profit: float,
                 order_id: int | None = None):
        # Pass order_id explicitly when replaying a scenario. The module-global
        # counter keeps incrementing across runs in the same process, so policies
        # run back-to-back would otherwise see disjoint id ranges for the same
        # logical orders -- and order_id is a tie-breaker in several policies.
        self.order_id = _next_order() if order_id is None else order_id
        self.restaurant_id = restaurant_id
        self.destination_zone_id = destination_zone_id
        self.destination = destination
        self.order_status = OrderStatus.PREPPING
        self.arrival_time = arrival_time
        self.prep_time = prep_time
        self.prep_ready_time = None
        self.deadline = deadline
        self.completion_time = None
        self.profit = profit
        self.assigned_driver = None
        

    def delivered(self, time: float) -> bool:
        if self.completion_time is not None:
            return self.completion_time <= time
        return False

    def flow_time(self) -> float:
        if self.completion_time is None:
            raise ValueError(
                "cannot calculate the flow time of an order that has not been " \
                "completed"
            )
        return self.completion_time - self.arrival_time
    
    #TODO getters and setters
