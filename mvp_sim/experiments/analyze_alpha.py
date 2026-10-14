"""Create a compact, reproducible cross-alpha sensitivity report.

Example:
    python -m mvp_sim.experiments.analyze_alpha \
      --suite 0.3=pilot_outputs/yt_alpha03_warmup05_seeds1-3_20260807 \
      --suite 0.5=pilot_outputs/yt_alpha05_warmup05_seeds1-3_20260807 \
      --suite 0.7=pilot_outputs/yt_alpha07_warmup05_seeds1-3_20260807 \
      --out reported_results/alpha_sensitivity
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict

import matplotlib.pyplot as plt

T95_DF2 = 4.303
POLICY_ORDER = [
    "sn_noreposition", "sn", "cals_noweights", "cals_coverage",
    "cals_urgency", "cals_mixed", "nearest_neighbor", "eaf", "erf",
]
LABEL = {
    "sn_noreposition": "SN, no reposition", "sn": "SN",
    "cals_noweights": "CALS, no weights", "cals_coverage": "CALS, coverage",
    "cals_urgency": "CALS, urgency", "cals_mixed": "CALS, mixed",
    "nearest_neighbor": "Nearest neighbor", "eaf": "EAF", "erf": "ERF",
}


def mean_ci(values: list[float]) -> tuple[float, float, float]:
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else float("nan")
    ci = T95_DF2 * sd / math.sqrt(len(values)) if len(values) == 3 else float("nan")
    return mean, sd, ci


def load(suites: dict[float, str]) -> dict[float, list[dict]]:
    data = {}
    for alpha, root in suites.items():
        path = os.path.join(root, "aggregate", "results_long.csv")
        with open(path) as f:
            rows = list(csv.DictReader(f))
        if len(rows) != 27:
            raise ValueError(f"expected 27 runs for alpha={alpha}, found {len(rows)}")
        for row in rows:
            if float(row["batch_alpha"]) != alpha:
                raise ValueError(f"alpha mismatch in {row['run_dir']}")
        data[alpha] = rows
    return data


def indexed(data: dict[float, list[dict]], metric: str) -> dict[tuple, float]:
    return {
        (alpha, row["policy"], int(row["seed"])): float(row[metric])
        for alpha, rows in data.items() for row in rows
    }


def plot_metric(data, metric, ylabel, filename, out, *, percent=False):
    values = indexed(data, metric)
    alphas = sorted(data)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for policy in POLICY_ORDER:
        means, cis = [], []
        for alpha in alphas:
            seed_values = [values[alpha, policy, seed] for seed in (1, 2, 3)]
            mean, _sd, ci = mean_ci(seed_values)
            means.append(mean * (100 if percent else 1))
            cis.append(ci * (100 if percent else 1))
            ax.scatter([alpha] * 3,
                       [v * (100 if percent else 1) for v in seed_values],
                       s=13, alpha=0.35)
        ax.errorbar(alphas, means, yerr=cis, marker="o", capsize=3,
                    linewidth=1.4, label=LABEL[policy])
    ax.set(xlabel="Batch exponent α", ylabel=ylabel, xticks=alphas)
    ax.grid(alpha=0.25)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, filename), dpi=180)
    plt.close(fig)


def plot_paired(data, out):
    flow = indexed(data, "flow_time.avg")
    alphas = sorted(data)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for policy in POLICY_ORDER:
        if policy == "erf":
            continue
        means, cis = [], []
        for alpha in alphas:
            changes = [
                100 * (flow[alpha, policy, seed] / flow[alpha, "erf", seed] - 1)
                for seed in (1, 2, 3)
            ]
            mean, _sd, ci = mean_ci(changes)
            means.append(mean)
            cis.append(ci)
            ax.scatter([alpha] * 3, changes, s=13, alpha=0.35)
        ax.errorbar(alphas, means, yerr=cis, marker="o", capsize=3,
                    linewidth=1.4, label=LABEL[policy])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set(xlabel="Batch exponent α", ylabel="Mean flow-time change vs ERF (%)",
           xticks=alphas)
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "paired_flow_difference_vs_alpha.png"), dpi=180)
    plt.close(fig)


def plot_ranks(data, out):
    flow = indexed(data, "flow_time.avg")
    alphas = sorted(data)
    per_policy = defaultdict(lambda: defaultdict(list))
    for alpha in alphas:
        for seed in (1, 2, 3):
            ordered = sorted(POLICY_ORDER, key=lambda p: flow[alpha, p, seed])
            for rank, policy in enumerate(ordered, 1):
                per_policy[policy][alpha].append(rank)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for policy in POLICY_ORDER:
        means, cis = [], []
        for alpha in alphas:
            ranks = per_policy[policy][alpha]
            mean, _sd, ci = mean_ci(ranks)
            means.append(mean)
            cis.append(ci)
            ax.scatter([alpha] * 3, ranks, s=13, alpha=0.35)
        ax.errorbar(alphas, means, yerr=cis, marker="o", capsize=3,
                    linewidth=1.4, label=LABEL[policy])
    ax.set(xlabel="Batch exponent α", ylabel="Flow-time rank (1 = best)",
           xticks=alphas, yticks=range(1, 10))
    ax.invert_yaxis()
    ax.grid(alpha=0.25)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "policy_rank_vs_alpha.png"), dpi=180)
    plt.close(fig)


def write_stats(data, out):
    flow = indexed(data, "flow_time.avg")
    fields = [
        "policy", "alpha", "n_seeds", "flow_mean", "flow_sd", "flow_ci95",
        "alpha07_minus_alpha03_mean", "alpha07_minus_alpha03_sd",
        "alpha07_minus_alpha03_ci95", "alpha_effect_pct_of_alpha05_mean",
        "alpha_effect_to_mean_within_alpha_sd",
    ]
    rows = []
    for policy in POLICY_ORDER:
        differences = [flow[0.7, policy, s] - flow[0.3, policy, s] for s in (1, 2, 3)]
        diff_mean, diff_sd, diff_ci = mean_ci(differences)
        within_sds = []
        for alpha in sorted(data):
            within_sds.append(statistics.stdev(flow[alpha, policy, s] for s in (1, 2, 3)))
        alpha05_mean = statistics.mean(flow[0.5, policy, s] for s in (1, 2, 3))
        for alpha in sorted(data):
            mean, sd, ci = mean_ci([flow[alpha, policy, s] for s in (1, 2, 3)])
            rows.append({
                "policy": policy, "alpha": alpha, "n_seeds": 3,
                "flow_mean": mean, "flow_sd": sd, "flow_ci95": ci,
                "alpha07_minus_alpha03_mean": diff_mean,
                "alpha07_minus_alpha03_sd": diff_sd,
                "alpha07_minus_alpha03_ci95": diff_ci,
                "alpha_effect_pct_of_alpha05_mean": 100 * diff_mean / alpha05_mean,
                "alpha_effect_to_mean_within_alpha_sd": (
                    diff_mean / statistics.mean(within_sds)
                    if statistics.mean(within_sds) else float("inf")
                ),
            })
    with open(os.path.join(out, "alpha_statistics.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", action="append", required=True,
                        help="ALPHA=SUITE_ROOT; repeat once per alpha")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    suites = {}
    for item in args.suite:
        alpha, root = item.split("=", 1)
        suites[float(alpha)] = root
    if set(suites) != {0.3, 0.5, 0.7}:
        raise SystemExit("expected exactly alpha 0.3, 0.5, and 0.7")
    os.makedirs(args.out, exist_ok=True)
    data = load(suites)
    write_stats(data, args.out)
    plot_metric(data, "flow_time.avg", "Mean order flow time",
                "flow_time_vs_alpha.png", args.out)
    plot_metric(data, "driver_utilization_makespan.avg",
                "Makespan-based driver utilization", "utilization_vs_alpha.png", args.out)
    plot_metric(data, "runtime_seconds", "End-to-end runtime (seconds)",
                "runtime_vs_alpha.png", args.out)
    plot_paired(data, args.out)
    plot_ranks(data, args.out)


if __name__ == "__main__":
    main()
