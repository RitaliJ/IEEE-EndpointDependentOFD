"""
Exploratory analysis of delivery_cq.csv to assess fitness for the delivery
dispatch simulator.  Run with: uv run python data/analysis.py

Sections
--------
1. Load & Basic Overview
2. Data Quality
3. Column Mapping to Simulator Model
4. Temporal Patterns  (busy / off-peak hours)
5. Spatial / Zone Structure
6. Ratio Analysis  (drivers : restaurants : zones)
7. Batching Detection
8. Driver Route Analysis
9. Model Fitness Summary
"""

import math

import numpy as np
import pandas as pd

DATA_PATH = "data/delivery/delivery_cq_rounded.csv"
OUTPUT_PATH = "data/analysis_cq.md"

lines: list[str] = []


def out(text: str = "") -> None:
    lines.append(text)


def section(title: str) -> None:
    out()
    out(f"## {title}")
    out()


def code_block(text: str) -> None:
    out("```")
    out(text)
    out("```")


# ---------------------------------------------------------------------------
# 1. Load & Basic Overview
# ---------------------------------------------------------------------------
out("# Delivery CQ — Exploratory Analysis")
out()
section("1. Load & Basic Overview")

df = pd.read_csv(DATA_PATH)
out(f"**Shape:** {df.shape[0]:,} rows × {df.shape[1]} columns")
out()
out(f"**Columns:** {list(df.columns)}")
out()

rows = ["| Column | Unique | Nulls |", "| --- | --- | --- |"]
for col in df.columns:
    rows.append(f"| `{col}` | {df[col].nunique():,} | {df[col].isna().sum():,} |")
out("\n".join(rows))

# ---------------------------------------------------------------------------
# 2. Data Quality
# ---------------------------------------------------------------------------
section("2. Data Quality")


def parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime("2000-" + series, format="%Y-%m-%d %H:%M:%S", errors="coerce")


df["accept_dt"] = parse_ts(df["accept_time"])
df["delivery_dt"] = parse_ts(df["delivery_time"])

n_parse_err = df["accept_dt"].isna().sum() + df["delivery_dt"].isna().sum()
out(f"- Timestamp parse errors: **{n_parse_err:,}**")

df["duration_min"] = (df["delivery_dt"] - df["accept_dt"]).dt.total_seconds() / 60
cross_day = df["duration_min"] < 0
df.loc[cross_day, "duration_min"] += 24 * 60
out(f"- Cross-midnight deliveries corrected: **{cross_day.sum():,}**")

neg = (df["duration_min"] < 0).sum()
out(f"- Still-negative durations (data errors): **{neg:,}**")

out()
out("**Delivery duration distribution (minutes):**")
out()
rows = ["| Percentile | Minutes | Hours |", "| --- | --- | --- |"]
for label, q in [("min", 0.0), ("p5", 0.05), ("p25", 0.25), ("p50", 0.50),
                 ("p75", 0.75), ("p95", 0.95), ("max", 1.0)]:
    val = df["duration_min"].quantile(q)
    rows.append(f"| {label} | {val:.1f} | {val/60:.1f} |")
out("\n".join(rows))
out()

out(f"- Deliveries < 10 min (likely errors): **{(df['duration_min'] < 10).sum():,}**")
out(f"- Deliveries > 8 h (multi-day/outliers): **{(df['duration_min'] > 480).sum():,}**")
out(f"- Deliveries > 24 h: **{(df['duration_min'] > 1440).sum():,}**")


def haversine_km(lat1, lon1, lat2, lon2) -> float:  # noqa: ANN001
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


sample = df.sample(min(10_000, len(df)), random_state=42)
dists_accept = [
    haversine_km(r.lat, r.lng, r.accept_gps_lat, r.accept_gps_lng)
    for r in sample.itertuples()
    if all(pd.notna([r.lat, r.lng, r.accept_gps_lat, r.accept_gps_lng]))
]
dists_delivery = [
    haversine_km(r.lat, r.lng, r.delivery_gps_lat, r.delivery_gps_lng)
    for r in sample.itertuples()
    if all(pd.notna([r.lat, r.lng, r.delivery_gps_lat, r.delivery_gps_lng]))
]

