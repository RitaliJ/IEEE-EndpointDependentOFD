# How to Run the Real-Data Experiment

## Required arguments

| Flag | Description | Example|
|------|-------------| ------ |
| `--csv <path>` | Path to the raw delivery CSV (Cainiao format) | oct_rounded.csv |
| `--output <dir>` | Directory to write all results into | experimental_result |
| `--seed <int>` | Random seed (controls driver placement and order timing) | 42 |

## Basic run

```
python -m mvp_sim.experiments.cainiao_data \
  --csv may_1_to_10_rounded.csv \
  --output experimental_results/ \
  --seed 42 \
  --no-per-driver-plots \
  --no-order-gantt
```

`--no-per-driver-plots` and `--no-order-gantt` skip the extremely slow plot generation. You should probably use these two arguments unless you have a really small synthetic dataset (like 6 drivers and less than 100 orders).

## Optional flags

| Flag | Description |
|------|-------------|
| `--no-per-driver-plots` | Skip per-driver PNG generation |
| `--no-order-gantt` | Skip order_gantt.png |
| `--sweep-sn` | Run SN at adjuster values specified at the top of the cainiao_data.py file |
| `--no-baselines` | Skips all policies except SN |
| `--driver-sweep` | Run all policies at driver fractions values specified at the top of the cianiao_data.py file` |

## Location of what policies to run
Make sure you do not have `--no-baselines` as an input argument.

If you have a new policy, first import it in the cainiao_data.py file in line 39. 

Then go to the `_build_policies` function in the file and find `policies += [...]`. Add your policy in the same format as the other policies there.

Before running the plot makers: plot_csvs.py and plot_driver_sweep.py, go to the top of each file and modify the following:

in plot_csvs.py, modify:
```COLORS, LABEL_MAP, POLICY_COLORS```

in plot_driver_sweep, modify:
```policies, policy_labels, COLORS```

## Output structure

```
<output>/
  prepared_data/          # intermediate JSON files produced from the CSV
    zones.json
    orders.json
    drivers.json
    cost_matrix.json
  cainiao_data/
    <policy_name>/        # one directory per policy run
      results.json
      timeline.txt
      plots/
```

For a driver sweep the results land under `cainiao_data_driver_sweep/frac_NNN/cainiao_data/<policy_name>/`.

## What the pipeline does

1. **`resturant_and_zone_maker`** — clusters unique pickup GPS coordinates with DBSCAN to produce zones and restaurants (`zones.json`).
2. **`order_maker`** — maps each CSV row to an order with destination zone (`orders.json`).
3. **`drivers_maker`** — collects unique courier IDs, computes a bounding box from zone centroids, and randomly places each driver within that box (seeded by `--seed`). The nearest centroid becomes the driver's starting zone (`drivers.json`).
4. **`cost_maker`** — builds a haversine distance matrix between zone centroids (`cost_matrix.json`).
5. **Simulation** — runs each policy over the prepared environment and writes metrics, event log, and plots.

---

## Plotting scripts

### `plot_csvs.py` — overlay multiple metric CSVs on one chart

Pass any number of single-metric CSV files (two columns: x, y). Each file becomes one line on the plot, labelled by its parent directory name. Saves `plot.png` in the current directory.

```
python3 plot_csvs.py \
  experimental_results/cainiao_data/eaf/flow_time_over_time.csv \
  experimental_results/cainiao_data/sn/flow_time_over_time.csv
```

### `plot_driver_sweep.py` — flow time vs. driver supply fraction

Reads `metrics.json` from every `frac_NNN/<policy>/` directory produced by `--driver-sweep` and plots average flow time against supply fraction for all policies. Saves output to `plots/flow_time_vs_supply.png`.

The `base_dir` path near the top of the file must point to your driver-sweep results directory — edit it before running.

#### Basic run first

```
python -m mvp_sim.experiments.cainiao_data 
--csv oct_rounded.csv 
--output experimental_results/
--seed 42 
--no-per-driver-plots 
--no-order-gantt 
--driver-sweep
```

#### analysis run

```
python plot_driver_sweep.py
```

### `plot_sn_cdf.py` — CDF of per-order flow times for the SN adjuster sweep

Requires results from a `--sweep-sn` run and an ERF baseline directory. Plots the CDF of per-order flow time for each SN adjuster value alongside ERF, with p90/p95 reference lines.

```
python plot_sn_cdf.py \
  --sweep-dir experimental_results/cainiao_data/ \
  --erf-dir   experimental_results/cainiao_data/erf \
  --out       flow_time_cdf.png
```

| Argument | Description |
|----------|-------------|
| `--sweep-dir` | Directory containing `sn_adj_*/` subdirectories (the `--sweep-sn` output) |
| `--erf-dir` | Directory containing ERF's `completed_orders.json` |
| `--out` | Output file path (default: `flow_time_cdf.png`) |
