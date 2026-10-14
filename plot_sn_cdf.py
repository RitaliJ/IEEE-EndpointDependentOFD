"""
CDF of per-order flow times: SN adjuster sweep + ERF baseline.

Usage:
    python -m plot_sn_cdf \
        --sweep-dir <path>/cainiao_data_sn_adjuster_sweep/cainiao_data \
        --erf-dir   <path>/cainiao_data_default_10/erf \
"""

import argparse
import json
import os

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


def load_flow_times(results_dir: str) -> np.ndarray:
    path = os.path.join(results_dir, "completed_orders.json")
    with open(path) as f:
        orders = json.load(f)
    return np.array([o["completion_time"] - o["arrival_time"] for o in orders])


def cdf(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    xs = np.sort(values)
    ys = np.arange(1, len(xs) + 1) / len(xs)
    return xs, ys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep-dir", required=True,
                        help="Directory containing sn_adj_*/ subdirectories")
    parser.add_argument("--erf-dir", required=True,
                        help="Directory containing ERF completed_orders.json")
    parser.add_argument("--out", default="flow_time_cdf.png",
                        help="Output file path (PDF or PNG)")
    args = parser.parse_args()

    # --- collect SN runs ---
    sn_dirs = sorted(
        d for d in os.listdir(args.sweep_dir)
        if d.startswith("sn_adj_")
    )

    # color ramp: light → dark blue for increasing adjuster
    sn_colors = plt.cm.Blues(np.linspace(0.35, 0.90, len(sn_dirs)))

    fig, ax = plt.subplots(figsize=(7, 4.5))

    for color, subdir in zip(sn_colors, sn_dirs):
        adj_label = subdir.replace("sn_adj_", "")
        ft = load_flow_times(os.path.join(args.sweep_dir, subdir))
        xs, ys = cdf(ft)
        ax.plot(xs, ys, color=color, linewidth=1.8, label=f"SN  α={adj_label}")

    # --- ERF baseline ---
    ft_erf = load_flow_times(args.erf_dir)
    xs_erf, ys_erf = cdf(ft_erf)
    ax.plot(xs_erf, ys_erf, color="#d62728", linewidth=2.0,
            linestyle="--", label="ERF (baseline)")

    # --- p90 / p95 reference lines ---
    for p, ls in [(90, ":"), (95, "--")]:
        ax.axhline(p / 100, color="grey", linewidth=0.8, linestyle=ls, alpha=0.6)
        ax.text(ax.get_xlim()[1] if ax.get_xlim()[1] > 0 else 1,
                p / 100 + 0.007, f"p{p}", fontsize=7, color="grey", ha="right")

    ax.set_xlabel("Flow time (time units)", fontsize=11)
    ax.set_ylabel("Fraction of orders delivered", fontsize=11)
    ax.set_title("CDF of Per-Order Flow Time: SN Adjuster Sweep vs. ERF", fontsize=12)
    ax.set_ylim(0, 1.02)
    ax.set_xlim(left=0)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.legend(fontsize=9, loc="lower right", framealpha=0.85)
    ax.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    fig.savefig(args.out, dpi=180, bbox_inches="tight")
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
