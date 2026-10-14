"""
Visual timeline of 10 couriers from the busiest depot on Oct 26.
Run: uv run python data/courier_timeline.py
"""

import random
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

random.seed(42)

df = pd.read_csv("data/delivery/delivery_cq_rounded_oct_busiest.csv")

# Busiest depot
chosen_lat, chosen_lng = 29.543, 106.483

couriers_at_loc = df[
    (df["accept_gps_lat"] == chosen_lat) & (df["accept_gps_lng"] == chosen_lng)
]["courier_id"].unique()

sampled = random.sample(list(couriers_at_loc), 10)
orders = df[df["courier_id"].isin(sampled)].copy()

def parse_hours(s):
    """Return fractional hours since midnight from 'MM-DD HH:MM:SS'."""
    dt = pd.to_datetime("2000-" + s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    return dt.hour + dt.minute / 60 + dt.second / 3600

orders["accept_h"]   = orders["accept_time"].apply(parse_hours)
orders["delivery_h"] = orders["delivery_time"].apply(parse_hours)

# Fix cross-midnight deliveries
mask = orders["delivery_h"] < orders["accept_h"]
orders.loc[mask, "delivery_h"] += 24

t_min, t_max = 7, 24

fig, ax = plt.subplots(figsize=(16, 8))

colors = plt.cm.tab10.colors
courier_order = sorted(sampled)

for i, cid in enumerate(courier_order):
    rows = orders[orders["courier_id"] == cid].copy()
    y = i

    for _, r in rows.iterrows():
        a = r["accept_h"]
        d = r["delivery_h"]
        if pd.isna(a) or pd.isna(d):
            continue

        at_depot = (r["accept_gps_lat"] == chosen_lat and r["accept_gps_lng"] == chosen_lng)

        bar_start = max(a, t_min)
        bar_end   = min(d, t_max)
        if bar_end > bar_start:
            ax.barh(y, bar_end - bar_start, left=bar_start - t_min,
                    height=0.6, color=colors[i % 10], alpha=0.7, edgecolor="white", linewidth=0.4)

        if t_min <= a <= t_max:
            accept_color = "limegreen" if at_depot else "black"
            ax.plot(a - t_min, y, marker="|", color=accept_color, markersize=10, markeredgewidth=1.5)

        if t_min <= d <= t_max:
            ax.plot(d - t_min, y, marker="D", color="crimson", markersize=4)

# Axes
hours = range(0, 18)
ax.set_xticks(list(hours))
ax.set_xticklabels([f"{h+7:02d}:00" for h in hours], fontsize=9)
ax.set_xlim(0, 17)
ax.set_yticks(range(len(courier_order)))
ax.set_yticklabels([f"Courier {c}" for c in courier_order], fontsize=10)
ax.set_xlabel("Time of day", fontsize=11)
ax.set_title(f"Courier day timelines — Oct 26, depot ({chosen_lat}, {chosen_lng})", fontsize=13)
ax.grid(axis="x", linestyle="--", alpha=0.4)
ax.invert_yaxis()

accept_depot  = Line2D([0], [0], marker="|", color="limegreen", markersize=10, linewidth=0, label="Accept at depot")
accept_enroute= Line2D([0], [0], marker="|", color="black",     markersize=10, linewidth=0, label="Accept mid-route")
deliver_dot   = Line2D([0], [0], marker="D", color="crimson",   markersize=6,  linewidth=0, label="Delivery time")
ax.legend(handles=[accept_depot, accept_enroute, deliver_dot], loc="lower right", fontsize=9)

plt.tight_layout()
out = "data/img/courier_timeline.png"
import os; os.makedirs("data/img", exist_ok=True)
plt.savefig(out, dpi=150)
print(f"Saved to {out}")
