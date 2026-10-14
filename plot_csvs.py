import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from pathlib import Path

COLORS = ["#2196F3", "#F44336", "#4CAF50", "#FF9800", "#9C27B0", "#00BCD4"]
LABEL_MAP = {
    "Eaf": "EAF",
    "Erf": "ERF",
    "Sn": "SN",
    # "Sn Noreposition": "SN No Reposition",
    "Calsnoweights": "CALS",
    # "Calsurgency": "CALS (urgency)",
    "Calscoverage": "CALS (coverage)",
    # "Calsmixed": "CALS (mixed)",
}
POLICY_COLORS = {
    "EAF": "#2196F3",
    "ERF": "#F44336",
    "Nearest Neighbor": "#4CAF50",
    "SN": "#FF9800",
    # "SN No Reposition": "#9C27B0",
    "CALS": "#607D8B",
    # "CALS (urgency)": "#E91E63",
    "CALS (coverage)": "#3F51B5",
    # "CALS (mixed)": "#009688",
}

def plot_csvs(csv_paths):
    mpl.rcParams.update({
        "font.family": "serif",
        "font.size": 16,
        "axes.titlesize": 20,
        "axes.labelsize": 18,
        "xtick.labelsize": 14,
        "ytick.labelsize": 14,
        "legend.fontsize": 14,
        "axes.linewidth": 1.5,
        "lines.linewidth": 2.5,
        "grid.linewidth": 0.8,
        "figure.dpi": 150,
    })

    fig, ax = plt.subplots(figsize=(10, 6))

    x_col = ""
    y_col = ""
    for i, path in enumerate(csv_paths):
        df = pd.read_csv(path)
        x_col = df.columns[0]
        y_col = df.columns[1]
        label = Path(path).parent.name.replace("_", " ").title()
        label = LABEL_MAP.get(label, label)
        color = POLICY_COLORS.get(label, COLORS[i % len(COLORS)])
        ax.plot(df[x_col], df[y_col], marker='o', label=label, color=color)

    ax.set_xlabel(x_col.replace("_", " ").title(), labelpad=10)
    ax.set_ylabel(y_col.replace("_", " ").title(), labelpad=10)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=True, framealpha=0.9, edgecolor="#cccccc")
    plt.tight_layout()
    plt.savefig("driver_util.png", dpi=200, bbox_inches="tight")
    print("Saved driver_util.png")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python plot_csvs.py <results_dir> [csv_filename]")
        print("  results_dir:  directory containing one subdir per policy")
        print("  csv_filename: CSV to plot from each policy dir (default: flow_time_over_time.csv)")
        sys.exit(1)

    results_dir = Path(sys.argv[1])
    csv_filename = sys.argv[2] if len(sys.argv) > 2 else "driver_utilization_over_time.csv"

    csv_paths = sorted(
        p / csv_filename
        for p in results_dir.iterdir()
        if p.is_dir() and (p / csv_filename).exists()
    )

    if not csv_paths:
        print(f"No '{csv_filename}' found under {results_dir}")
        sys.exit(1)

    print(f"Plotting {len(csv_paths)} policies: {[p.parent.name for p in csv_paths]}")
    plot_csvs(csv_paths)
