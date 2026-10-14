"""A Scenario is everything that must be held identical across policies.

The comparison in the paper is only meaningful if every policy sees the same
world: the same orders arriving at the same times, the same drivers starting in
the same places, the same horizon, and the same service-cost parameters. Before
this module those things were regenerated inside each policy's run from a shared,
advancing RNG, so every policy silently got a different realisation.

A Scenario is built once per (city, experiment_seed), serialised, hashed, and
replayed unchanged for every policy. Nothing in a policy run may draw from the
scenario RNG.

Layout of responsibilities:
    build_scenario()   generate the order trace + driver roster exactly once
    Scenario.save()    persist it next to the results, with hashes
    roster_prefix()    nested driver subsets for the supply sweep
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
from dataclasses import dataclass, asdict, field

import numpy as np

# The canonical data subset. ds is formatted MMDD; "0610" (June 10) is the single
# day that reproduces Table I of the paper exactly for all five cities:
#     cq 4088 orders / 348 restaurants / 316 couriers
#     hz 8225 / 449 / 349      jl 213 / 82 / 11
#     sh 6115 / 406 / 461      yt 1051 / 278 / 99
CANONICAL_DAY: str = "0610"

# Rounding applied to pickup coordinates before they are treated as distinct
# restaurants. The raw feed obfuscates GPS by up to 10m; 4 decimal places (~11m)
# collapses that jitter so one physical restaurant is one restaurant.
GPS_DECIMAL_PLACES: int = 4

# Poisson arrival rate per restaurant (paper section V.B: lambda = 1).
ARRIVAL_RATE: float = 1.0

# Buchanan-Hamilton-Beardwood constant for 2-D Euclidean tours; c(j) = beta*sqrt(A_j).
BHH_CONSTANT: float = 0.714

# Exponent alpha in tau(i,j,k) = D[z(i),j] + c(j)*k**alpha. BHH gives 1/2, which
# satisfies the paper's requirement that 0 < alpha < 1.
BATCH_ALPHA: float = 0.5

# Discard the first 5% of each generated trace's arrival horizon. A fraction
# scales across cities and seeds whose horizons differ substantially.
WARMUP_FRACTION: float = 0.05

# km per degree at the equator, used for the local equirectangular projection that
# turns lng/lat spreads into an area in km^2.
_KM_PER_DEG_LAT: float = 110.574
_KM_PER_DEG_LNG: float = 111.320


# ----------------------------------------------------------------------------
# Cost parameters
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class CostParams:
    """Every parameter of the service-time model, recorded with each run.

    The simulator and any policy that scores candidate batches must read the batch
    cost from the same place, so that a policy cannot optimise a different
    objective than the one it is measured against.
    """
    cost_function: str                    # class name in cost_functions.travel_time
    batch_alpha: float                    # alpha in c(j) * k**alpha
    bhh_constant: float                   # beta in c(j) = beta * sqrt(A_j)
    speed_km_per_min: float               # divisor turning haversine km into minutes
    zone_area_estimator: str              # how A_j was estimated
    zone_areas_km2: dict[int, float]      # A_j by 1-based zone id
    zone_scale: dict[int, float]          # c(j) in minutes, by 1-based zone id
    matrix_diagonal: float                # D[j][j] as written by cost_maker

    def to_json(self) -> dict:
        d = asdict(self)
        # JSON object keys must be strings; keep them sorted numerically for diffing.
        d["zone_areas_km2"] = {str(k): v for k, v in sorted(self.zone_areas_km2.items())}
        d["zone_scale"] = {str(k): v for k, v in sorted(self.zone_scale.items())}
        return d


def compute_zone_areas(
    orders: list[dict],
    zones: dict,
) -> tuple[dict[int, float], str]:
    """Estimate each zone's service area in km^2 from the destinations routed to it.

    c(j) models the within-zone work of serving k destinations in zone j, so the
    relevant area is the spread of *destinations* assigned to j, not the spread of
    the pickup points that originally defined the cluster.

    Uses the bounding box of the destinations under a local equirectangular
    projection. Zones with fewer than two distinct destinations have no measurable
    spread; they inherit the median positive area so that c(j) is never zero (a
    zero would make batching free in that zone).
    """
    by_zone: dict[int, list[tuple[float, float]]] = {}
    for o in orders:
        by_zone.setdefault(int(o["destination_zone_id"]), []).append(
            (float(o["destination"][0]), float(o["destination"][1]))
        )

    areas: dict[int, float] = {}
    for zid, pts in by_zone.items():
        if len(pts) < 2:
            areas[zid] = 0.0
            continue
        lat0 = sum(p[1] for p in pts) / len(pts)
        km_per_deg_lng = _KM_PER_DEG_LNG * math.cos(math.radians(lat0))
        xs = [p[0] * km_per_deg_lng for p in pts]
        ys = [p[1] * _KM_PER_DEG_LAT for p in pts]
        areas[zid] = (max(xs) - min(xs)) * (max(ys) - min(ys))

    positive = sorted(a for a in areas.values() if a > 0.0)
    fallback = positive[len(positive) // 2] if positive else 1.0

    # Every zone in the layout needs an entry, including zones that received no
    # orders in this subset -- a policy may still route a driver there.
    for zid_str in zones:
        areas.setdefault(int(zid_str), 0.0)
    for zid, a in areas.items():
        if a <= 0.0:
            areas[zid] = fallback

    return areas, "destination_bounding_box_km2"


def build_cost_params(
    orders: list[dict],
    zones: dict,
    cost_matrix: list[list[float]],
    cost_function: str,
    speed_km_per_min: float,
    batch_alpha: float = BATCH_ALPHA,
    bhh_constant: float = BHH_CONSTANT,
) -> CostParams:
    if not 0.0 < batch_alpha < 1.0:
        raise ValueError(f"batch_alpha must be strictly between 0 and 1, got {batch_alpha}")
    if speed_km_per_min <= 0.0:
        raise ValueError(f"speed_km_per_min must be positive, got {speed_km_per_min}")
    areas, estimator = compute_zone_areas(orders, zones)
    # c(j) = beta * sqrt(A_j) km, converted to minutes by the same speed used for D.
    scale = {zid: bhh_constant * math.sqrt(a) / speed_km_per_min for zid, a in areas.items()}
    diagonal = cost_matrix[0][0] if cost_matrix else float("nan")
    return CostParams(
        cost_function=cost_function,
        batch_alpha=batch_alpha,
        bhh_constant=bhh_constant,
        speed_km_per_min=speed_km_per_min,
        zone_area_estimator=estimator,
        zone_areas_km2=areas,
        zone_scale=scale,
        matrix_diagonal=diagonal,
    )


# ----------------------------------------------------------------------------
# Scenario
# ----------------------------------------------------------------------------

@dataclass
class Scenario:
    """One fixed realisation of the world, replayed identically by every policy."""
    city: str
    data_day: str
    experiment_seed: int
    roster_seed: int
    arrival_rate: float
    warmup_duration: float
    horizon: float
    orders: list[dict]        # order_id, restaurant_id, destination_zone_id, destination, arrival_time
    roster: list[dict]        # driver_id, curr_zone_id, curr_pt -- already shuffled
    cost_params: CostParams
    warmup_fraction: float | None = None
    trace_hash: str = ""
    roster_hash: str = ""

    def manifest(self) -> dict:
        """The identity of this scenario, small enough to embed in every result."""
        return {
            "city": self.city,
            "data_day": self.data_day,
            "experiment_seed": self.experiment_seed,
            "roster_seed": self.roster_seed,
            "arrival_rate": self.arrival_rate,
            "warmup_duration": self.warmup_duration,
            "warmup_fraction": self.warmup_fraction,
            "horizon": self.horizon,
            "num_orders": len(self.orders),
            "num_drivers_full_roster": len(self.roster),
            "trace_hash": self.trace_hash,
            "roster_hash": self.roster_hash,
            "cost_params": self.cost_params.to_json(),
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(
                {
                    "manifest": self.manifest(),
                    "orders": self.orders,
                    "roster": self.roster,
                },
                f,
                indent=2,
            )

    @classmethod
    def load(cls, path: str) -> "Scenario":
        with open(path) as f:
            payload = json.load(f)
        m = payload["manifest"]
        cp = m["cost_params"]
        cost_params = CostParams(
            cost_function=cp["cost_function"],
            batch_alpha=cp["batch_alpha"],
            bhh_constant=cp["bhh_constant"],
            speed_km_per_min=cp["speed_km_per_min"],
            zone_area_estimator=cp["zone_area_estimator"],
            zone_areas_km2={int(k): v for k, v in cp["zone_areas_km2"].items()},
            zone_scale={int(k): v for k, v in cp["zone_scale"].items()},
            matrix_diagonal=cp["matrix_diagonal"],
        )
        return cls(
            city=m["city"],
            data_day=m["data_day"],
            experiment_seed=m["experiment_seed"],
            roster_seed=m["roster_seed"],
            arrival_rate=m["arrival_rate"],
            warmup_duration=m["warmup_duration"],
            horizon=m["horizon"],
            orders=payload["orders"],
            roster=payload["roster"],
            cost_params=cost_params,
            warmup_fraction=m.get("warmup_fraction"),
            trace_hash=m["trace_hash"],
            roster_hash=m["roster_hash"],
        )


def _hash_rows(rows: list[tuple]) -> str:
    """Stable digest of a list of tuples, independent of Python's hash seed."""
    h = hashlib.sha256()
    for row in rows:
        h.update(repr(row).encode())
        h.update(b"\x00")
    return h.hexdigest()[:16]


