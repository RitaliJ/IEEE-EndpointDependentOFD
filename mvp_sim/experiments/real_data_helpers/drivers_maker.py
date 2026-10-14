"""
output_to_json: yes/no — whether this field should appear in the output JSON

Input:  <path/to/file.csv>,  <path/to/zones.json>  (output of resturant_and_zone_maker.py)
Output: <path/to/drivers.json>

output schema:
[{driver_id, curr_zone_id, curr_pt, dest_pt, dest_zone_id, status}, ...]

all ids start at 1

Consumed by: build_environment_from_real_data.py

find the nearest zone centroid in zones.json closest to the driver's first accept_gps_lat/lng — that zone is curr_zone_id, that centroid is curr_pt

yes    driver_id:     int
yes    curr_zone_id:       int
yes    curr_pt: tuple[float, float]
yes    dest_pt: tuple[float, float] | None      # set to None
yes    dest_zone_id: int | None                 # set to None
no    status:        DriverStatus
no    processed_orders: list[int]
no    next_available_time: float


outputs a json to make driver objects for simulation

fields always in csv:
order_id,region_id,city,courier_id,lng,lat,aoi_id,aoi_type,accept_time,accept_gps_time,accept_gps_lng,accept_gps_lat,delivery_time,delivery_gps_time,delivery_gps_lng,delivery_gps_lat,ds

"""

import argparse
import csv
import json
import random
from .helpers import nearest_zone_id

def main(rng: random.Random) -> None:
    parser = argparse.ArgumentParser(description="Build drivers.json from CSV and zones.json")
    parser.add_argument("csv", help="Path to input CSV file")
    parser.add_argument("zones", help="Path to zones.json")
    parser.add_argument("output", help="Path to output drivers.json")
    args = parser.parse_args()

    assert rng != None

    with open(args.zones) as f:
        zones: dict = json.load(f)

    zone_centroids: dict[int, tuple[float, float]] = {
        int(zid): (zone["zone_centriod"][0], zone["zone_centriod"][1])
        for zid, zone in zones.items()
    }

    # Bounding box from zone centroids
    all_lngs = [c[0] for c in zone_centroids.values()]
    all_lats = [c[1] for c in zone_centroids.values()]
    min_lng, max_lng = min(all_lngs), max(all_lngs)
    min_lat, max_lat = min(all_lats), max(all_lats)

    # Collect unique courier_ids
    courier_ids: set[int] = set()
    with open(args.csv) as f:
        for row in csv.DictReader(f):
            courier_ids.add(int(row["courier_id"]))

    drivers = []
    driver_id = 1
    for courier_id in sorted(courier_ids):
        lng = rng.uniform(min_lng, max_lng)
        lat = rng.uniform(min_lat, max_lat)
        zid = nearest_zone_id(lng, lat, zone_centroids)
        clng, clat = zone_centroids[zid]
        drivers.append({
            "driver_id": driver_id,
            "curr_zone_id": zid,
            "curr_pt": [clng, clat],
            "dest_pt": None,
            "dest_zone_id": None,
        })
        driver_id += 1

    with open(args.output, "w") as f:
        json.dump(drivers, f, indent=2)

    print(f"Wrote {len(drivers)} drivers → {args.output}")


if __name__ == "__main__":
    main()
