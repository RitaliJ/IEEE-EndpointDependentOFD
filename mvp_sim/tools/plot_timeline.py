"""
Plot an experiment result directory as a visual chart with a time axis.

Can read any saved file from the experiment directory
(orders.json, completed_orders.json, batches.json, events.log,
experiment_config.json, drivers.json).

Usage:
    python -m mvp_sim.tools.plot_timeline <experiment_dir>

Saves (to <experiment_dir>/)
------------------------------
    overview.png         — 3-panel combined view: order Gantt, event scatter,
                           driver swim-lane.
    driver_activity.png  — full-width swim-lane for all drivers.
    driver_<id>.png      — per-driver: that driver's order Gantt + swim-lane.
"""

import argparse
import json
import os
import re

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from tqdm import tqdm


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BG       = "#1E1E2E"
FG       = "#CDD6F4"
GRID_COL = "#45475A"
PANEL_BG = "#181825"

CATEGORY_COLORS = {
    "ARRIVE":  "#F59E0B",
    "READY":   "#10B981",
    "ASSIGN":  "#3B82F6",
    "PICKUP":  "#6366F1",
    "DELIVER": "#F38BA8",
    "RARR":    "#9CA3AF",
    "RASS":    "#6B7280",
    "EXPIRED": "#EF4444",
}

CATEGORIES = list(CATEGORY_COLORS)

ACTIVITY_COLORS = {
    "idle":          "#313244",
    "traveling":     "#3B82F6",
    "delivering":    "#F38BA8",
    "repositioning": "#9CA3AF",
}

DRIVER_PALETTE = [
    "#F59E0B", "#10B981", "#6366F1", "#EC4899",
    "#14B8A6", "#8B5CF6", "#EF4444", "#F97316",
]

EVENT_TYPE_TO_CATEGORY = {
    "OrderArriveEvent":            "ARRIVE",
    "OrderReadyEvent":             "READY",
    "OrdersAssignEvent":           "ASSIGN",
    "DriverArriveEvent":           "PICKUP",
    "OrderDeliveredEvent":         "DELIVER",
    "DriverRepositionArriveEvent": "RARR",
    "DriverRepositionAssignEvent": "RASS",
    "OrderExpiredEvent":           "EXPIRED",
}


# ---------------------------------------------------------------------------
# Loading saved files
# ---------------------------------------------------------------------------

def _load(directory: str, filename: str):
    with open(os.path.join(directory, filename)) as f:
        return json.load(f)


def _load_events(directory: str) -> list[dict]:
    path = os.path.join(directory, "events.log")
    events = []
    with open(path) as f:
        for line in f:
            parsed = _parse_event_line(line.strip())
            if parsed:
                events.append(parsed)
    return events


def _parse_event_line(line: str) -> dict | None:
    m = re.match(r"(\w+)\((.+)\)$", line)
    if not m:
        return None
    fields: dict = {"event_type": m.group(1)}
    for kv in re.finditer(r"(\w+)=(\[[^\]]*\]|[^,)]+)", m.group(2)):
        key, raw = kv.group(1), kv.group(2).strip()
        if raw.startswith("["):
            fields[key] = [int(float(x.strip())) for x in raw[1:-1].split(",") if x.strip()]
        else:
            try:
                fields[key] = int(raw)
            except ValueError:
                try:
                    fields[key] = float(raw)
                except ValueError:
                    fields[key] = raw
    return fields


# ---------------------------------------------------------------------------
# Building structured data from saved files
# ---------------------------------------------------------------------------

def build_data(directory: str) -> tuple[dict, dict, list[dict], list[dict], list[dict]]:
    """
    Returns (config, orders_by_id, raw_events, batches, drivers).
    orders_by_id merges orders.json with completed_orders.json and
    annotates each order with assign_time and driver_id from events.
    """
    config    = _load(directory, "experiment_config.json")
    orders_in = {o["order_id"]: o for o in _load(directory, "orders.json")}
    completed = {o["order_id"]: o for o in _load(directory, "completed_orders.json")}
    batches   = _load(directory, "batches.json")
    drivers   = _load(directory, "drivers.json")
    events    = _load_events(directory)

    orders: dict = {}
    for oid, o in orders_in.items():
        orders[oid] = dict(o)
        if oid in completed:
            orders[oid]["completion_time"] = completed[oid]["completion_time"]

    for ev in events:
        if ev["event_type"] == "OrdersAssignEvent":
            for oid in ev.get("order_ids", []):
                if oid in orders:
                    orders[oid]["assign_time"] = ev["time"]
                    orders[oid]["driver_id"]   = ev.get("driver_id")

    return config, orders, events, batches, drivers


