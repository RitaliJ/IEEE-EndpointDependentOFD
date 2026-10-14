"""Turn a directory of individual runs into the tables the paper is built from.

Every run writes metrics.json and experiment_config.json. This module walks those,
flattens them into one tidy row per run, and produces three machine-readable
artifacts:

    results_long.csv     one row per (city, seed, supply, policy)
    results_summary.csv  mean / std / 95% CI across replicate seeds
    results_paired.csv   per-seed percentage change vs a baseline policy,
                         computed only within a matching (city, seed, trace,
                         fleet, cost) cell

The paired table is the one to quote improvements from. Averaging each policy
across seeds first and then dividing throws away the pairing that makes the
comparison low-variance, and it silently tolerates policies whose runs came from
different traces.
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
from collections import defaultdict

# Two-sided 95% t multipliers by degrees of freedom (n - 1). Replicate counts are
# small, so the normal approximation (1.96) understates the interval materially:
# at n=3 the correct multiplier is 4.30.
_T95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
}


def _t95(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df in _T95:
        return _T95[df]
    return 1.96


# Metric columns kept in the tables, in report order. Scalars are taken directly;
# "metric.stat" entries pull a field out of a summary-stats dict.
METRIC_COLUMNS: list[str] = [
    "flow_time.avg",
    "flow_time.p90",
    "flow_time.p95",
    "flow_time.p99",
    "flow_time.max",
    "arrived_orders",
    "delivered_orders",
    "undelivered_orders",
    "completion_rate",
    "avg_batch_size",
    "batch_efficiency",
    "driver_utilization.avg",
    "driver_utilization.max",
    "driver_utilization_makespan.avg",
    "driver_utilization_makespan.max",
    "makespan",
    "travel_time.avg",
]

# Identity of the experimental cell a run belongs to. Two runs may only be PAIRED
# when every one of these matches -- including the trace and roster hashes, since
# a percentage improvement is only meaningful between policies that saw the same
# world.
CELL_KEYS: list[str] = ["city", "supply_fraction", "num_drivers", "trace_hash",
                        "roster_hash", "warmup_duration", "warmup_fraction",
                        "cost_signature"]

# Identity of the condition a *replicate* belongs to. Deliberately excludes the
# trace and roster hashes: replicates are independent redraws, so every seed has a
# different trace by design, and grouping on the hash would put each seed in its
# own group and never pool anything.
SUMMARY_KEYS: list[str] = ["city", "supply_fraction", "num_drivers",
                           "warmup_config", "cost_signature"]


def _get_metric(metrics: dict, column: str):
    if "." in column:
        name, stat = column.split(".", 1)
        value = metrics.get(name)
        return value.get(stat) if isinstance(value, dict) else None
    return metrics.get(column)


def load_runs(root: str) -> list[dict]:
    """Collect every run under `root` that has both metrics and config."""
    rows: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "metrics.json" not in filenames or "experiment_config.json" not in filenames:
            continue
        with open(os.path.join(dirpath, "metrics.json")) as f:
            metrics = json.load(f)
        with open(os.path.join(dirpath, "experiment_config.json")) as f:
            config = json.load(f)
        runtime = {}
        runtime_path = os.path.join(dirpath, "runtime.json")
        if os.path.exists(runtime_path):
            with open(runtime_path) as f:
                runtime = json.load(f)

        scenario = config.get("scenario", {})
        cost = scenario.get("cost_params", {})
        row: dict = {
            "run_dir": os.path.relpath(dirpath, root),
            "city": scenario.get("city", config.get("experiment", "?")),
            "data_day": scenario.get("data_day"),
            "seed": config.get("seed", scenario.get("experiment_seed")),
            "policy": config.get("policy"),
            "policy_config": json.dumps(config.get("policy_config", {}), sort_keys=True),
            "supply_fraction": config.get("supply_fraction", 1.0),
            "num_drivers": config.get("num_drivers"),
            "num_zones": config.get("num_zones"),
            "num_restaurants": config.get("num_restaurants"),
            "horizon": config.get("horizon"),
            "warmup_duration": config.get("warmup_duration"),
            "warmup_fraction": config.get("warmup_fraction"),
            "warmup_config": (
                f"fraction:{config.get('warmup_fraction')}"
                if config.get("warmup_fraction") is not None
                else f"duration:{config.get('warmup_duration')}"
            ),
            "runtime_seconds": runtime.get("runtime_seconds"),
            "simulation_runtime_seconds": runtime.get(
                "simulation_runtime_seconds", config.get("simulation_runtime_seconds")),
            "trace_hash": scenario.get("trace_hash"),
            "roster_hash": scenario.get("roster_hash"),
            "cost_function": cost.get("cost_function"),
            "batch_alpha": cost.get("batch_alpha"),
            "bhh_constant": cost.get("bhh_constant"),
            "speed_km_per_min": cost.get("speed_km_per_min"),
            # Full identity, including estimated zone scales and the actual
            # matrix digest. Pairing on alpha alone can silently mix models.
            "cost_signature": json.dumps({
                "params": cost,
                "matrix_sha": config.get("cost_matrix_sha"),
            }, sort_keys=True, separators=(",", ":")),
        }
        for column in METRIC_COLUMNS:
            row[column] = _get_metric(metrics, column)
        rows.append(row)

    rows.sort(key=lambda r: (str(r["city"]), r["supply_fraction"] or 0,
                             r["seed"] or 0, str(r["policy"])))
    return rows


def _write_csv(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_long(rows: list[dict], path: str) -> None:
    if not rows:
        return
    base = [k for k in rows[0] if k not in METRIC_COLUMNS]
    _write_csv(path, base + METRIC_COLUMNS, rows)


def write_summary(rows: list[dict], path: str) -> list[dict]:
    """Mean, sd and 95% CI across replicate seeds, per (cell, policy)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(k) for k in SUMMARY_KEYS) + (row["policy"],)
        groups[key].append(row)

    out: list[dict] = []
    for key, group in sorted(groups.items(), key=lambda kv: [str(x) for x in kv[0]]):
        summary: dict = dict(zip(SUMMARY_KEYS + ["policy"], key))
        summary["n_seeds"] = len(group)
        summary["seeds"] = ";".join(str(g["seed"]) for g in sorted(group, key=lambda g: g["seed"] or 0))
        for column in METRIC_COLUMNS:
            values = [g[column] for g in group
                      if isinstance(g[column], (int, float)) and not math.isnan(float(g[column]))]
            if not values:
                summary[f"{column}.mean"] = ""
                summary[f"{column}.sd"] = ""
                summary[f"{column}.ci95"] = ""
                continue
            mean = statistics.mean(values)
            summary[f"{column}.mean"] = mean
            if len(values) > 1:
                sd = statistics.stdev(values)
                half = _t95(len(values) - 1) * sd / math.sqrt(len(values))
                summary[f"{column}.sd"] = sd
                summary[f"{column}.ci95"] = half
            else:
                # A single replicate carries no uncertainty estimate. Leave the
                # interval blank rather than printing 0, which would read as
                # "measured and found to be exactly zero".
                summary[f"{column}.sd"] = ""
                summary[f"{column}.ci95"] = ""
        out.append(summary)

    fields = SUMMARY_KEYS + ["policy", "n_seeds", "seeds"]
    for column in METRIC_COLUMNS:
        fields += [f"{column}.mean", f"{column}.sd", f"{column}.ci95"]
    _write_csv(path, fields, out)
    return out