out()
arr = np.array(dists_accept)
out(f"**Pickup → driver-at-accept distance (km, sample n={len(dists_accept):,}):** "
    f"median={np.median(arr):.2f}  p95={np.percentile(arr,95):.2f}  max={arr.max():.2f}")

arr2 = np.array(dists_delivery)
out(f"**Pickup → delivery distance (km, sample n={len(dists_delivery):,}):** "
    f"median={np.median(arr2):.2f}  p95={np.percentile(arr2,95):.2f}  max={arr2.max():.2f}")

# ---------------------------------------------------------------------------
# 3. Column Mapping to Simulator Model
# ---------------------------------------------------------------------------
section("3. Column Mapping to Simulator Model")

out("| CSV Column | Simulator Field |")
out("| --- | --- |")
out("| `courier_id` | `Driver.driver_id` |")
out("| `region_id` | `Zone.zone_id` (48 unique regions) |")
out("| `aoi_id` | `Restaurant.restaurant_id` (pickup point) |")
out("| `aoi_type` | type of pickup point |")
out("| `lng` / `lat` | `Restaurant.location` / `Order.source_location` |")
out("| `accept_gps_lng/lat` | `Driver.location` at time of assignment |")
out("| `delivery_gps_lng/lat` | `Order.destination_location` |")
out("| `accept_time` | `Order.arrival_time` (no separate prep_time) |")
out("| `delivery_time` | `Order.completion_time` |")
out()
out("**Missing from dataset:**")
out("- `Order.prep_time` (no restaurant queue / ready time recorded)")
out("- `Order.profit`")
out("- `Driver.status` transitions within a shift")
out()
out("**`aoi_type` value counts (top 10):**")
out()
top_aoi = df["aoi_type"].value_counts().head(10)
rows = ["| aoi_type | Count |", "| --- | --- |"]
for k, v in top_aoi.items():
    rows.append(f"| {k} | {v:,} |")
out("\n".join(rows))
out()
out("> `aoi_type=1` and `aoi_type=14` dominate; unclear if these map to different "
    "merchant categories (e.g., restaurants vs. retail).")

# ---------------------------------------------------------------------------
# 4. Temporal Patterns
# ---------------------------------------------------------------------------
section("4. Temporal Patterns (Busy / Off-Peak Hours)")

df["accept_hour"] = df["accept_dt"].dt.hour
df["delivery_hour"] = df["delivery_dt"].dt.hour

out("**Order volume by hour of acceptance (all dates):**")
out()
hourly = df["accept_hour"].value_counts().sort_index()
total = hourly.sum()

buf = []
for h, cnt in hourly.items():
    bar = "█" * int(30 * cnt / hourly.max())
    buf.append(f"  {h:02d}:00  {cnt:>7,} ({100*cnt/total:4.1f}%)  {bar}")
code_block("\n".join(buf))

peak_hours = hourly[hourly >= hourly.quantile(0.75)].index.tolist()
offpeak_hours = hourly[hourly <= hourly.quantile(0.25)].index.tolist()
out(f"- **Peak hours** (top quartile by volume): {sorted(peak_hours)}")
out(f"- **Off-peak hours** (bottom quartile): {sorted(offpeak_hours)}")

out()
dates = sorted(df["ds"].unique())
vc = df["ds"].value_counts()
out(f"**Unique dates in dataset:** {len(dates)}  "
    f"({dates[0]} … {dates[-1]})")
out(f"- Orders per date: min={vc.min():,}  mean={vc.mean():.0f}  max={vc.max():,}")

# ---------------------------------------------------------------------------
# 5. Spatial / Zone Structure
# ---------------------------------------------------------------------------
section("5. Spatial / Zone Structure")

out(f"- Unique regions (zones): **{df['region_id'].nunique()}**")
out(f"- Unique aoi_ids (pickup points / restaurants): **{df['aoi_id'].nunique():,}**")