def build_driver_segments(
    events: list[dict],
    driver_ids: list[int],
    end_time: float,
) -> dict[int, list[tuple[float, float, str]]]:
    """
    Reconstruct activity segments per driver from events.log.

    Transitions:
      OrdersAssignEvent           → traveling
      DriverArriveEvent           → delivering
      DriverRepositionAssignEvent → repositioning
      DriverRepositionArriveEvent → idle

    Returns {driver_id: [(start, end, state), ...]}.
    """
    TRANSITIONS = {
        "OrdersAssignEvent":           "traveling",
        "DriverArriveEvent":           "delivering",
        "DriverRepositionAssignEvent": "repositioning",
        "DriverRepositionArriveEvent": "idle",
    }

    driver_events: dict[int, list] = {did: [] for did in driver_ids}
    for ev in events:
        did = ev.get("driver_id")
        if did in driver_events and ev["event_type"] in TRANSITIONS:
            driver_events[did].append(ev)

    segments: dict[int, list] = {}
    for did in driver_ids:
        evs = sorted(driver_events[did], key=lambda e: (e["time"], e.get("id", 0)))
        segs: list[tuple[float, float, str]] = []
        curr_state = "idle"
        curr_time  = 0.0

        for ev in evs:
            t = ev["time"]
            if t > curr_time:
                segs.append((curr_time, t, curr_state))
            curr_state = TRANSITIONS[ev["event_type"]]
            curr_time  = t

        segs.append((curr_time, end_time, curr_state))
        segments[did] = segs

    return segments


# ---------------------------------------------------------------------------
# Shared drawing helpers
# ---------------------------------------------------------------------------

def _style_ax(ax) -> None:
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=FG, labelsize=8)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)
    for spine in ax.spines.values():
        spine.set_color(GRID_COL)


def _draw_gantt(
    ax,
    sorted_orders: list[dict],
    branch_color: dict,
    driver_color: dict,
    title: str = "Order Lifecycle    |=arrive   ▲=assign (by driver)   ★=deliver (by driver)",
    sim_end_time: float | None = None,
) -> None:
    UNDELIVERED_COLOR = "#6B7280"
    for row, o in enumerate(sorted_orders):
        arrive  = o.get("arrival_time")
        deliver = o.get("completion_time")
        assign  = o.get("assign_time")
        branch  = o.get("destination", [0])[0]
        bar_col = branch_color.get(branch, FG)
        drv_col = driver_color.get(o.get("driver_id"), FG)

        if arrive is not None and deliver is not None:
            ax.barh(row, deliver - arrive, left=arrive,
                    color=bar_col, alpha=0.45, height=0.6, zorder=2)
            ax.scatter(arrive, row, marker="|", color=bar_col,
                       s=90, linewidths=2, zorder=3)
            ax.scatter(deliver, row, marker="*", color=drv_col, s=140, zorder=4)
        elif arrive is not None and sim_end_time is not None:
            ax.barh(row, sim_end_time - arrive, left=arrive,
                    color=UNDELIVERED_COLOR, alpha=0.3, height=0.6, zorder=2)
            ax.scatter(arrive, row, marker="|", color=UNDELIVERED_COLOR,
                       s=90, linewidths=2, zorder=3)

        if assign is not None:
            ax.scatter(assign, row, marker="^", color=drv_col, s=70, zorder=3)

    ax.set_yticks(range(len(sorted_orders)))
    ax.set_yticklabels([f"#{o['order_id']}" for o in sorted_orders], fontsize=7)
    ax.set_xlabel("Time", color=FG)
    ax.set_title(title, pad=8)
    ax.grid(axis="x", color=GRID_COL, alpha=0.5, linestyle="--", zorder=1)
    ax.invert_yaxis()


