from __future__ import annotations
from .order import Order
from .driver import Driver
from .restaurant import Restaurant
from .zone import Zone
from ..cost_functions.travel_time import TravelCost, AuxInfo

class Environment:
    def __init__(
        self,
        zones: dict[int, Zone],                         # zone_id to zone
        restaurants: dict[int, Restaurant],             # restaurant_id to restaurant
        drivers: dict[int, Driver],                     # driver_id to driver
        orders: dict[int, Order],                       # order_id to order
        travel_cost: TravelCost,                        # cost of traveling for a batch of orders
        obj_function: staticmethod | None,                     # objective function that the policy tries to optimize
        warmup_duration: float,                         # how long should the system warm up for before metrics begin computing
        horizon: float,                                 # end of the simulation
        ainfo: AuxInfo                                  # aux info needed to run the cost function
    ):
        self.zones = zones
        self.restaurants = restaurants
        self.drivers = drivers
        self.orders:dict[int, Order] = orders
        self.travel_cost = travel_cost
        self.obj_function = obj_function
        self.warmup_duration = warmup_duration
        self.horizon = horizon
        self.ainfo = ainfo
        self.batches: list[tuple[Driver, list[Order]]] = []    # batches of orders in this simulation
        self.driver_pickup_and_reposition_time: list[float] = []    # chronological list of drivers and their repositioning/picking up times witohut orders in their basket

    def idle_drivers(self) -> list[Driver]:
        idlers = []
        for zone in self.zones.values():
            idlers = idlers + list(zone.idle_drivers.values())
        return idlers
    
    def compute_orders_travel_cost(self, orders: list[Order], driver: Driver) -> list[float]:
        return self.travel_cost.orders_cost(orders, driver, self.ainfo)
    
    def compute_driver_travel_cost(self, driver: Driver) -> float:
        return self.travel_cost.driver_cost(driver, self.ainfo)
    
    def add_batch(self, driver: Driver, batch: list[Order]) -> None:
        self.batches.append((driver, batch))