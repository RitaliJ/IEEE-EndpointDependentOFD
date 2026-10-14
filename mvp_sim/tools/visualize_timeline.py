"""
Visualize an experiment result as a human-readable timeline.

Reads only saved result files from the experiment directory:
    events.log, orders.json, experiment_config.json

Usage:
    python -m mvp_sim.tools.visualize_timeline <experiment_dir>
    python -m mvp_sim.tools.visualize_timeline <experiment_dir> --no-color
"""

import argparse
import json
import os
import re

"""
File not generalized yet, it takes in distance of star instead of a general one
may not be a good idea to even make a general_one

could make another visualizer based on the type of cost? but thats already nasty
lol
"""

# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load(directory: str, filename: str):
    with open(os.path.join(directory, filename)) as f:
        return json.load(f)


def load_events(directory: str) -> list[dict]:
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
# Timeline builder — reads only from saved files
# ---------------------------------------------------------------------------

TIEBREAK = {
    "OrderArriveEvent":              0,
    "OrderReadyEvent":               1,
    "OrdersAssignEvent":             2,
    "DriverArriveEvent":             3,
    "OrderDeliveredEvent":           4,
    "DriverRepositionArriveEvent":   5,
    "DriverRepositionAssignEvent":   6,
    "OrderExpiredEvent":             7,
}


def build_timeline(directory: str) -> list[tuple[float, int, str, str]]:
    events   = load_events(directory)
    orders   = {o["order_id"]: o for o in load(directory, "orders.json")}
    config   = load(directory, "experiment_config.json")
    distances = config.get("distances", {})
    if not isinstance(distances, dict):
        distances = {}

    def branch_label(order_id: int) -> str:
        o = orders.get(order_id)
        if not o:
            return "?"
        vertex = o["destination"][0]
        dist   = distances.get(str(vertex), "?")
        return f"branch {vertex} (dist={dist})"

    timeline: list[tuple[float, int, str, str]] = []

    for ev in events:
        t    = ev["time"]
        etype = ev["event_type"]
        tb   = TIEBREAK.get(etype, 99)

        if etype == "OrderArriveEvent":
            oid = ev["order_id"]
            timeline.append((t, tb, "ARRIVE", f"order #{oid} → {branch_label(oid)}"))

        elif etype == "OrderReadyEvent":
            timeline.append((t, tb, "READY", f"order #{ev['order_id']}"))

        elif etype == "OrdersAssignEvent":
            oids = ev.get("order_ids", [])
            label = branch_label(oids[0]) if oids else "?"
            order_list = ", ".join(f"#{oid}" for oid in oids)
            timeline.append((t, tb, "ASSIGN",
                             f"driver #{ev['driver_id']} ← [{order_list}] → {label}"))

        elif etype == "DriverArriveEvent":
            timeline.append((t, tb, "PICKUP",
                             f"driver #{ev['driver_id']} at restaurant #{ev['restaurant_id']}"))

        elif etype == "OrderDeliveredEvent":
            oid = ev["order_id"]
            o   = orders.get(oid, {})
            flow = t - (o.get("arrival_time", 0) + o.get("prep_time", 0))
            timeline.append((t, tb, "DELIVER",
                             f"order #{oid} → {branch_label(oid)}  [flow={flow:.1f}]"))

        elif etype == "DriverRepositionArriveEvent":
            loc = ev.get("location", [])
            timeline.append((t, tb, "IDLE",
                             f"driver #{ev['driver_id']} idle at {tuple(loc)}"))

        elif etype == "DriverRepositionAssignEvent":
            loc = ev.get("location", [])
            timeline.append((t, tb, "REPOSITION",
                             f"driver #{ev['driver_id']} repositioning → {tuple(loc)}"))

        elif etype == "OrderExpiredEvent":
            timeline.append((t, tb, "EXPIRED", f"order #{ev['order_id']}"))

    return sorted(timeline, key=lambda e: (e[0], e[1]))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

CATEGORY_STYLE = {
    "ARRIVE":     ("↓", 33),
    "READY":      ("✓", 32),
    "ASSIGN":     ("→", 36),
    "PICKUP":     ("▶", 34),
    "DELIVER":    ("★", 35),
    "IDLE":       ("◉", 90),
    "REPOSITION": ("⇢", 90),
    "EXPIRED":    ("✗", 31),
}

RESET = "\033[0m"
_use_color = True


def _color(code: int, text: str) -> str:
    return f"\033[{code}m{text}{RESET}" if _use_color else text


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def render(timeline: list[tuple[float, int, str, str]], config: dict) -> str:
    lines = []
    distances = config.get("distances", {})
    if not isinstance(distances, dict):
        distances = {}
    branch_info = "  ".join(
        f"branch {v}: dist={d}" for v, d in distances.items() if str(v) != "0"
    )
    lines.append(_color(1, "=== Experiment Timeline ==="))
    lines.append(f"Seed: {config.get('seed', '?')}   "
                 f"Horizon: {config.get('horizon', '?')}   "
                 f"Warmup: {config.get('warmup_duration', '?')}")
    if branch_info:
        lines.append(f"Graph: {branch_info}")
    lines.append("")

    prev_time = None
    for time, _, category, desc in timeline:
        sym, col = CATEGORY_STYLE.get(category, ("?", 37))
        time_str = f"t={time:>6.1f}" if time != prev_time else " " * 9
        cat_str  = _color(col, f"{sym} {category:<11}")
        lines.append(f"  {time_str}  {cat_str}  {desc}")
        prev_time = time

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _use_color
    parser = argparse.ArgumentParser(description="Visualize experiment timeline")
    parser.add_argument("directory", help="Experiment output directory")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color")
    args = parser.parse_args()

    if args.no_color:
        _use_color = False

    config   = load(args.directory, "experiment_config.json")
    timeline = build_timeline(args.directory)
    output   = render(timeline, config)

    print(output)

    save_path = os.path.join(args.directory, "timeline.txt")
    with open(save_path, "w") as f:
        f.write(_strip_ansi(output))
    print(f"saved → {save_path}")


if __name__ == "__main__":
    main()