def _draw_scatter(ax, events: list[dict]) -> None:
    present_cats = [
        cat for cat in CATEGORIES
        if any(EVENT_TYPE_TO_CATEGORY.get(e["event_type"]) == cat for e in events)
    ]
    cat_idx = {c: i for i, c in enumerate(present_cats)}

    buckets: dict[str, list] = {c: [] for c in present_cats}
    for ev in events:
        cat = EVENT_TYPE_TO_CATEGORY.get(ev["event_type"])
        if cat and cat in cat_idx:
            buckets[cat].append(ev["time"])

    for cat, times in buckets.items():
        if times:
            ax.scatter(times, [cat_idx[cat]] * len(times),
                       color=CATEGORY_COLORS.get(cat, FG),
                       s=45, alpha=0.75, zorder=2)

    ax.set_yticks(range(len(present_cats)))
    ax.set_yticklabels(present_cats, fontsize=8)
    ax.set_xlabel("Time", color=FG)
    ax.set_title("Events over Time", pad=8)
    ax.grid(axis="x", color=GRID_COL, alpha=0.5, linestyle="--", zorder=1)


def _draw_swim(
    ax,
    segments: dict[int, list],
    driver_ids: list[int],
    title: str = "Driver Activity",
) -> None:
    for row, did in enumerate(driver_ids):
        xranges_by_state: dict[str, list] = {}
        for start, end, state in segments[did]:
            if end > start:
                xranges_by_state.setdefault(state, []).append((start, end - start))
        for state, xranges in xranges_by_state.items():
            ax.broken_barh(xranges, (row - 0.3, 0.6),
                           facecolors=ACTIVITY_COLORS.get(state, FG),
                           alpha=0.85, zorder=2)

    show_labels = len(driver_ids) <= 100
    ax.set_yticks(range(len(driver_ids)))
    ax.set_yticklabels([f"d{did}" for did in driver_ids] if show_labels else [], fontsize=6)
    ax.set_xlabel("Time", color=FG)
    ax.set_title(title, pad=8)
    ax.grid(axis="x", color=GRID_COL, alpha=0.5, linestyle="--", zorder=1)

    activity_patches = [
        mpatches.Patch(color=ACTIVITY_COLORS[s], label=s)
        for s in ("idle", "traveling", "delivering", "repositioning")
    ]
    ax.legend(handles=activity_patches, loc="upper right",
              facecolor="#313244", edgecolor=GRID_COL, labelcolor=FG, fontsize=8)


def _save(fig, output_path: str, dpi: int = 150) -> None:
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"saved → {output_path}")


# ---------------------------------------------------------------------------
# Individual plot functions
# ---------------------------------------------------------------------------

def plot_overview(directory: str, output_path: str, _data=None) -> None:
    """3-panel combined view: order Gantt + event scatter + driver swim-lane."""
    config, orders, events, _, drivers = _data or build_data(directory)
    distances  = config.get("distances", {})
    if not isinstance(distances, dict):
        distances = {}
    driver_ids = sorted(d["driver_id"] for d in drivers)
    n_drivers  = len(driver_ids)

    driver_color = {did: DRIVER_PALETTE[i % len(DRIVER_PALETTE)]
                    for i, did in enumerate(driver_ids)}
    branches     = sorted(int(v) for v in distances if str(v) != "0")
    palette      = plt.cm.Set2(np.linspace(0, 0.8, max(len(branches), 1)))
    branch_color = {b: palette[i] for i, b in enumerate(branches)}

    swim_height = max(n_drivers, 1)
    fig, (ax_gantt, ax_scatter, ax_swim) = plt.subplots(
        3, 1,
        figsize=(16, 11 + swim_height),
        gridspec_kw={"height_ratios": [3, 1, swim_height]},
    )
    fig.patch.set_facecolor(BG)
    _style_ax(ax_gantt)
    _style_ax(ax_scatter)
    _style_ax(ax_swim)

    sorted_orders = sorted(orders.values(), key=lambda o: o.get("arrival_time", 0))
    _draw_gantt(ax_gantt, sorted_orders, branch_color, driver_color)

    branch_patches = [
        mpatches.Patch(color=branch_color[b],
                       label=f"branch {b} (dist={distances.get(str(b), '?')})")
        for b in branches
    ]
    driver_patches = [
        mpatches.Patch(color=driver_color[did], label=f"driver {did}")
        for did in driver_ids
    ]
    ax_gantt.legend(handles=branch_patches + driver_patches, loc="upper right",
                    facecolor="#313244", edgecolor=GRID_COL, labelcolor=FG, fontsize=8)

    _draw_scatter(ax_scatter, events)

    end_time = max((ev["time"] for ev in events), default=float(config.get("horizon", 1)))
    segments = build_driver_segments(events, driver_ids, end_time)
    _draw_swim(ax_swim, segments, driver_ids)

    seed    = config.get("seed",    "?")
    horizon = config.get("horizon", "?")
    policy  = config.get("policy",  "?")
    branch_summary = "  ".join(
        f"branch {v}: dist={d}" for v, d in distances.items() if str(v) != "0"
    )
    fig.suptitle(
        f"Star Experiment  —  policy={policy}  seed={seed}  horizon={horizon}  "
        f"drivers={n_drivers}  |  {branch_summary}",
        color=FG, fontsize=11, y=1.01,
    )
    _save(fig, output_path)


