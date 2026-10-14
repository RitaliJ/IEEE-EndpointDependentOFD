"""
Input:  zones.json (output of resturant_and_zone_maker.py)
Output: cost_matrix.json — NxN 2D list of floats

Consumed by: build_environment_from_real_data.py

For each pair of zone centroids, compute haversine distance in km.
Matrix is symmetric. Diagonal = 0: this matrix contains only inter-zone travel;
within-zone service is charged by the separate sublinear batch-cost term.
No INF entries — all zones are directly connected.
Do NOT run Floyd-Warshall here; poisson.py's verify_cost_matrix() does that.
Units: km (the sim treats these as abstract cost units, so km is fine).

The file should allow the dev to choose a scalar to divide the haversine output matrix by, it is out speed assumption so that we could get minutes

The JSON should be a bare 2D list (not wrapped in a dict), since poisson.py's COST_MATRIX is just a list[list[float]]
"""

import argparse
import json
from .helpers import haversine_km

def main() -> None:
    parser = argparse.ArgumentParser(description="Build cost_matrix.json from zones.json")
    parser.add_argument("zones", help="Path to zones.json")
    parser.add_argument("output", help="Path to output cost_matrix.json")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Speed in km/min to convert haversine km to minutes (default: 1.0)")
    args = parser.parse_args()

    with open(args.zones) as f:
        zones: dict = json.load(f)

    zone_ids = sorted(zones.keys(), key=lambda k: int(k))
    centroids = [zones[zid]["zone_centriod"] for zid in zone_ids]  # each is [lng, lat]
    n = len(centroids)

    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        # A driver already in the destination zone has no inter-zone travel.
        # Within-zone delivery work is charged separately by the sublinear
        # c(j) * k**alpha term, so a positive diagonal would double-count it.
        matrix[i][i] = 0.0
        lng1, lat1 = centroids[i]
        for j in range(i + 1, n):
            lng2, lat2 = centroids[j]
            d = haversine_km(lng1, lat1, lng2, lat2) / args.speed
            matrix[i][j] = d
            matrix[j][i] = d

    with open(args.output, "w") as f:
        json.dump(matrix, f, indent=2)

    print(f"Wrote {n}x{n} cost matrix → {args.output}")


if __name__ == "__main__":
    main()
