from __future__ import annotations
from dataclasses import dataclass, field
from .driver import Driver
from .restaurant import Restaurant

_zone_counter = 0

def _next_zone() -> int:
    global _zone_counter
    _zone_counter += 1
    return _zone_counter

class Zone:
    """
    Zone class

    The zone class is in charge of keeping track of its restaurants
    and drivers in itself
    """
    zone_id:  int
    zone_centriod: tuple[float, float]
    restaurants: dict[int, Restaurant]
    idle_drivers: dict[int, Driver]
    busy_drivers: dict[int, Driver]

    def __init__(self,
                 restaurants: dict[int, Restaurant],
                 idle_drivers: dict[int, Driver],
                 busy_drivers: dict[int, Driver],
                 zone_centriod: tuple[float, float],
                 zone_id: int | None = None):
        self.zone_id = zone_id if zone_id is not None else _next_zone()
        self.restaurants = restaurants
        self.idle_drivers = idle_drivers
        self.busy_drivers = busy_drivers
        self.zone_centriod = zone_centriod


    