def plot_driver_activity(directory: str, output_path: str, _data=None) -> None:
    """Full-width swim-lane for all drivers."""
    config, _, events, _, drivers = _data or build_data(directory)
    driver_ids = sorted(d["driver_id"] for d in drivers)
    n_drivers  = len(driver_ids)

    end_time = max((ev["time"] for ev in events), default=float(config.get("horizon", 1)))
    segments = build_driver_segments(events, driver_ids, end_time)

    fig, ax = plt.subplots(figsize=(16, min(2 + n_drivers * 0.15, 60)))
    fig.patch.set_facecolor(BG)
    _style_ax(ax)
    _draw_swim(ax, segments, driver_ids, title="Driver Activity")

    seed   = config.get("seed",   "?")
    policy = config.get("policy", "?")
    fig.suptitle(
        f"Driver Activity  —  policy={policy}  seed={seed}  drivers={n_drivers}",
        color=FG, fontsize=11, y=1.02,
    )
    _save(fig, output_path, dpi=72)


def plot_driver(directory: str, driver_id: int, output_path: str, _data=None) -> None:
    """Per-driver: that driver's order Gantt + their personal swim-lane."""
    config, orders, events, _, drivers = _data or build_data(directory)
    distances  = config.get("distances", {})
    if not isinstance(distances, dict):
        distances = {}
    driver_ids = sorted(d["driver_id"] for d in drivers)

    driver_color = {did: DRIVER_PALETTE[i % len(DRIVER_PALETTE)]
                    for i, did in enumerate(driver_ids)}
    branches     = sorted(int(v) for v in distances if str(v) != "0")
    palette      = plt.cm.Set2(np.linspace(0, 0.8, max(len(branches), 1)))
    branch_color = {b: palette[i] for i, b in enumerate(branches)}

    driver_orders = sorted(
        [o for o in orders.values() if o.get("driver_id") == driver_id],
        key=lambda o: o.get("arrival_time", 0),
    )

    end_time = max((ev["time"] for ev in events), default=float(config.get("horizon", 1)))
    segments = build_driver_segments(events, [driver_id], end_time)

    n_orders = max(len(driver_orders), 1)
    fig, (ax_gantt, ax_swim) = plt.subplots(
        2, 1,
        figsize=(16, 4 + n_orders * 0.3),
        gridspec_kw={"height_ratios": [max(n_orders, 3), 1]},
    )
    fig.patch.set_facecolor(BG)
    _style_ax(ax_gantt)
    _style_ax(ax_swim)

    _draw_gantt(ax_gantt, driver_orders, branch_color, driver_color,
                title=f"Driver {driver_id} — Order Lifecycle    |=arrive   ▲=assign   ★=deliver")

    branch_patches = [
        mpatches.Patch(color=branch_color[b],
                       label=f"branch {b} (dist={distances.get(str(b), '?')})")
        for b in branches
    ]
    ax_gantt.legend(handles=branch_patches, loc="upper right",
                    facecolor="#313244", edgecolor=GRID_COL, labelcolor=FG, fontsize=8)

    _draw_swim(ax_swim, segments, [driver_id], title=f"Driver {driver_id} — Activity")

    seed   = config.get("seed",   "?")
    policy = config.get("policy", "?")
    fig.suptitle(
        f"Driver {driver_id}  —  policy={policy}  seed={seed}  "
        f"orders={len(driver_orders)}",
        color=FG, fontsize=11, y=1.01,
    )
    _save(fig, output_path)