per_region = df.groupby("region_id").agg(
    orders=("order_id", "count"),
    couriers=("courier_id", "nunique"),
    aois=("aoi_id", "nunique"),
).sort_values("orders", ascending=False)

out()
out("**Top 10 regions by order volume:**")
out()
rows = ["| region_id | orders | couriers | aois |", "| --- | --- | --- | --- |"]
for rid, row in per_region.head(10).iterrows():
    rows.append(f"| {rid} | {row['orders']:,} | {row['couriers']} | {row['aois']} |")
out("\n".join(rows))
out()

out(f"- AOIs per region: min={per_region['aois'].min()}  "
    f"median={per_region['aois'].median():.0f}  max={per_region['aois'].max()}")
out(f"- Couriers per region: min={per_region['couriers'].min()}  "
    f"median={per_region['couriers'].median():.0f}  max={per_region['couriers'].max()}")

out()
out("**Geographic bounding box:**")
out(f"- lat: [{df['lat'].min():.4f}, {df['lat'].max():.4f}]")
out(f"- lng: [{df['lng'].min():.4f}, {df['lng'].max():.4f}]")

# ---------------------------------------------------------------------------
# 6. Ratio Analysis
# ---------------------------------------------------------------------------
section("6. Ratio Analysis (Drivers : Restaurants : Zones)")

n_drivers = df["courier_id"].nunique()
n_restaurants = df["aoi_id"].nunique()
n_zones = df["region_id"].nunique()

out("**Global ratios:**")
out()
out(f"| Entity | Count | Per Zone |")
out(f"| --- | --- | --- |")
out(f"| Drivers | {n_drivers:,} | — |")
out(f"| Restaurants | {n_restaurants:,} | {n_restaurants/n_zones:.0f} |")
out(f"| Zones | {n_zones:,} | — |")
out()
out(f"Ratio drivers:restaurants:zones = **1 : {n_restaurants/n_drivers:.1f} : {n_zones/n_drivers:.3f}**")

top_region = per_region["orders"].idxmax()
reg = df[df["region_id"] == top_region]
out()
out(f"**Largest region (region_id={top_region}):**")
out(f"- Orders: {len(reg):,}")
out(f"- Drivers: {reg['courier_id'].nunique()}")
out(f"- Restaurants: {reg['aoi_id'].nunique()}")
out(f"- Drivers:aois ratio = 1 : {reg['aoi_id'].nunique() / reg['courier_id'].nunique():.1f}")

# ---------------------------------------------------------------------------
# 7. Batching Detection
# ---------------------------------------------------------------------------
section("7. Batching Detection")

df_sorted = df.sort_values(["courier_id", "ds", "accept_dt"]).copy()

batched_pairs = 0
batched_couriers: set = set()
total_pairs = 0
wait_before_pickup: list[float] = []

for (courier, day), grp in df_sorted.groupby(["courier_id", "ds"]):
    accepts = grp["accept_dt"].values
    deliveries = grp["delivery_dt"].values
    for i in range(len(grp) - 1):
        total_pairs += 1
        gap = (pd.Timestamp(accepts[i + 1]) - pd.Timestamp(accepts[i])).total_seconds() / 60
        wait_before_pickup.append(gap)
        if pd.Timestamp(accepts[i + 1]) < pd.Timestamp(deliveries[i]):
            batched_pairs += 1
            batched_couriers.add(courier)

batch_rate = batched_pairs / total_pairs if total_pairs else 0
out(f"- Total consecutive-order pairs analysed: **{total_pairs:,}**")
out(f"- Pairs where next accept < previous delivery: **{batched_pairs:,}**")
out(f"- Batching rate: **{batch_rate:.1%}**")
out(f"- Couriers observed batching at least once: **{len(batched_couriers):,} / {n_drivers:,}**")

gaps = np.array(wait_before_pickup)
out()
out("**Time between consecutive order acceptances (same courier, same day):**")
out()
rows = ["| Percentile | Minutes |", "| --- | --- |"]
for label, q in [("p5", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95)]:
    rows.append(f"| {label} | {np.percentile(gaps, q):.1f} |")
