import math

@staticmethod
def euclidean_dist_zone(a : tuple[float, float], b : tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)

@staticmethod
def manhattan_dist(a : tuple[float, float], b : tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
