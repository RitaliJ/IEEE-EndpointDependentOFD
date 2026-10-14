# Alpha-sensitivity pilot

This directory contains the small, commit-safe record of the Yantai
alpha-sensitivity pilot. Raw run artifacts are intentionally excluded from Git
under `pilot_outputs/`.

## Purpose and conclusion

The pilot checks whether the main policy ordering is sensitive to the exponent
in the sublinear service model

```text
tau(i,j,k) = D[z(i),j] + c(j) k^alpha.
```

The tested values were `alpha = 0.3, 0.5, 0.7`. All 81 runs completed, every
arrived order was delivered, and every suite passed all 8 validation checks.
The broad ordering was stable. `alpha = 0.5` remains the central default for the
full experiment suite.

## Frozen configuration

| setting | value |
| --- | --- |
| city | Yantai (`yt`) |
| raw data subset | June 10 (`ds=0610`) |
| source rows retained by subset | 1,051 |
| zones / restaurants / drivers | 36 / 278 / 99 |
| fleet fraction | 1.0 (all 99 drivers) |
| seeds | 1, 2, 3 |
| policies | ERF, EAF, nearest neighbor, four CALS variants, SN, SN without repositioning |
| cost function | `sublinear_intrazone` |
| beta | 0.714 |
| alpha values | 0.3, 0.5, 0.7 |
| warm-up | first 5% of each seed's arrival horizon |
| resolved warm-up durations | 1.60, 1.75, 1.50 minutes for seeds 1, 2, 3 |
| post-warm-up order counts | 725, 699, 718 for seeds 1, 2, 3 |
| speed | 1.0 km/min |
| cost-matrix diagonal | 0.0 |
| SN adjuster | 1.0 |
| paired baseline | ERF |

The three suites used identical trace and roster hashes for a given seed. Only
`batch_alpha` changed.

## Exact commands executed

The pilot read the locally available dataset from the teammate checkout without
writing to it:

```bash
MPLCONFIGDIR=/tmp/cs145-mpl .venv/bin/python -m mvp_sim.experiments.run_suite \
  --output pilot_outputs/yt_alpha03_warmup05_seeds1-3_20260807 \
  --data-root ../cs145-new --cities yt --seeds 1 2 3 --fractions 1.0 \
  --day 0610 --warmup-fraction 0.05 --cost-function sublinear_intrazone \
  --batch-alpha 0.3 --speed 1.0 --baseline erf --jobs 4

MPLCONFIGDIR=/tmp/cs145-mpl .venv/bin/python -m mvp_sim.experiments.run_suite \
  --output pilot_outputs/yt_alpha05_warmup05_seeds1-3_20260807 \
  --data-root ../cs145-new --cities yt --seeds 1 2 3 --fractions 1.0 \
  --day 0610 --warmup-fraction 0.05 --cost-function sublinear_intrazone \
  --batch-alpha 0.5 --speed 1.0 --baseline erf --jobs 4

MPLCONFIGDIR=/tmp/cs145-mpl .venv/bin/python -m mvp_sim.experiments.run_suite \
  --output pilot_outputs/yt_alpha07_warmup05_seeds1-3_20260807 \
  --data-root ../cs145-new --cities yt --seeds 1 2 3 --fractions 1.0 \
  --day 0610 --warmup-fraction 0.05 --cost-function sublinear_intrazone \
  --batch-alpha 0.7 --speed 1.0 --baseline erf --jobs 4
```

For a canonical checkout containing `data/delivery/delivery_yt.csv`, replace
`--data-root ../cs145-new` with `--data-root .`.

## Validation evidence

Each alpha suite reported:

- 27 unique runs matching its manifest;
- identical trace, arrival count, horizon, and roster across policies;
- utilization within `[0,1]`;
- identical cost parameters within comparison cells;
- balanced completion accounting;
- no unfinished orders;
- **8/8 checks passed**;
- 24 paired comparisons: three seeds times eight non-ERF policies.