out("\n".join(rows))

# ---------------------------------------------------------------------------
# 8. Driver Route Analysis
# ---------------------------------------------------------------------------
section("8. Driver Route Analysis")

orders_per_courier = df.groupby("courier_id")["order_id"].count()
out("**Orders per courier (career total):**")
out()
rows = ["| Percentile | Orders |", "| --- | --- |"]
for label, q in [("min", 0.0), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("max", 1.0)]:
    rows.append(f"| {label} | {orders_per_courier.quantile(q):.0f} |")
out("\n".join(rows))

orders_per_courier_day = df.groupby(["courier_id", "ds"])["order_id"].count()
out()
out("**Orders per courier per day:**")
out()
rows = ["| Percentile | Orders |", "| --- | --- |"]
for label, q in [("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p95", 0.95)]:
    rows.append(f"| {label} | {orders_per_courier_day.quantile(q):.0f} |")
out("\n".join(rows))

sample2 = df.sample(min(20_000, len(df)), random_state=0)
route_km = [
    haversine_km(r.lat, r.lng, r.delivery_gps_lat, r.delivery_gps_lng)
    for r in sample2.itertuples()
    if all(pd.notna([r.lat, r.lng, r.delivery_gps_lat, r.delivery_gps_lng]))
]
arr3 = np.array(route_km)
out()
out(f"**Pickup-to-delivery straight-line distance (km, sample n={len(arr3):,}):**")
out()
rows = ["| Percentile | km |", "| --- | --- |"]
for label, q in [("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95)]:
    rows.append(f"| {label} | {np.percentile(arr3, q):.2f} |")
out("\n".join(rows))

revisit_counts = df.groupby(["courier_id", "ds", "aoi_id"])["order_id"].count()
multi = (revisit_counts > 1).sum()
out()
out(f"- Courier×day×aoi groups with >1 order (revisits / multi-pickup): **{multi:,}**")
out(f"  ({100*multi/len(revisit_counts):.1f}% of all courier×day×aoi combos)")

# ---------------------------------------------------------------------------
# 9. Model Fitness Summary
# ---------------------------------------------------------------------------
section("9. Model Fitness Summary")

out("### Fits the Simulator Model")
out()
out("- Spatial coordinates for source, destination, and driver positions map directly to the new location fields.")
out("- `region_id` → zone provides a natural zone hierarchy (48 zones).")
out("- `aoi_id` → restaurant gives pickup-point identity.")
out("- Hourly order volume shows clear peak / off-peak structure usable to calibrate arrival rate λ per hour.")
out("- Batching signal is present: many couriers accepted a new order before completing the previous one.")
out("- `accept_gps` captures driver location at assignment — can initialise `Driver.location` and validate GreedyNearest cost.")

out()
out("### Gaps / Concerns")
out()
out("- **No prep_time.** `accept_time` appears to be when the courier accepted the job, not when the order was placed or ready. A prep_time distribution must be assumed or sampled.")
out("- **Very long delivery durations** (median ~3 h, p95 ~28 h). This is consistent with general-goods courier delivery, not food delivery. Consider whether the time scale matches simulation parameters, or whether durations should be rescaled / filtered.")
out("- **No explicit order-ready event.** The queue wait between `accept_time` and actual pickup is unobservable unless trajectory data (`courier_detailed_trajectory.zip`) is used.")
out("- **Restaurant count is very high** (17 k AOIs across 48 zones, ~360 per zone). If the simulator uses a small number of restaurants per zone, filter to a single region or cluster AOIs by proximity.")
out("- **`aoi_type` semantics are unknown.** Type-1 (66%) and type-14 (21%) dominate; unclear whether all types represent food merchants.")

out()
out("### Recommended Next Steps")
out()
out("1. Filter to a single region (e.g., top-volume region) to reduce AOI count to a manageable range.")
out("2. Inspect `courier_detailed_trajectory.zip` to see if in-route GPS traces reveal when couriers actually arrived at pickup (proxy for order ready time).")
out("3. Decide on a prep_time model (fixed constant or fitted distribution) to fill the missing field.")
out("4. Check whether `delivery_five_cities.csv` or `delivery_jl.csv` contain additional cities that could serve as out-of-sample validation sets.")

# ---------------------------------------------------------------------------
# 10. GPS Coverage per AOI
# ---------------------------------------------------------------------------
section("10. GPS Coverage per AOI")

# --- AOI count per courier ---
aoi_per_courier = df.groupby("courier_id")["aoi_id"].nunique()
out("### AOI count per courier")
out()
out("| Stat | Value |")
out("| --- | --- |")
out(f"| min | {aoi_per_courier.min():,} |")
out(f"| max | {aoi_per_courier.max():,} |")
out(f"| avg | {aoi_per_courier.mean():.2f} |")
out()
out("Each courier serves between "
    f"{aoi_per_courier.min()} and {aoi_per_courier.max():,} "
    f"distinct AOIs over the dataset, averaging ~{aoi_per_courier.mean():.0f}.")

# --- Unique accept GPS pairs per aoi_id ---
accept_per_aoi = (
    df.groupby("aoi_id")[["accept_gps_lng", "accept_gps_lat"]]
    .apply(lambda x: x.drop_duplicates().shape[0])
    .rename("unique_accept_pairs")
)
out()
out("### Unique accept GPS pairs per aoi_id")
out()
out("| Stat | Unique accept pairs |")
out("| --- | --- |")
out(f"| min | {accept_per_aoi.min():,} |")
out(f"| p25 | {accept_per_aoi.quantile(0.25):.0f} |")
out(f"| median | {accept_per_aoi.median():.0f} |")
out(f"| p75 | {accept_per_aoi.quantile(0.75):.0f} |")
out(f"| max | {accept_per_aoi.max():,} |")
out(f"| mean | {accept_per_aoi.mean():.2f} |")
out()
out("**Top 15 AOIs by unique accept GPS pairs:**")
out()
rows = ["| aoi_id | unique accept pairs |", "| --- | --- |"]
for aoi_id, val in accept_per_aoi.sort_values(ascending=False).head(15).items():
    rows.append(f"| {aoi_id} | {val:,} |")
out("\n".join(rows))
out()
out("> High accept-pair counts suggest busy AOIs where couriers are spread across many "
    "pickup positions, or GPS jitter across many orders at the same location.")

# --- Unique delivery GPS pairs per aoi_id ---
delivery_per_aoi = (
    df.groupby("aoi_id")[["delivery_gps_lng", "delivery_gps_lat"]]
    .apply(lambda x: x.drop_duplicates().shape[0])
    .rename("unique_delivery_pairs")
)
out()
out("### Unique delivery GPS pairs per aoi_id")
out()
out("| Stat | Unique delivery pairs |")
out("| --- | --- |")
out(f"| min | {delivery_per_aoi.min():,} |")
out(f"| p25 | {delivery_per_aoi.quantile(0.25):.0f} |")
out(f"| median | {delivery_per_aoi.median():.0f} |")
out(f"| p75 | {delivery_per_aoi.quantile(0.75):.0f} |")
out(f"| max | {delivery_per_aoi.max():,} |")
out(f"| mean | {delivery_per_aoi.mean():.2f} |")
out()
out("**Top 15 AOIs by unique delivery GPS pairs:**")
out()
rows = ["| aoi_id | unique delivery pairs |", "| --- | --- |"]
for aoi_id, val in delivery_per_aoi.sort_values(ascending=False).head(15).items():
    rows.append(f"| {aoi_id} | {val:,} |")
out("\n".join(rows))
out()
out("> Delivery pairs spread far wider than accept pairs — consistent with one pickup "
    "location fanning out to many distinct customer addresses.")

# --- Unique couriers per aoi_id ---
couriers_per_aoi = df.groupby("aoi_id")["courier_id"].nunique().rename("unique_couriers")
out()
out("### Unique couriers per aoi_id")
out()
out("| Stat | Unique couriers |")
out("| --- | --- |")
out(f"| min | {couriers_per_aoi.min():,} |")
out(f"| p25 | {couriers_per_aoi.quantile(0.25):.0f} |")
out(f"| median | {couriers_per_aoi.median():.0f} |")
out(f"| p75 | {couriers_per_aoi.quantile(0.75):.0f} |")
out(f"| max | {couriers_per_aoi.max():,} |")
out(f"| mean | {couriers_per_aoi.mean():.2f} |")
out()
out("**Top 15 AOIs by unique couriers:**")
out()
rows = ["| aoi_id | unique couriers |", "| --- | --- |"]
for aoi_id, val in couriers_per_aoi.sort_values(ascending=False).head(15).items():
    rows.append(f"| {aoi_id} | {val:,} |")
out("\n".join(rows))

# ---------------------------------------------------------------------------
# 11. Inter-Accept Time Analysis (within active delivery windows)
# ---------------------------------------------------------------------------
section("11. Inter-Accept Time Analysis")

out("For each courier, the gap between accept[i] and accept[i+1] is included **only** "
    "if accept[i+1] occurs before delivery[i] — i.e. the courier accepted a new order "
    "while the previous one was still undelivered. Gaps between a delivery and the next "
    "accept (idle time) are excluded.")
out()

inter_accept_gaps: list[float] = []
all_gaps_by_courier: dict = {}

for (courier, day), grp in df_sorted.groupby(["courier_id", "ds"]):
    accepts = grp["accept_dt"].values
    deliveries = grp["delivery_dt"].values
    for i in range(len(accepts) - 1):
        # Only count if the next accept is before the current delivery
        if pd.Timestamp(accepts[i + 1]) >= pd.Timestamp(deliveries[i]):
            continue
        gap = (pd.Timestamp(accepts[i + 1]) - pd.Timestamp(accepts[i])).total_seconds() / 60
        if 0 <= gap <= 1440:
            inter_accept_gaps.append(gap)
            all_gaps_by_courier.setdefault(courier, []).append(gap)

gaps = np.array(inter_accept_gaps)
courier_means = np.array([np.mean(v) for v in all_gaps_by_courier.values()])

out("**Distribution of time between consecutive accepts (while previous order still undelivered):**")
out()
rows = ["| Percentile | Minutes |", "| --- | --- |"]
for label, q in [("min", 0), ("p5", 5), ("p25", 25), ("p50", 50),
                 ("p75", 75), ("p90", 90), ("p95", 95), ("max", 100)]:
    rows.append(f"| {label} | {np.percentile(gaps, q):.1f} |")
out("\n".join(rows))
out()
out(f"- Total gaps analysed: **{len(gaps):,}**")
out(f"- Gaps < 5 min: **{(gaps < 5).sum():,}** ({100*(gaps < 5).mean():.1f}%)")
out(f"- Gaps 5–30 min: **{((gaps >= 5) & (gaps < 30)).sum():,}** ({100*((gaps >= 5) & (gaps < 30)).mean():.1f}%)")
out(f"- Gaps 30–60 min: **{((gaps >= 30) & (gaps < 60)).sum():,}** ({100*((gaps >= 30) & (gaps < 60)).mean():.1f}%)")
out(f"- Gaps > 60 min: **{(gaps >= 60).sum():,}** ({100*(gaps >= 60).mean():.1f}%)")

out()
out("**Per-courier mean inter-accept gap (minutes, couriers with ≥1 qualifying gap):**")
out()
rows = ["| Percentile | Minutes |", "| --- | --- |"]
for label, q in [("min", 0), ("p25", 25), ("p50", 50), ("p75", 75), ("max", 100)]:
    rows.append(f"| {label} | {np.percentile(courier_means, q):.1f} |")
out("\n".join(rows))
out()
out(f"- Couriers with at least one qualifying gap: **{len(courier_means):,}**")
out(f"- Couriers with mean gap < 5 min: **{(courier_means < 5).sum():,}**")
out(f"- Couriers with mean gap > 30 min: **{(courier_means > 30).sum():,}**")

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------
with open(OUTPUT_PATH, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Analysis written to {OUTPUT_PATH}")
