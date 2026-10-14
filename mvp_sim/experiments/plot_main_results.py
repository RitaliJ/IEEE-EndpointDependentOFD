"""Generate the compact main-paper results figure from frozen outputs.

This script reads the validated run-level aggregate and does not rerun or alter
any experiment.  It writes a vector PDF, a review PNG, and the 25-cell source
table used by the figure.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import pandas as pd


CITIES = ["cq", "hz", "jl", "sh", "yt"]
CITY_LABELS = {
    "cq": "Chongqing",
    "hz": "Hangzhou",
    "jl": "Jilin",
    "sh": "Shanghai",
    "yt": "Yantai",
}
SUPPLY = [0.10, 0.25, 0.50, 0.75, 1.00]
SUPPLY_LABELS = ["10", "25", "50", "75", "100"]
WINNER_LABELS = {
    "cals_noweights": "CALS–\nNW",
    "sn_noreposition": "SN–NR",
}


def _figure_data(data: pd.DataFrame) -> pd.DataFrame:
    keys = ["city", "seed", "supply_fraction"]
    erf = data[data.policy == "erf"][keys + ["flow_time.avg"]].rename(
        columns={"flow_time.avg": "erf_flow_time"}
    )
    cals = data[data.policy == "cals_noweights"][keys + ["flow_time.avg"]].rename(
        columns={"flow_time.avg": "cals_nw_flow_time"}
    )
    paired = cals.merge(erf, on=keys, validate="one_to_one")
    paired["cals_nw_improvement_pct"] = 100 * (
        paired.erf_flow_time - paired.cals_nw_flow_time
    ) / paired.erf_flow_time

    counts = paired.groupby(["city", "supply_fraction"]).seed.nunique()
    if len(paired) != 75 or len(counts) != 25 or not counts.eq(3).all():
        raise ValueError("expected 25 cells with exactly three matched seeds each")
    if not paired.cals_nw_improvement_pct.gt(0).all():
        raise ValueError("CALS–NW does not improve on ERF in every matched run")

    improvements = paired.groupby(
        ["city", "supply_fraction"], as_index=False
    ).cals_nw_improvement_pct.agg(["mean", "std", "count"])
    improvements = improvements.rename(columns={
        "mean": "cals_nw_improvement_pct_mean",
        "std": "cals_nw_improvement_pct_sd",
        "count": "matched_seed_count",
    })

    means = data.groupby(
        ["city", "supply_fraction", "policy"], as_index=False
    )["flow_time.avg"].mean()
    winners = means.loc[
        means.groupby(["city", "supply_fraction"])["flow_time.avg"].idxmin()
    ].rename(columns={"policy": "winner", "flow_time.avg": "winner_flow_time_mean"})
    result = improvements.merge(
        winners, on=["city", "supply_fraction"], validate="one_to_one"
    )
    unexpected = set(result.winner) - set(WINNER_LABELS)
    if unexpected:
        raise ValueError(f"unexpected winning policies: {sorted(unexpected)}")
    return result.sort_values(["city", "supply_fraction"])


def _matrix(frame: pd.DataFrame, column: str) -> np.ndarray:
    return (
        frame.pivot(index="city", columns="supply_fraction", values=column)
        .reindex(index=CITIES, columns=SUPPLY)
        .to_numpy()
    )


def plot(frame: pd.DataFrame, output_stem: Path) -> None:
    mpl.rcParams.update({
        "font.family": "serif",
        "font.size": 8,
        "axes.titlesize": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, (ax_a, ax_b) = plt.subplots(
        1, 2, figsize=(7.16, 2.55), gridspec_kw={"width_ratios": [1.15, 1.0]}
    )

    improvement = _matrix(frame, "cals_nw_improvement_pct_mean").astype(float)
    image_a = ax_a.imshow(improvement, cmap="Greys", vmin=0, vmax=60, aspect="auto")
    for row in range(improvement.shape[0]):
        for col in range(improvement.shape[1]):
            value = improvement[row, col]
            color = "white" if value >= 35 else "black"
            ax_a.text(col, row, f"{value:.1f}%", ha="center", va="center",
                      fontsize=7.2, color=color)
    ax_a.set_title("(a) CALS–NW mean flow-time reduction vs. ERF", fontweight="bold")

    winner_names = _matrix(frame, "winner")
    winner_code = np.vectorize({"cals_noweights": 0, "sn_noreposition": 1}.get)(winner_names)
    winner_cmap = ListedColormap(["#f2f2f2", "#595959"])
    winner_norm = BoundaryNorm([-0.5, 0.5, 1.5], winner_cmap.N)
    ax_b.imshow(winner_code, cmap=winner_cmap, norm=winner_norm, aspect="auto")
    for row in range(winner_names.shape[0]):
        for col in range(winner_names.shape[1]):
            label = WINNER_LABELS[winner_names[row, col]]
            color = "white" if winner_code[row, col] == 1 else "black"
            ax_b.text(col, row, label, ha="center", va="center",
                      fontsize=7.2, fontweight="bold", color=color)
    ax_b.set_title("(b) Policy with lowest 3-seed mean flow time", fontweight="bold")

    for ax in (ax_a, ax_b):
        ax.set_xticks(range(len(SUPPLY)), SUPPLY_LABELS)
        ax.set_yticks(range(len(CITIES)), [CITY_LABELS[c] for c in CITIES])
        ax.set_xlabel("Fleet supply (% of full roster)")
        ax.set_xticks(np.arange(-0.5, len(SUPPLY), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(CITIES), 1), minor=True)
        ax.grid(which="minor", color="black", linewidth=0.45)
        ax.tick_params(which="minor", bottom=False, left=False)
        ax.tick_params(length=0)
    ax_b.tick_params(labelleft=False)

    colorbar = fig.colorbar(image_a, ax=ax_a, fraction=0.047, pad=0.025)
    colorbar.set_label("Reduction (%)", fontsize=7)
    colorbar.ax.tick_params(labelsize=7)
    fig.subplots_adjust(left=0.105, right=0.985, bottom=0.19, top=0.86, wspace=0.28)
    save_options = {"bbox_inches": "tight", "facecolor": "white", "transparent": False}
    fig.savefig(output_stem.with_suffix(".pdf"), **save_options)
    fig.savefig(output_stem.with_suffix(".png"), dpi=300, **save_options)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results",
        default="results/canonical_alpha05_warmup05/aggregate/results_long.csv",
    )
    parser.add_argument(
        "--output-stem",
        default="reported_results/canonical_alpha05_warmup05/main_results_figure",
    )
    args = parser.parse_args()
    output_stem = Path(args.output_stem)
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    frame = _figure_data(pd.read_csv(args.results))
    frame.to_csv(output_stem.with_name(output_stem.name + "_data.csv"), index=False)
    plot(frame, output_stem)


if __name__ == "__main__":
    main()