Total: 81/81 successful runs and 72/72 expected paired comparisons.

## Results

`mean_flow_time.csv` records the mean of each policy's three seed-level mean flow
times. Lower is better.

The main ordering was stable: SN without repositioning ranked first at all three
alpha values; SN and unweighted CALS occupied the next two positions; the three
greedy baselines remained the bottom three. Fine ordering between SN and
unweighted CALS, and among the greedy baselines, was not stable enough to support
strong comparative claims.

## Statistical analysis

All aggregate means use the three seed-level values. Error bars in the figures
are two-sided 95% t intervals with 2 degrees of freedom (`t = 4.303`); translucent
points show the individual seeds. With only three seeds these intervals are
appropriately wide, so the pilot supports robustness conclusions rather than
precise population estimates.

The paired `alpha=0.7` minus `alpha=0.3` effect is consistent for the batching-
oriented policies:

| policy | paired mean increase | % of alpha=0.5 mean | effect / typical seed SD | paired 95% CI half-width |
| --- | ---: | ---: | ---: | ---: |
| SN, no reposition | 10.56 | 16.7% | 6.62 | 2.99 |
| SN | 9.98 | 14.9% | 11.81 | 1.94 |
| CALS, no weights | 11.58 | 17.3% | 4.84 | 1.10 |
| CALS, coverage | 11.48 | 16.4% | 3.70 | 0.98 |
| CALS, urgency | 11.90 | 15.1% | 6.55 | 2.11 |
| CALS, mixed | 13.15 | 16.1% | 8.24 | 1.96 |

For nearest neighbor, EAF, and ERF, the corresponding change is only 4.7–5.1%
of the alpha=0.5 mean and 0.14–0.16 times typical seed variation. Their paired
95% intervals include zero. Alpha therefore changes the numerical service burden
materially for SN/CALS, but the main policy categories and scientific ordering
remain stable. It should be reported as a robustness check, not multiplied across
every cell of the full suite.

Horizon-based utilization remains near saturation (`0.947–1.000`). The more
informative makespan-based utilization is plotted. Runtime is effectively
unchanged across alpha: individual end-to-end runs range from approximately
0.074 to 0.162 seconds in these no-plot pilot suites.

## Diagnostic figures and data

- [`flow_time_vs_alpha.png`](flow_time_vs_alpha.png): flow time by policy;
- [`utilization_vs_alpha.png`](utilization_vs_alpha.png): makespan-based utilization;
- [`runtime_vs_alpha.png`](runtime_vs_alpha.png): persisted end-to-end runtime;
- [`paired_flow_difference_vs_alpha.png`](paired_flow_difference_vs_alpha.png):
  seed-paired percentage difference from ERF;
- [`policy_rank_vs_alpha.png`](policy_rank_vs_alpha.png): seed-level and mean rank;
- [`alpha_statistics.csv`](alpha_statistics.csv): means, standard deviations,
  95% intervals, paired endpoint effects, and effect-to-seed-variability ratios.

The figures and statistics are reproducible from the ignored raw artifacts with:

```bash
MPLCONFIGDIR=/tmp/cs145-mpl .venv/bin/python \
  -m mvp_sim.experiments.analyze_alpha \
  --suite 0.3=pilot_outputs/yt_alpha03_warmup05_seeds1-3_20260807 \
  --suite 0.5=pilot_outputs/yt_alpha05_warmup05_seeds1-3_20260807 \
  --suite 0.7=pilot_outputs/yt_alpha07_warmup05_seeds1-3_20260807 \
  --out reported_results/alpha_sensitivity
```

## Provenance limitation

These are debugging-pilot results, not publication results. Their manifests
record base commit `1a940d2443bc396e6a1367b881ae16c4991db8f9` and correctly flag
that the working tree was dirty because the integration changes had not yet been
committed. The full suite must be run from a clean committed revision.