def _restaurant_stream(experiment_seed: int, restaurant_id: int) -> np.random.Generator:
    """A numpy Generator dedicated to one restaurant's arrival process.

    Seeded from (experiment_seed, restaurant_id) rather than drawn sequentially
    from a shared RNG, so the trace does not depend on the order restaurants
    happen to be iterated in, and a restaurant's arrivals are stable even if the
    set of restaurants changes.
    """
    digest = hashlib.sha256(f"arrivals:{experiment_seed}:{restaurant_id}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def build_scenario(
    *,
    zones_path: str,
    orders_path: str,
    drivers_path: str,
    cost_matrix: list[list[float]],
    city: str,
    experiment_seed: int,
    roster_seed: int,
    data_day: str = CANONICAL_DAY,
    warmup_duration: float | None = None,
    warmup_fraction: float = WARMUP_FRACTION,
    arrival_rate: float = ARRIVAL_RATE,
    cost_function: str = "sublinear_intrazone",
    speed_km_per_min: float = 1.0,
    batch_alpha: float = BATCH_ALPHA,
    bhh_constant: float = BHH_CONSTANT,
) -> Scenario:
    """Generate the one order trace and driver roster for this (city, seed).

    Arrival times are synthetic (the dataset fixes which orders exist and their
    origin/destination, but not when they arrive): per restaurant, inter-arrival
    times are exponential with rate `arrival_rate`, cumulatively summed. This
    matches section V.B of the paper.
    """
    with open(zones_path) as f:
        zones = json.load(f)
    with open(orders_path) as f:
        orders_json: list[dict] = json.load(f)
    with open(drivers_path) as f:
        roster_json: list[dict] = json.load(f)

    # --- order trace, generated once ---
    by_restaurant: dict[int, list[dict]] = {}
    for o in orders_json:
        by_restaurant.setdefault(int(o["restaurant_id"]), []).append(o)

    orders: list[dict] = []
    horizon = 0.0
    for rest_id in sorted(by_restaurant):
        # Sort by order id before pairing orders with arrival times: otherwise the
        # trace depends on the row order of orders.json, and re-exporting the same
        # data in a different order would silently produce a different experiment.
        infos = sorted(by_restaurant[rest_id], key=lambda o: int(o["order_id"]))
        stream = _restaurant_stream(experiment_seed, rest_id)
        inter = stream.exponential(scale=1.0 / arrival_rate, size=len(infos))
        timings = np.cumsum(inter).tolist()
        for info, t in zip(infos, timings):
            orders.append({
                "order_id": int(info["order_id"]),
                "restaurant_id": rest_id,
                "destination_zone_id": int(info["destination_zone_id"]),
                "destination": [float(info["destination"][0]), float(info["destination"][1])],
                "arrival_time": float(t),
            })
            horizon = max(horizon, t)

    orders.sort(key=lambda o: (o["arrival_time"], o["order_id"]))
    horizon = float(math.ceil(horizon))
    if warmup_duration is None:
        if not 0.0 <= warmup_fraction < 1.0:
            raise ValueError(f"warmup_fraction must be in [0, 1), got {warmup_fraction}")
        effective_warmup = warmup_fraction * horizon
        recorded_warmup_fraction: float | None = warmup_fraction
    else:
        if not 0.0 <= warmup_duration < horizon:
            raise ValueError(f"warmup_duration must be in [0, horizon), got {warmup_duration}")
        effective_warmup = warmup_duration
        recorded_warmup_fraction = None

    # --- driver roster, shuffled once so supply levels can be nested prefixes ---
    roster = [
        {
            "driver_id": int(d["driver_id"]),
            "curr_zone_id": int(d["curr_zone_id"]),
            "curr_pt": [float(d["curr_pt"][0]), float(d["curr_pt"][1])],
        }
        for d in roster_json
    ]
    roster.sort(key=lambda d: d["driver_id"])
    random.Random(roster_seed).shuffle(roster)

    cost_params = build_cost_params(
        orders=orders,
        zones=zones,
        cost_matrix=cost_matrix,
        cost_function=cost_function,
        speed_km_per_min=speed_km_per_min,
        batch_alpha=batch_alpha,
        bhh_constant=bhh_constant,
    )

    scenario = Scenario(
        city=city,
        data_day=data_day,
        experiment_seed=experiment_seed,
        roster_seed=roster_seed,
        arrival_rate=arrival_rate,
        warmup_duration=effective_warmup,
        horizon=horizon,
        orders=orders,
        roster=roster,
        cost_params=cost_params,
        warmup_fraction=recorded_warmup_fraction,
    )
    scenario.trace_hash = _hash_rows([
        (o["order_id"], o["restaurant_id"], o["destination_zone_id"],
         o["destination"][0], o["destination"][1], round(o["arrival_time"], 9))
        for o in orders
    ])
    scenario.roster_hash = _hash_rows([
        (d["driver_id"], d["curr_zone_id"], d["curr_pt"][0], d["curr_pt"][1])
        for d in roster
    ])
    return scenario


