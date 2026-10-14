"""
output_to_json: yes/no — whether this field should appear in the output JSON

Input:  <path/to/file.csv>,
Output: <path/to/zones.json>

output schema:
{}

all ids start at 1 (zone_ids and resturant_ids)

Consumed by: build_environment_from_real_data.py

a resturant's position is a unique accept_gps_lat/lng coordinate pair

that means: number of resturants = number of unique accept_gps_lat/lng pairs

For zones:
 Start with DBSCAN using haversine distance of accept_gps_lat/lng pairs.
 If the clusters look wrong, fall back to agglomerative with a dendrogram cut.

ZONES:
yes    zone_id:  int
yes    zone_centriod: tuple[float, float]       # DBSCAN Core points
yes    restaurants: dict[int, Restaurant]
no    idle_drivers: dict[int, Driver]
no    busy_drivers: dict[int, Driver]

RESTURANTS:
yes    restaurant_id:  int
yes    zone_id:        int
yes    position:  tuple[float, float]           # unique accept_gps_lat/lng pair foound in the csv
no    orders_in_progress: int
no    capacity: int | None
no    prep_subqueues: dict[int, list[int]] # zone to unprepared order id
no    ready_subqueues: dict[int, list[int]] # zone to ready order ids
no    assigned_orders: dict[int, list[int]] # driver to order ids

fields always in csv:
order_id,region_id,city,courier_id,lng,lat,aoi_id,aoi_type,accept_time,accept_gps_time,accept_gps_lng,accept_gps_lat,delivery_time,delivery_gps_time,delivery_gps_lng,delivery_gps_lat,ds

"""

import argparse
import csv
import json

import numpy as np
from sklearn.cluster import DBSCAN

# earth's mean radius in km
R = 6371.0

def main() -> None:
    parser = argparse.ArgumentParser(description="Build zones.json from delivery CSV data")
    parser.add_argument("csv", help="Path to input CSV file")
    parser.add_argument("output", help="Path to output zones.json")
    parser.add_argument("--eps-km", type=float, default=1.0,
                        help="DBSCAN epsilon radius in km (default: 1.0)")
    parser.add_argument("--min-samples", type=int, default=1,
                        help="DBSCAN min_samples (default: 1)")
    args = parser.parse_args()

    # Collect unique (lng, lat) restaurant positions in CSV row order
    seen: set[tuple[float, float]] = set([])
    with open(args.csv) as f:
        for row in csv.DictReader(f):
            key = (float(row["accept_gps_lng"]), float(row["accept_gps_lat"]))
            seen.add(key)
    positions = list(seen)  # (lng, lat)

    # DBSCAN: sklearn haversine metric expects (lat, lng) in radians
    coords_rad = np.radians([[lat, lng] for lng, lat in positions])
    labels = DBSCAN(
        eps=args.eps_km / R,
        min_samples=args.min_samples,
        algorithm="ball_tree",
        metric="haversine",
    ).fit_predict(coords_rad)

    # Group positions by cluster; noise points (label == -1) each get their own cluster
    cluster_map: dict[int, list[tuple[float, float]]] = {}
    noise_id = int(max(labels)) + 1
    for i, label in enumerate(labels):
        k = label if label != -1 else noise_id + i
        cluster_map.setdefault(k, []).append(positions[i])

    zones: dict[str, object] = {}
    restaurant_id = 1
    for zone_idx, cluster_key in enumerate(sorted(cluster_map.keys()), start=1):
        rest_positions = cluster_map[cluster_key]
        centroid_lng = sum(p[0] for p in rest_positions) / len(rest_positions)
        centroid_lat = sum(p[1] for p in rest_positions) / len(rest_positions)

        restaurants: dict[str, object] = {}
        for pos in rest_positions:
            restaurants[str(restaurant_id)] = {
                "restaurant_id": restaurant_id,
                "zone_id": zone_idx,
                "position": list(pos),
            }
            restaurant_id += 1

        zones[str(zone_idx)] = {
            "zone_id": zone_idx,
            "zone_centriod": [centroid_lng, centroid_lat],
            "restaurants": restaurants,
        }

    with open(args.output, "w") as f:
        json.dump(zones, f, indent=2)

    print(f"Wrote {len(zones)} zones, {restaurant_id - 1} restaurants → {args.output}")


if __name__ == "__main__":
    main()