def plot_order_gantt(directory: str, output_path: str, _data=None) -> None:
    """Single-panel order Gantt chart."""
    config, orders, _, _, drivers = _data or build_data(directory)
    distances  = config.get("distances", {})
    if not isinstance(distances, dict):
        distances = {}
    driver_ids = sorted(d["driver_id"] for d in drivers)

    driver_color = {did: DRIVER_PALETTE[i % len(DRIVER_PALETTE)]
                    for i, did in enumerate(driver_ids)}
    branches     = sorted(int(v) for v in distances if str(v) != "0")
    palette      = plt.cm.Set2(np.linspace(0, 0.8, max(len(branches), 1)))
    branch_color = {b: palette[i] for i, b in enumerate(branches)}

    completion_times = [o["completion_time"] for o in orders.values() if o.get("completion_time") is not None]
    sim_end_time = max(completion_times) if completion_times else float(config.get("horizon", 1))

    n_orders = max(len(orders), 1)
    fig, ax = plt.subplots(figsize=(16, max(5, n_orders * 0.35)))
    fig.patch.set_facecolor(BG)
    _style_ax(ax)

    sorted_orders = sorted(orders.values(), key=lambda o: o.get("arrival_time", 0))
    _draw_gantt(ax, sorted_orders, branch_color, driver_color, sim_end_time=sim_end_time)

    branch_patches = [
        mpatches.Patch(color=branch_color[b],
                       label=f"branch {b} (dist={distances.get(str(b), '?')})")
        for b in branches
    ]
    driver_patches = [
        mpatches.Patch(color=driver_color[did], label=f"driver {did}")
        for did in driver_ids
    ]
    undelivered_patch = mpatches.Patch(color="#6B7280", alpha=0.3, label="undelivered")
    ax.legend(handles=branch_patches + driver_patches + [undelivered_patch], loc="upper right",
              facecolor="#313244", edgecolor=GRID_COL, labelcolor=FG, fontsize=8)

    seed   = config.get("seed",   "?")
    policy = config.get("policy", "?")
    fig.suptitle(f"Order Gantt  —  policy={policy}  seed={seed}", color=FG, fontsize=11)
    _save(fig, output_path)


def plot_event_scatter(directory: str, output_path: str, _data=None) -> None:
    """Single-panel event scatter chart."""
    config, _, events, _, _ = _data or build_data(directory)

    fig, ax = plt.subplots(figsize=(16, 4))
    fig.patch.set_facecolor(BG)
    _style_ax(ax)
    _draw_scatter(ax, events)

    seed   = config.get("seed",   "?")
    policy = config.get("policy", "?")
    fig.suptitle(f"Event Scatter  —  policy={policy}  seed={seed}", color=FG, fontsize=11)
    _save(fig, output_path)


import csv as _csv