def roster_prefix(scenario: Scenario, fraction: float) -> list[dict]:
    """The nested driver subset for a supply level.

    Because the roster was shuffled once at scenario construction, taking prefixes
    guarantees D_10 subset D_25 subset ... subset D_100: raising supply only adds
    drivers, it never swaps out drivers that were already present.
    """
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction!r}")
    k = max(1, round(len(scenario.roster) * fraction))
    return scenario.roster[:k]


# ----------------------------------------------------------------------------
# Raw CSV preparation
# ----------------------------------------------------------------------------

def clean_and_filter_csv(src: str, dst: str, data_day: str = CANONICAL_DAY) -> dict:
    """Write the modelled subset of a raw city feed to `dst`.

    Three things happen here, all of which the downstream makers assume but none
    of which they do themselves:
      * rows outside `data_day` are dropped (the experiments model a single day);
      * rows whose pickup or delivery GPS is missing/NaN are dropped -- the raw
        feed has these and DBSCAN rejects them outright;
      * pickup coordinates are rounded to GPS_DECIMAL_PLACES so that the platform's
        up-to-10m obfuscation does not split one restaurant into several.

    Returns a summary suitable for the run manifest.
    """
    def finite(value: str) -> bool:
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    gps_fields = ("accept_gps_lng", "accept_gps_lat", "delivery_gps_lng", "delivery_gps_lat")
    total = kept = dropped_day = dropped_gps = 0

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(src, newline="") as f_in, open(dst, "w", newline="") as f_out:
        reader = csv.DictReader(f_in)
        writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            total += 1
            if row["ds"] != data_day:
                dropped_day += 1
                continue
            if not all(finite(row[k]) for k in gps_fields):
                dropped_gps += 1
                continue
            row["accept_gps_lng"] = round(float(row["accept_gps_lng"]), GPS_DECIMAL_PLACES)
            row["accept_gps_lat"] = round(float(row["accept_gps_lat"]), GPS_DECIMAL_PLACES)
            writer.writerow(row)
            kept += 1

    if kept == 0:
        raise SystemExit(f"No usable rows for ds={data_day} in {src}")

    return {
        "source_csv": os.path.abspath(src),
        "data_day": data_day,
        "rows_total": total,
        "rows_kept": kept,
        "rows_dropped_other_day": dropped_day,
        "rows_dropped_bad_gps": dropped_gps,
        "gps_decimal_places": GPS_DECIMAL_PLACES,
    }