def write_paired(rows: list[dict], path: str, baseline: str) -> list[dict]:
    """Per-seed percentage change vs `baseline`, paired within an experimental cell.

    A positive `pct_change` means the policy's metric is larger than the
    baseline's. For flow time smaller is better, so improvements are negative.
    """
    by_cell_seed: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        key = tuple(row.get(k) for k in CELL_KEYS) + (row["seed"],)
        by_cell_seed[key][row["policy"]] = row

    out: list[dict] = []
    for key, policies in sorted(by_cell_seed.items(), key=lambda kv: [str(x) for x in kv[0]]):
        base_row = policies.get(baseline)
        if base_row is None:
            continue
        for policy, row in sorted(policies.items()):
            if policy == baseline:
                continue
            entry: dict = dict(zip(CELL_KEYS + ["seed"], key))
            entry["baseline"] = baseline
            entry["policy"] = policy
            for column in METRIC_COLUMNS:
                a, b = base_row[column], row[column]
                ok = (isinstance(a, (int, float)) and isinstance(b, (int, float))
                      and not math.isnan(float(a)) and not math.isnan(float(b)) and a != 0)
                entry[f"{column}.pct_change"] = ((b - a) / a * 100.0) if ok else ""
            out.append(entry)

    fields = CELL_KEYS + ["seed", "baseline", "policy"] + [f"{c}.pct_change" for c in METRIC_COLUMNS]
    _write_csv(path, fields, out)
    return out


def aggregate_all(root: str, out_dir: str, baseline: str = "erf") -> dict:
    rows = load_runs(root)
    write_long(rows, os.path.join(out_dir, "results_long.csv"))
    summary = write_summary(rows, os.path.join(out_dir, "results_summary.csv"))
    paired = write_paired(rows, os.path.join(out_dir, "results_paired.csv"), baseline=baseline)
    return {"n_runs": len(rows), "n_summary_rows": len(summary), "n_paired_rows": len(paired)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aggregate simulation runs into paper tables")
    parser.add_argument("--runs", required=True, help="Directory containing run outputs")
    parser.add_argument("--out", required=True, help="Directory to write CSVs into")
    parser.add_argument("--baseline", default="erf", help="Policy used as the paired baseline")
    args = parser.parse_args()

    stats = aggregate_all(args.runs, args.out, baseline=args.baseline)
    print(f"aggregated {stats['n_runs']} runs -> {args.out}")
