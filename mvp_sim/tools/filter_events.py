"""
Filter an events.log to only include specified event types and save the result.

Usage:
    python -m mvp_sim.tools.filter_events <experiment_dir> [--types TYPE ...]

Default types: OrderArriveEvent OrderReadyEvent

Saves:
    <experiment_dir>/filtered_events.log

Examples:
    python -m mvp_sim.tools.filter_events experimental_results/star/
    python -m mvp_sim.tools.filter_events experimental_results/star/ --types OrderDeliveredEvent OrdersAssignEvent
"""

import argparse
import os

DEFAULT_TYPES = ["OrderArriveEvent", "OrderReadyEvent"]


def filter_events(directory: str, types: list[str]) -> list[str]:
    path = os.path.join(directory, "events.log")
    matched = []
    with open(path) as f:
        for line in f:
            if any(line.startswith(t) for t in types):
                matched.append(line.rstrip())
    return matched


def save_filtered(directory: str, types: list[str] = DEFAULT_TYPES) -> str:
    lines = filter_events(directory, types)
    out_path = os.path.join(directory, "filtered_events.log")
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Filter events.log by event type")
    parser.add_argument("directory", help="Experiment output directory")
    parser.add_argument("--types", nargs="+", default=DEFAULT_TYPES,
                        help="Event types to include (default: OrderArriveEvent OrderReadyEvent)")
    args = parser.parse_args()

    out_path = save_filtered(args.directory, args.types)
    print(f"saved → {out_path}")


if __name__ == "__main__":
    main()