def _build_metric_series(
    config: dict,
    orders: dict,
    events: list[dict],
    drivers: list[dict],
    n_bins: int = 50,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute binned time-series for all four metrics.

    Returns (bin_centers, travel_avgs, flow_avgs, util_avgs, batch_avgs).
    """
    horizon    = float(config.get("horizon", 1))
    warmup     = float(config.get("warmup_duration", 0))
    driver_ids = [d["driver_id"] for d in drivers]
    n_drivers  = len(driver_ids)

    assign_times:  dict[int, float] = {}
    deliver_times: dict[int, float] = {}
    batch_events:  list[tuple[float, int]] = []

    for ev in events:
        etype = ev["event_type"]
        t     = ev["time"]
        if etype == "OrdersAssignEvent":
            oids = ev.get("order_ids", [])
            for oid in oids:
                assign_times[oid] = t
            if oids:
                batch_events.append((t, len(oids)))
        elif etype == "OrderDeliveredEvent":
            deliver_times[ev["order_id"]] = t

    # horizon is when orders stop arriving; completions can extend well past it
    actual_end = max(
        (o["completion_time"] for o in orders.values() if o.get("completion_time") is not None),
        default=horizon,
    )
    sim_end     = max(actual_end, horizon)
    bin_edges   = np.linspace(warmup, sim_end, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    def _bin_avg(times, values):
        avgs = []
        for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
            vals = [v for t, v in zip(times, values) if lo <= t < hi]
            avgs.append(float(np.mean(vals)) if vals else float("nan"))
        return np.array(avgs)

    # cumulative avg flow time: avg of all qualifying orders completing at or before each bin edge
    flow_pairs = [
        (o["completion_time"], o["completion_time"] - o["arrival_time"])
        for o in orders.values()
        if o.get("completion_time") is not None
        and o.get("arrival_time") is not None
        and o["arrival_time"] >= warmup
    ]
    if flow_pairs:
        ft_arr    = np.array([ft for ft, _ in flow_pairs])
        fv_arr    = np.array([fv for _, fv in flow_pairs])
        flow_avgs = np.array([
            float(np.mean(fv_arr[ft_arr <= hi])) if np.any(ft_arr <= hi) else float("nan")
            for hi in bin_edges[1:]
        ])
    else:
        flow_avgs = np.full(n_bins, float("nan"))

    # travel_time = delivery_time - assign_time, binned by delivery_time
    travel_pairs = [
        (deliver_times[oid], deliver_times[oid] - assign_times[oid])
        for oid in deliver_times
        if oid in assign_times and deliver_times[oid] >= warmup
    ]
    if travel_pairs:
        tt_arr      = np.array([t for t, _ in travel_pairs])
        tv_arr      = np.array([v for _, v in travel_pairs])
        travel_avgs = np.array([
            float(np.mean(tv_arr[tt_arr <= hi])) if np.any(tt_arr <= hi) else float("nan")
            for hi in bin_edges[1:]
        ])
    else:
        travel_avgs = np.full(n_bins, float("nan"))

    # cumulative driver utilization: fraction of driver-time spent active from warmup to each bin edge
    segments  = build_driver_segments(events, driver_ids, sim_end)
    util_avgs = []
    for hi in bin_edges[1:]:
        dt = hi - warmup
        if dt <= 0 or n_drivers == 0:
            util_avgs.append(float("nan"))
            continue
        active = sum(
            max(0.0, min(end, hi) - max(start, warmup))
            for segs in segments.values()
            for start, end, state in segs
            if state in ("traveling", "delivering")
        )
        util_avgs.append(active / (n_drivers * dt))
    util_avgs = np.array(util_avgs)

    # cumulative avg batch size: avg of all batches assigned at or before each bin edge
    if batch_events:
        bt_arr     = np.array([t for t, _ in batch_events])
        bv_arr     = np.array([v for _, v in batch_events])
        batch_avgs = np.array([
            float(np.mean(bv_arr[bt_arr <= hi])) if np.any(bt_arr <= hi) else float("nan")
            for hi in bin_edges[1:]
        ])
    else:
        batch_avgs = np.full(n_bins, float("nan"))

    return bin_centers, travel_avgs, flow_avgs, util_avgs, batch_avgs


def _save_metric_csv(output_path: str, time_col: str, value_col: str,
                     bin_centers: np.ndarray, avgs: np.ndarray) -> None:
    csv_path = os.path.splitext(output_path)[0] + ".csv"
    with open(csv_path, "w", newline="") as f:
        writer = _csv.writer(f)
        writer.writerow([time_col, value_col])
        for t, v in zip(bin_centers, avgs):
            writer.writerow([t, "" if np.isnan(v) else v])
    print(f"saved → {csv_path}")


def _plot_metric_line(
    output_path: str,
    title: str,
    ylabel: str,
    color: str,
    bin_centers: np.ndarray,
    avgs: np.ndarray,
    warmup: float,
    suptitle: str,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(BG)
    _style_ax(ax)

    mask = ~np.isnan(avgs)
    xs, ys = bin_centers[mask], avgs[mask]
    if len(xs):
        ax.plot(xs, ys, color=color, linewidth=2)
        ax.fill_between(xs, ys, alpha=0.2, color=color)

    ax.set_title(title, pad=8)
    ax.set_xlabel("Time", color=FG)
    ax.set_ylabel(ylabel, color=FG)
    ax.grid(axis="both", color=GRID_COL, alpha=0.4, linestyle="--", zorder=1)
    if warmup > 0:
        ax.axvline(warmup, color="#EF4444", linestyle=":", alpha=0.7, linewidth=1,
                   label=f"warmup end ({warmup})")
        ax.legend(facecolor="#313244", edgecolor=GRID_COL, labelcolor=FG, fontsize=8)

    fig.suptitle(suptitle, color=FG, fontsize=11)
    _save(fig, output_path)


def plot_travel_time_over_time(directory: str, output_path: str, _data=None, n_bins: int = 50) -> None:
    """Avg travel time (assign→deliver) per time bin. Also writes a companion CSV."""
    config, orders, events, _, drivers = _data or build_data(directory)
    bin_centers, travel_avgs, _, _, _ = _build_metric_series(config, orders, events, drivers, n_bins)
    warmup = float(config.get("warmup_duration", 0))
    policy, seed = config.get("policy", "?"), config.get("seed", "?")
    _plot_metric_line(output_path, "Avg Travel Time vs Time", "Avg Travel Time",
                      "#3B82F6", bin_centers, travel_avgs, warmup,
                      f"Avg Travel Time  —  policy={policy}  seed={seed}")
    _save_metric_csv(output_path, "time", "avg_travel_time", bin_centers, travel_avgs)


def plot_flow_time_over_time(directory: str, output_path: str, _data=None, n_bins: int = 50) -> None:
    """Avg flow time (arrival→delivery) per time bin. Also writes a companion CSV."""
    config, orders, events, _, drivers = _data or build_data(directory)
    bin_centers, _, flow_avgs, _, _ = _build_metric_series(config, orders, events, drivers, n_bins)
    warmup = float(config.get("warmup_duration", 0))
    policy, seed = config.get("policy", "?"), config.get("seed", "?")
    _plot_metric_line(output_path, "Avg Flow Time vs Time", "Avg Flow Time",
                      "#10B981", bin_centers, flow_avgs, warmup,
                      f"Avg Flow Time  —  policy={policy}  seed={seed}")
    _save_metric_csv(output_path, "time", "avg_flow_time", bin_centers, flow_avgs)


def plot_max_flow_time_over_time(directory: str, output_path: str, _data=None, n_bins: int = 50) -> None:
    """Max flow time (arrival→delivery) per time bin. Also writes a companion CSV."""
    config, orders, events, _, drivers = _data or build_data(directory)
    warmup  = float(config.get("warmup_duration", 0))
    horizon = float(config.get("horizon", 1))
    policy, seed = config.get("policy", "?"), config.get("seed", "?")

    actual_end  = max(
        (o["completion_time"] for o in orders.values() if o.get("completion_time") is not None),
        default=horizon,
    )
    sim_end     = max(actual_end, horizon)
    bin_edges   = np.linspace(warmup, sim_end, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    def _bin_max(times, values):
        result = []
        for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
            vals = [v for t, v in zip(times, values) if lo <= t < hi]
            result.append(float(max(vals)) if vals else float("nan"))
        return np.array(result)

    flow_pairs = [
        (o["completion_time"], o["completion_time"] - o["arrival_time"])
        for o in orders.values()
        if o.get("completion_time") is not None
        and o.get("arrival_time")   is not None
        and o["arrival_time"] >= warmup
    ]
    if flow_pairs:
        ft_arr     = np.array([t for t, _ in flow_pairs])
        fv_arr     = np.array([v for _, v in flow_pairs])
        flow_maxes = np.array([
            float(np.max(fv_arr[ft_arr <= hi])) if np.any(ft_arr <= hi) else float("nan")
            for hi in bin_edges[1:]
        ])
    else:
        flow_maxes = np.full(n_bins, float("nan"))

    _plot_metric_line(output_path, "Max Flow Time vs Time", "Max Flow Time",
                      "#F59E0B", bin_centers, flow_maxes, warmup,
                      f"Max Flow Time  —  policy={policy}  seed={seed}")
    _save_metric_csv(output_path, "time", "max_flow_time", bin_centers, flow_maxes)


def plot_driver_utilization_over_time(directory: str, output_path: str, _data=None, n_bins: int = 50) -> None:
    """Avg driver utilization (fraction active) per time bin. Also writes a companion CSV."""
    config, orders, events, _, drivers = _data or build_data(directory)
    bin_centers, _, _, util_avgs, _ = _build_metric_series(config, orders, events, drivers, n_bins)
    warmup = float(config.get("warmup_duration", 0))
    policy, seed = config.get("policy", "?"), config.get("seed", "?")
    _plot_metric_line(output_path, "Avg Driver Utilization vs Time", "Utilization",
                      "#F59E0B", bin_centers, util_avgs, warmup,
                      f"Avg Driver Utilization  —  policy={policy}  seed={seed}")
    _save_metric_csv(output_path, "time", "avg_driver_utilization", bin_centers, util_avgs)


def plot_batch_size_over_time(directory: str, output_path: str, _data=None, n_bins: int = 50) -> None:
    """Avg batch size per time bin. Also writes a companion CSV."""
    config, orders, events, _, drivers = _data or build_data(directory)
    bin_centers, _, _, _, batch_avgs = _build_metric_series(config, orders, events, drivers, n_bins)
    warmup = float(config.get("warmup_duration", 0))
    policy, seed = config.get("policy", "?"), config.get("seed", "?")
    _plot_metric_line(output_path, "Avg Batch Size vs Time", "Avg Batch Size",
                      "#6366F1", bin_centers, batch_avgs, warmup,
                      f"Avg Batch Size  —  policy={policy}  seed={seed}")
    _save_metric_csv(output_path, "time", "avg_batch_size", bin_centers, batch_avgs)


def plot_all(directory: str, per_driver: bool = True, order_gantt: bool = True) -> list[str]:
    """Generate all plot images into directory. Returns list of saved paths."""
    data = build_data(directory)
    _, orders, _, _, drivers = data
    driver_ids = sorted(d["driver_id"] for d in drivers)
    saved = []

    many_orders = len(orders) > 200

    summary_plots = [
        ("order_gantt.png",                  lambda p: plot_order_gantt(directory, p, _data=data),                  order_gantt),
        ("event_scatter.png",                lambda p: plot_event_scatter(directory, p, _data=data),                True),
        ("driver_activity.png",              lambda p: plot_driver_activity(directory, p, _data=data),              not many_orders),
        ("travel_time_over_time.png",        lambda p: plot_travel_time_over_time(directory, p, _data=data),        True),
        ("flow_time_over_time.png",          lambda p: plot_flow_time_over_time(directory, p, _data=data),          True),
        ("max_flow_time_over_time.png",     lambda p: plot_max_flow_time_over_time(directory, p, _data=data),      True),
        ("driver_utilization_over_time.png", lambda p: plot_driver_utilization_over_time(directory, p, _data=data), True),
        ("batch_size_over_time.png",         lambda p: plot_batch_size_over_time(directory, p, _data=data),         True),
    ]
    for name, fn, enabled in tqdm(summary_plots, desc="summary plots"):
        if not enabled:
            continue
        p = os.path.join(directory, name)
        fn(p)
        saved.append(p)

    if per_driver:
        for did in tqdm(driver_ids, desc="per-driver plots"):
            p = os.path.join(directory, f"driver_{did}.png")
            plot_driver(directory, did, p, _data=data)
            saved.append(p)

    return saved


# backward-compat alias
def plot(directory: str, output_path: str) -> None:
    plot_overview(directory, output_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Plot experiment results as a visual timeline")
    parser.add_argument("directory", help="Experiment output directory")
    args = parser.parse_args()
    plot_all(args.directory)


if __name__ == "__main__":
    main()
