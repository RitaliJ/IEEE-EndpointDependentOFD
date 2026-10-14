import math

def haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))

def nearest_zone_id(lng: float, lat: float, zone_centroids: dict[int, tuple[float, float]]) -> int:
    best_id, best_d = -1, math.inf
    for zid, (clng, clat) in zone_centroids.items():
        d = haversine_km(lng, lat, clng, clat)
        if d < best_d:
            best_d = d
            best_id = zid
    return best_id