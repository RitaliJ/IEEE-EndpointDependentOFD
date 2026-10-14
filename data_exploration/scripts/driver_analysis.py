"""
Find drivers present in both delivery_cq.csv and pickup_cq.csv,
then check: for pickup orders, does pickup_time fall within the
promised time window (time_window_start .. time_window_end)?

Run with: uv run python data/driver_analysis.py
"""

import pandas as pd

DELIVERY_PATH = "data/delivery/delivery_cq.csv"
PICKUP_PATH = "data/pickup/pickup_cq.csv"


def parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime("2000-" + series, format="%Y-%m-%d %H:%M:%S", errors="coerce")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
delivery = pd.read_csv(DELIVERY_PATH)
pickup = pd.read_csv(PICKUP_PATH)

# ---------------------------------------------------------------------------
# Find shared drivers
# ---------------------------------------------------------------------------
delivery_drivers = set(delivery["courier_id"].unique())
pickup_drivers = set(pickup["courier_id"].unique())
shared = delivery_drivers & pickup_drivers

print(f"Drivers in delivery_cq : {len(delivery_drivers):,}")
print(f"Drivers in pickup_cq   : {len(pickup_drivers):,}")
print(f"Shared drivers         : {len(shared):,}")

# Work only with shared drivers
pickup_shared = pickup[pickup["courier_id"].isin(shared)].copy()
print(f"\nPickup orders from shared drivers: {len(pickup_shared):,}")

# ---------------------------------------------------------------------------
# Parse timestamps
# ---------------------------------------------------------------------------
pickup_shared["pickup_dt"]  = parse_ts(pickup_shared["pickup_time"])
pickup_shared["window_start"] = parse_ts(pickup_shared["time_window_start"])
pickup_shared["window_end"]   = parse_ts(pickup_shared["time_window_end"])

# Drop rows with any parse failure
before = len(pickup_shared)
pickup_shared = pickup_shared.dropna(subset=["pickup_dt", "window_start", "window_end"])
print(f"Rows dropped due to timestamp parse errors: {before - len(pickup_shared):,}")

# ---------------------------------------------------------------------------
# On-time check
# ---------------------------------------------------------------------------
pickup_shared["on_time"] = (
    (pickup_shared["pickup_dt"] >= pickup_shared["window_start"]) &
    (pickup_shared["pickup_dt"] <= pickup_shared["window_end"])
)
pickup_shared["early"] = pickup_shared["pickup_dt"] < pickup_shared["window_start"]
pickup_shared["late"]  = pickup_shared["pickup_dt"] > pickup_shared["window_end"]

n_total   = len(pickup_shared)
n_on_time = pickup_shared["on_time"].sum()
n_early   = pickup_shared["early"].sum()
n_late    = pickup_shared["late"].sum()

print(f"\n=== On-Time Analysis (shared drivers) ===")
print(f"Total orders  : {n_total:,}")
print(f"On time       : {n_on_time:,}  ({100*n_on_time/n_total:.1f}%)")
print(f"Early         : {n_early:,}  ({100*n_early/n_total:.1f}%)")
print(f"Late          : {n_late:,}  ({100*n_late/n_total:.1f}%)")

# ---------------------------------------------------------------------------
# Per-driver breakdown (pick one driver to show detail)
# ---------------------------------------------------------------------------
per_driver = pickup_shared.groupby("courier_id").agg(
    orders=("order_id", "count"),
    on_time=("on_time", "sum"),
    early=("early", "sum"),
    late=("late", "sum"),
)
per_driver["on_time_pct"] = 100 * per_driver["on_time"] / per_driver["orders"]
per_driver = per_driver.sort_values("orders", ascending=False)

print(f"\n=== Per-Driver Summary (top 10 by order count) ===")
print(per_driver.head(10).to_string())

# Pick the busiest shared driver and show their orders
sample_driver = per_driver.index[0]
sample_orders = pickup_shared[pickup_shared["courier_id"] == sample_driver][
    ["order_id", "accept_time", "time_window_start", "time_window_end", "pickup_time", "on_time", "early", "late"]
].head(20)

print(f"\n=== Sample orders for driver {sample_driver} ===")
print(sample_orders.to_string(index=False))

# ---------------------------------------------------------------------------
# Lateness distribution (for late pickups)
# ---------------------------------------------------------------------------
late_orders = pickup_shared[pickup_shared["late"]].copy()
if len(late_orders):
    late_orders["minutes_late"] = (
        (late_orders["pickup_dt"] - late_orders["window_end"]).dt.total_seconds() / 60
    )
    q = late_orders["minutes_late"]
    print(f"\n=== Lateness Distribution (minutes past window_end) ===")
    print(f"  p25 : {q.quantile(0.25):.1f} min")
    print(f"  p50 : {q.quantile(0.50):.1f} min")
    print(f"  p75 : {q.quantile(0.75):.1f} min")
    print(f"  p95 : {q.quantile(0.95):.1f} min")
    print(f"  max : {q.max():.1f} min")

# ---------------------------------------------------------------------------
# Earliness distribution (for early pickups)
# ---------------------------------------------------------------------------
early_orders = pickup_shared[pickup_shared["early"]].copy()
if len(early_orders):
    early_orders["minutes_early"] = (
        (early_orders["window_start"] - early_orders["pickup_dt"]).dt.total_seconds() / 60
    )
    q = early_orders["minutes_early"]
    print(f"\n=== Earliness Distribution (minutes before window_start) ===")
    print(f"  p25 : {q.quantile(0.25):.1f} min")
    print(f"  p50 : {q.quantile(0.50):.1f} min")
    print(f"  p75 : {q.quantile(0.75):.1f} min")
    print(f"  p95 : {q.quantile(0.95):.1f} min")
    print(f"  max : {q.max():.1f} min")
