from mvp_sim.core.order import Order
from mvp_sim.core.restaurant import Restaurant
from mvp_sim.core.zone import Zone
from mvp_sim.core.environment import Environment
import random
import numpy as np
from typing import Callable
from dataclasses import dataclass

"""
All arrivals pick a number of orders from uniform: 0, horizon

then generate the orders based on that

"""

@dataclass
class ArrivalAuxInfo:
    center: float | None 
    std: float | None
    lam: float | None

SpreadGen = Callable[[random.Random, int, dict[int, Zone], Environment], tuple[int, tuple[float, float]]]

def uniform_arr(rng: random.Random,
                horizon: float,
                restaurant: Restaurant,
                order_spread_gen: SpreadGen,
                zones: dict[int, Zone],
                a_info: ArrivalAuxInfo,
                env: Environment) -> dict[int, Order]:
    orders = {}
    num_orders = rng.randint(0, int(horizon))
    order_timings: list[float] = (
        np.random.default_rng(rng.randint(0, 2**32 - 1))
        .uniform(low=0, high=horizon, size=num_orders)
        .tolist()
    )
    for time in order_timings:
        dest_zone_id, dest = order_spread_gen(rng, restaurant.zone_id, zones, env)
        order = Order(restaurant_id=restaurant.restaurant_id,
                      destination_zone_id=dest_zone_id,
                      destination=dest,
                      arrival_time=time,
                      prep_time=0,
                      deadline=None,
                      profit=0)
        orders[order.order_id] = order
    return orders

def poisson_arr(rng: random.Random,
                horizon: float,
                restaurant: Restaurant,
                order_spread_gen: SpreadGen,
                zones: dict[int, Zone],
                a_info: ArrivalAuxInfo,
                env: Environment) -> dict[int, Order]:
    l = a_info.lam
    assert l
    orders = {}
    num_orders = rng.randint(0, int(horizon))
    inter_arrivals = (
        np.random.default_rng(rng.randint(0, 2**32 - 1))
        .exponential(scale=1.0 / l, size=num_orders)
    )
    order_timings: list[float] = np.cumsum(inter_arrivals).tolist()
    for time in order_timings:
        dest_zone_id, dest = order_spread_gen(rng, restaurant.zone_id, zones, env)
        order = Order(restaurant_id=restaurant.restaurant_id,
                      destination_zone_id=dest_zone_id,
                      destination=dest,
                      arrival_time=time,
                      prep_time=0,
                      deadline=None,
                      profit=0)
        orders[order.order_id] = order
    return orders

def normal_arr(rng: random.Random,
               horizon: float,
               restaurant: Restaurant,
               order_spread_gen: SpreadGen,
               zones: dict[int, Zone],
               a_info: ArrivalAuxInfo,
               env: Environment) -> dict[int, Order]:
    center, std = a_info.center, a_info.std
    assert center
    assert std
    orders = {}
    num_orders = rng.randint(0, int(horizon))
    order_timings: list[float] = (
        np.random.default_rng(rng.randint(0, 2**32 - 1))
        .normal(loc=center, scale=std, size=num_orders)
        .tolist()
    )
    for time in order_timings:
        time = max(0, time)
        dest_zone_id, dest = order_spread_gen(rng, restaurant.zone_id, zones, env)
        order = Order(restaurant_id=restaurant.restaurant_id,
                      destination_zone_id=dest_zone_id,
                      destination=dest,
                      arrival_time=time,
                      prep_time=0,
                      deadline=None,
                      profit=0)
        orders[order.order_id] = order
    return orders