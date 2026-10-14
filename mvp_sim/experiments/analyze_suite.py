"""Create commit-ready tables and figures from a validated frozen suite.

Example:
    python -m mvp_sim.experiments.analyze_suite \
      --suite results/canonical_alpha05_warmup05 \
      --out reported_results/canonical_alpha05_warmup05
"""

from __future__ import annotations

import argparse
import json
import os

import matplotlib.pyplot as plt
import pandas as pd


POLICY_ORDER = [
    "erf", "eaf", "nearest_neighbor", "cals_noweights", "cals_urgency",
    "cals_coverage", "cals_mixed", "sn", "sn_noreposition",
]
LABEL = {
    "erf": "ERF", "eaf": "EAF", "nearest_neighbor": "Nearest neighbor",
    "cals_noweights": "CALS, no weights", "cals_urgency": "CALS, urgency",
    "cals_coverage": "CALS, coverage", "cals_mixed": "CALS, mixed",
    "sn": "SN", "sn_noreposition": "SN, no reposition",
}
CITY_LABEL = {"cq": "Chongqing", "hz": "Hangzhou", "jl": "Jilin",
              "sh": "Shanghai", "yt": "Yantai"}
T95_DF2 = 4.303


def _flatten_columns(frame: pd.DataFrame) -> None:
    frame.columns = [
        ".".join(str(part) for part in column if part).rstrip(".")
        if isinstance(column, tuple) else str(column)
        for column in frame.columns
    ]


def _load(suite: str) -> tuple[pd.DataFrame, dict]:
    with open(os.path.join(suite, "manifest.json")) as f:
        manifest = json.load(f)
    validation = os.path.join(suite, "validation_report.md")
    with open(validation) as f:
        report = f.read()
    if "**8/8 checks passed.**" not in report:
        raise ValueError(f"suite is not fully validated: {validation}")
    data = pd.read_csv(os.path.join(suite, "aggregate", "results_long.csv"))
    expected = (len(manifest["cities"]) * len(manifest["seeds"])
                * len(manifest["supply_fractions"]) * len(manifest["policies"]))
    if len(data) != expected:
        raise ValueError(f"expected {expected} rows, found {len(data)}")
    return data, manifest


