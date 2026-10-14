from mvp_sim.core.zone import Zone
from mvp_sim.core.environment import Environment
import random
import math
import types

def uniform_spread(rng: random.Random, zone_id: int, zones: dict[int, Zone], env: Environment) -> tuple[int, tuple[float, float]]:
    poss_zones = list(set(zones.keys()) - {zone_id})
    chosen = rng.choice(poss_zones)
    return chosen, zones[chosen].zone_centriod

def _softmax_sample(rng: random.Random, ids: list[int], scores: list[float]) -> int:
    max_s = max(scores)
    weights = [math.exp(s - max_s) for s in scores]
    return rng.choices(ids, weights=weights, k=1)[0]

def _zone_cost(origin_zone_id: int, dest_zone_id: int, env: Environment) -> float:
    mock = types.SimpleNamespace(
        curr_zone_id=origin_zone_id,
        dest_zone_id=dest_zone_id,
        curr_pt=env.zones[origin_zone_id].zone_centriod,
        dest_pt=env.zones[dest_zone_id].zone_centriod,
    )
    return env.travel_cost.driver_cost(mock, env.ainfo)

def closest_spread(rng: random.Random, zone_id: int, zones: dict[int, Zone], env: Environment) -> tuple[int, tuple[float, float]]:
    others = [zid for zid in zones if zid != zone_id]
    scores = [-_zone_cost(zone_id, zid, env) for zid in others]
    chosen = _softmax_sample(rng, others, scores)
    return chosen, zones[chosen].zone_centriod

def furtherest_spread(rng: random.Random, zone_id: int, zones: dict[int, Zone], env: Environment) -> tuple[int, tuple[float, float]]:
    others = [zid for zid in zones if zid != zone_id]
    scores = [_zone_cost(zone_id, zid, env) for zid in others]
    chosen = _softmax_sample(rng, others, scores)
    return chosen, zones[chosen].zone_centriod