"""
output_to_json: yes/no — whether this field should appear in the output JSON

Input:  <path/to/file.csv>,  <path/to/zones.json>  (output of resturant_and_zone_maker.py)
Output: <path/to/orders.json>

Output Scheme:
[{order_id, restaurant_id, destination_zone_id, destination, order_status}, ...]

all ids start at 1

Consumed by: build_environment_from_real_data.py

arrival is not accept_time, do not use it in any way

DO NOT use lng/lat in order to find restaurant_id in <path/tozones.json>, use accept_gps_lat/lng

yes    order_id:         int
yes    restaurant_id:    int                        # get from the accept_gps_lat/lng and the zones.json
yes    destination_zone_id: int                     #  find the nearest zone centroid in zones.json to delivery_gps_lat/lng → that's destination_zone_id
yes    destination:      tuple[float, float]        # the raw (delivery_gps_lng, delivery_gps_lat) is destination
no    order_status:     OrderStatus
no    arrival_time:     float  # based on resturant config, each resturant is configed to a synthetic generator
no    prep_time:        float
no    prep_ready_time:  float | None  # set by sim engine
no    completion_time:  float | None  # set by sim engine
no    deadline:         float | None
no    profit:           float
no    assigned_driver:  int | None   = None  # set on assign

fields always in csv:
order_id,region_id,city,courier_id,lng,lat,aoi_id,aoi_type,accept_time,accept_gps_time,accept_gps_lng,accept_gps_lat,delivery_time,delivery_gps_time,delivery_gps_lng,delivery_gps_lat,ds
"""

import argparse
import csv
import json
from .helpers import nearest_zone_id

def main() -> None:
    parser = argparse.ArgumentParser(description="Build orders.json from CSV and zones.json")
    parser.add_argument("csv", help="Path to input CSV file")
    parser.add_argument("zones", help="Path to zones.json")
    parser.add_argument("output", help="Path to output orders.json")
    args = parser.parse_args()

    with open(args.zones) as f:
        zones: dict = json.load(f)

    # Build (lng, lat) → restaurant_id lookup and zone_id → centroid lookup
    pos_to_restaurant: dict[tuple[float, float], int] = {}
    zone_centroids: dict[int, tuple[float, float]] = {}
    for zid, zone in zones.items():
        zone_centroids[int(zid)] = (zone["zone_centriod"][0], zone["zone_centriod"][1])
        for rest in zone["restaurants"].values():
            pos = (rest["position"][0], rest["position"][1])
            pos_to_restaurant[pos] = rest["restaurant_id"]

    orders = []
    order_id = 1
    with open(args.csv) as f:
        for row in csv.DictReader(f):
            accept_lng = float(row["accept_gps_lng"])
            accept_lat = float(row["accept_gps_lat"])
            delivery_lng = float(row["delivery_gps_lng"])
            delivery_lat = float(row["delivery_gps_lat"])

            restaurant_id = pos_to_restaurant[(accept_lng, accept_lat)]
            destination_zone_id = nearest_zone_id(delivery_lng, delivery_lat, zone_centroids)

            orders.append({
                "order_id": order_id,
                "restaurant_id": restaurant_id,
                "destination_zone_id": destination_zone_id,
                "destination": [delivery_lng, delivery_lat],
            })
            order_id += 1

    with open(args.output, "w") as f:
        json.dump(orders, f, indent=2)

    print(f"Wrote {len(orders)} orders → {args.output}")


if __name__ == "__main__":
    main()
