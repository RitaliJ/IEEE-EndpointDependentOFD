from __future__ import annotations
from enum import Enum, auto
from .order import Order

_driver_counter = 0

def _next_driver() -> int:
    global _driver_counter
    _driver_counter += 1
    return _driver_counter

class DriverStatus(Enum):
    IDLE = auto()
    DELIVERING = auto()
    REPOSITIONING = auto()

class Driver:
    """
    Driver class

    The driver class keeps track of its own data, but is also double accounted for in
    both zones and the timeline priority queue.
    
    """
    driver_id:     int             # unique id for lookup in environment.drivers
    curr_zone_id:       int             # the driver's current zone id for lookup in environment.zones, needs to be current_zone for travel_time.py to work
    curr_pt: tuple[float, float]        # the driver's current pt, used for figuring out if the cost should activate when driver is moving within a zone
    dest_pt: tuple[float, float] | None # restaurant currently associated with driver
    dest_zone_id: int | None               # destination that the driver will end up
    status:        DriverStatus    # idle or busy
    processed_orders: list[int]       # list of orderids
    next_available_time: float     # next time the driver is idle

    def __init__(self, zone_id: int, position: tuple[float, float], driver_id: int | None = None):
        self.driver_id = _next_driver() if driver_id is None else driver_id
        self.curr_zone_id = zone_id
        self.curr_pt = position
        self.dest_pt = None
        self.dest_zone_id = None
        self.status = DriverStatus.IDLE
        self.next_available_time = 0
        self.cum_delivering_time : float = 0.0
        # Every interval during which this driver was not idle, as (start, end) in
        # simulation time. Includes travel-to-restaurant, batch delivery, and
        # repositioning. Intervals may overlap or be recorded out of order; the
        # utilization metric merges them before measuring, so double counting a
        # span cannot inflate the result. See stats/metrics.py:busy_time_in_window.
        self.busy_intervals: list[tuple[float, float]] = []
        self.processed_orders = []

    def mark_busy(self, start: float, end: float) -> None:
        """Record a non-idle interval. Zero-length and inverted spans are dropped."""
        if end > start:
            self.busy_intervals.append((start, end))

    def set_delivering(self):
        """
        Note that set_delivering will not alter a zone's queues.
        User must update the queues to reflect the change
        """
        self.status = DriverStatus.DELIVERING
    
    def set_repositioning(self):
        """
        Note that set_repositioning will not alter a zone's queues.
        User must update the queues to reflect the change
        """
        self.status = DriverStatus.REPOSITIONING
    
    def set_idle(self):
        """
        Note that set_idle will not alter a zone's busy / idle queues.
        User must update the queues to reflect the change
        """
        self.status = DriverStatus.IDLE
    
    def is_delivering(self) -> bool:
        return self.status == DriverStatus.DELIVERING
    
    def is_repositioning(self) -> bool:
        return self.status == DriverStatus.REPOSITIONING

    def is_idle(self) -> bool:
        return self.status == DriverStatus.IDLE
    
    def had_order(self, order: Order):
        return order in self.processed_orders