def _summaries(data: pd.DataFrame, out: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ["city", "supply_fraction", "num_drivers", "policy"]
    metrics = ["flow_time.avg", "flow_time.p95", "driver_utilization_makespan.avg",
               "runtime_seconds", "delivered_orders"]
    summary = data.groupby(keys, as_index=False)[metrics].agg(["mean", "std", "count"])
    _flatten_columns(summary)
    summary.to_csv(os.path.join(out, "policy_by_city_supply.csv"), index=False)

    baseline = data[data.policy == "erf"][
        ["city", "seed", "supply_fraction", "flow_time.avg"]
    ].rename(columns={"flow_time.avg": "erf_flow_time"})
    paired = data.merge(baseline, on=["city", "seed", "supply_fraction"],
                        validate="many_to_one")
    paired["flow_time_improvement_pct"] = (
        100 * (paired["erf_flow_time"] - paired["flow_time.avg"])
        / paired["erf_flow_time"]
    )
    paired = paired[paired.policy != "erf"]
    paired_summary = paired.groupby(
        ["city", "supply_fraction", "policy"], as_index=False
    )["flow_time_improvement_pct"].agg(["mean", "std", "count"])
    _flatten_columns(paired_summary)
    paired_summary.rename(columns={
        stat: f"flow_time_improvement_pct.{stat}"
        for stat in ("mean", "std", "count")
    }, inplace=True)
    paired_summary.to_csv(os.path.join(out, "paired_flow_improvement.csv"), index=False)
    return summary, paired_summary


def _plot_grid(data: pd.DataFrame, metric: str, ylabel: str, path: str,
               policies: list[str] = POLICY_ORDER) -> None:
    cities = list(CITY_LABEL)
    fig, axes = plt.subplots(2, 3, figsize=(12, 7), sharex=True)
    for ax, city in zip(axes.flat, cities):
        city_data = data[data.city == city]
        for policy in policies:
            part = city_data[city_data.policy == policy]
            grouped = part.groupby("supply_fraction")[metric]
            mean, sem = grouped.mean(), grouped.sem()
            ax.errorbar(mean.index, mean, yerr=T95_DF2 * sem, marker="o", markersize=3,
                        capsize=2, linewidth=1.1, label=LABEL[policy])
        ax.set_title(CITY_LABEL[city])
        ax.grid(alpha=0.25)
    axes.flat[-1].axis("off")
    for ax in axes[-1, :2]:
        ax.set_xlabel("Driver supply fraction")
    for ax in axes[:, 0]:
        ax.set_ylabel(ylabel)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    axes.flat[-1].legend(handles, labels, loc="center", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _plot_paired(data: pd.DataFrame, path: str) -> None:
    baseline = data[data.policy == "erf"][["city", "seed", "supply_fraction",
                                            "flow_time.avg"]].rename(
        columns={"flow_time.avg": "baseline"})
    paired = data.merge(baseline, on=["city", "seed", "supply_fraction"])
    paired = paired[paired.policy != "erf"].copy()
    paired["improvement"] = 100 * (paired.baseline - paired["flow_time.avg"]) / paired.baseline
    _plot_grid(paired, "improvement", "Mean flow-time improvement vs ERF (%)", path,
               [p for p in POLICY_ORDER if p != "erf"])


def _write_readme(data: pd.DataFrame, manifest: dict, out: str) -> None:
    full = data[data.supply_fraction == 1.0]
    ranking = full.groupby("policy")["flow_time.avg"].mean().sort_values()
    best = ranking.index[0]
    worst_runtime = data.groupby("policy")["runtime_seconds"].mean().sort_values().index[-1]
    text = f"""# Frozen full-suite analysis

Generated from commit `{manifest['code_commit']}` and the validated suite
`canonical_alpha05_warmup05` without rerunning simulations.

Reproduce from the repository root:

```bash
MPLCONFIGDIR=/tmp/cs145-mpl .venv/bin/python -m mvp_sim.experiments.analyze_suite \\
  --suite results/canonical_alpha05_warmup05 \\
  --out reported_results/canonical_alpha05_warmup05
```

## Scope

- Cities: {', '.join(CITY_LABEL[c] for c in manifest['cities'])}
- Day: `{manifest['data_day']}`; seeds: {manifest['seeds']}
- Driver supply: {manifest['supply_fractions']}
- Policies: {len(manifest['policies'])}; runs: {len(data)}
- Alpha: {manifest['batch_alpha']}; warm-up: first {100 * manifest['warmup_fraction']:.0f}%
- All 8 validation checks passed and every arrived order completed.

## Reading the artifacts

`flow_time_by_supply.png` is the primary outcome figure. `paired_flow_improvement.png`
uses ERF as the within-city, within-seed, within-fleet baseline; positive values mean
lower flow time. `utilization_by_supply.png` uses makespan-based utilization.
The CSVs retain the underlying means, standard deviations, replicate counts, and
paired percentage changes.

Across cities at full fleet, the lowest unweighted mean flow time is
**{LABEL[best]}**. The largest mean runtime across all experimental cells is from
**{LABEL[worst_runtime]}**. These summaries weight cities equally only after the
run-level results are grouped; paper claims should preferably report city-specific
paired effects rather than a single pooled headline number.

Error bars are two-sided 95% t intervals (`t₂ = 4.303`) based on only three seeds
and should be presented as uncertainty indicators, not strong inferential evidence.
"""
    with open(os.path.join(out, "README.md"), "w") as f:
        f.write(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    data, manifest = _load(args.suite)
    _summaries(data, args.out)
    _plot_grid(data, "flow_time.avg", "Mean order flow time (minutes)",
               os.path.join(args.out, "flow_time_by_supply.png"))
    _plot_grid(data, "driver_utilization_makespan.avg", "Makespan-based utilization",
               os.path.join(args.out, "utilization_by_supply.png"))
    _plot_paired(data, os.path.join(args.out, "paired_flow_improvement.png"))
    _write_readme(data, manifest, args.out)


if __name__ == "__main__":
    main()
