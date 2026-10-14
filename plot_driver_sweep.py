import json
import os
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np

### MODIFY THIS
base_dir = "/home/jinhuangzhou/cs145/ds_oct_results_sh/cainiao_data_driver_sweep"
fractions = ["010", "025", "050", "075", "100"]
frac_values = [10, 25, 50, 75, 100]
policies = ["eaf", "erf", "nearest_neighbor", "sn", "calsnoweights", "calscoverage"]
policy_labels = {
    "eaf": "EAF",
    "erf": "ERF",
    "nearest_neighbor": "Nearest Neighbor",
    "sn": "SN",
    # "sn_NoReposition": "SN No Reposition",
    "calsnoweights": "CALS",
    # "calsurgency": "CALS (urgency)",
    "calscoverage": "CALS (coverage)",
    # "calsmixed": "CALS (mixed)",
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
FALLBACK_COLORS = ["#2196F3", "#F44336", "#4CAF50", "#FF9800", "#9C27B0", "#00BCD4"]

# Apply beautiful styles
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


def format_ax(ax):
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=True, framealpha=0.9, edgecolor="#cccccc")


data = {p: {'flow_time': [], 'undelivered': [], 'utilization': [], 'batch_size': []} for p in policies}

for frac in fractions:
    for p in policies:
        metrics_file = os.path.join(base_dir, f"frac_{frac}", "cainiao_data", p, "metrics.json")
        try:
            with open(metrics_file, 'r') as f:
                metrics = json.load(f)
                
            data[p]['flow_time'].append(metrics['flow_time']['avg'])
            undelivered_pct = (metrics['undelivered_orders'] / metrics['total_orders']) * 100
            data[p]['undelivered'].append(undelivered_pct)
            data[p]['utilization'].append(metrics['driver_utilization']['avg'])
            data[p]['batch_size'].append(metrics['avg_batch_size'])
        except Exception as e:
            print(f"Error loading {metrics_file}: {e}")
            data[p]['flow_time'].append(None)
            data[p]['undelivered'].append(None)
            data[p]['utilization'].append(None)
            data[p]['batch_size'].append(None)

# Create plots directory if it doesn't exist
plot_dir = "/home/jinhuangzhou/cs145/plots"
os.makedirs(plot_dir, exist_ok=True)

# 1. Flow time line plot
fig, ax = plt.subplots(figsize=(10, 6))
for i, p in enumerate(policies):
    label = policy_labels[p]
    color = POLICY_COLORS.get(label, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
    ax.plot(frac_values, data[p]['flow_time'], marker='o', label=label, color=color)
ax.set_xlabel("Supply Fraction (%)", labelpad=10)
ax.set_ylabel("Avg Flow Time (min)", labelpad=10)
format_ax(ax)
plt.tight_layout()
plt.savefig(os.path.join(plot_dir, "flow_time_vs_supply.png"), dpi=200, bbox_inches="tight")
plt.close()

print("Plots generated successfully in", plot_dir)
