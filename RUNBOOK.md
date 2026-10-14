# Experiment runbook

Everything needed to regenerate the paper's numerical results.

## Getting the data

`delivery_jl.csv` and `delivery_yt.csv` are committed, so Jilin and Yantai run out
of the box. The Chongqing, Hangzhou and Shanghai raw CSVs are 138-273 MB each,
over GitHub's 100 MB hard limit, so they are gitignored — re-download them from
the public LaDe dataset (the paper's reference [7]) or copy them from a teammate
into `data/delivery/`. The full exclusion list is in `.gitignore`.

## Run the canonical suite

```bash
python -m mvp_sim.experiments.run_suite --output results/canonical --seeds 1 2 3 --driver-sweep --jobs 8
```

That is the whole thing: 5 cities x 3 seeds x 5 supply levels x 9 policies = 675
runs, writing about 250 MB.

**Budget 30-45 minutes on 8 cores, and do not kill it when it stalls at 673/675.**
Most runs finish in under 6 seconds, but two cells take 20+ minutes each and hold
~1 GB of RSS apiece. They are the same two on every run:

    sh/seed3/frac075/nearest_neighbor
    sh/seed3/frac100/eaf

ERF, EAF and NN scan every restaurant for every idle driver on every dispatch
decision, so their cost grows like `orders x idle_drivers x restaurants`. Shanghai
has the largest fleet (461 drivers against 406 restaurants), so it is worst there.
Memory oscillates rather than growing without bound — the process is working, not
hung. Give it at least 4 GB of headroom if you lower `--jobs`. Speeding those
policies up (indexing restaurants with ready work, instead of rescanning all of
them) is the obvious follow-up, but it changes no results, so it was left alone.

If you need a faster turnaround, `--cities cq hz sh` covers the three cities that
fall inside the paper's stated `Z < D ~ R` regime, and dropping `--driver-sweep`
cuts the run count by 5x.

It produces:

| path | what it is |
| --- | --- |
| `manifest.json` | code commit, data subset, seeds, policies and all their parameters |
| `scenarios/<city>_seed<S>.json` | the exact order trace and driver roster each replicate replayed |
| `runs/<city>/seed<S>/frac<PPP>/<policy>/` | per-run metrics and config |
| `aggregate/results_long.csv` | one row per run |
| `aggregate/results_summary.csv` | mean / sd / 95% CI across the 3 seeds |
| `aggregate/results_paired.csv` | per-seed % change vs the baseline, paired within a cell |
| `validation_report.md` | the correctness checks, all must pass |

**Read `validation_report.md` first.** If every check does not pass, the numbers are not
usable and the report says which guarantee broke. The suite also exits non-zero.

Useful variations:

```bash
# Quick smoke test (~1 min)
python -m mvp_sim.experiments.run_suite --output /tmp/smoke --cities jl yt --seeds 1

# Headline five-city table only, no supply sweep
python -m mvp_sim.experiments.run_suite --output results/headline --seeds 1 2 3

# SN adjuster tuning. Keep this OUT of the headline run.
python -m mvp_sim.experiments.run_suite --output results/tuning --sweep-sn --seeds 4 5 6

# Re-aggregate or re-validate without re-running anything
python -m mvp_sim.experiments.aggregate --runs results/canonical/runs --out results/canonical/aggregate
python -m mvp_sim.experiments.validate --runs results/canonical/runs
```

Tests: `python -m pytest tests/ -q` (114 tests, all should pass, ~3s).

**Commit before the run you publish from.** The repo currently has no commits, so
`manifest.json` records `code_commit: "unknown"` and the results cannot be pinned
to a code version. The suite prints a warning when this happens.

## Quoting numbers in the paper

Use `results_paired.csv` for percentage improvements. It compares policies only
within a matching `(city, seed, trace_hash, roster_hash, num_drivers,
cost_function, batch_alpha)` cell, so a comparison can never silently span two
different arrival traces. `pct_change` is positive when the policy's metric is
*larger*; for flow time an improvement is therefore negative.

Use `results_summary.csv` for a policy's own value plus uncertainty. With 3 seeds
the 95% interval uses the t multiplier 4.303, not 1.96 — with this few replicates
the normal approximation understates the interval by more than a factor of two.

Report `n_seeds` alongside any interval. Change it with `--seeds 1 2 3 4 5`.

## What changed, against FEEDBACK-V2.md

**P0.1 — one fixed trace replayed across policies.** Order arrivals and the
driver roster are now generated once per `(city, seed)` into a `Scenario`
(`mvp_sim/experiments/scenario.py`), serialised, hashed, and replayed unchanged.
`build_real_data_environment` takes no RNG at all. Arrival streams are seeded per
`(experiment_seed, restaurant_id)` and orders are paired to times in order-id
order, so the trace does not depend on dict iteration order or on the row order
of `orders.json`. ERF, EAF and NN now draw retry jitter from an explicitly seeded
instance RNG instead of the module-global `random`.

Two related bugs found on the way: `Order` and `Driver` assign ids from
module-global counters, so back-to-back policy runs in one process gave the same
logical orders different ids — and `order_id` is a tie-breaker inside several
policies. Both now accept an explicit id.

**P0.2 — sublinear batch cost.** The runner defaults to `sublinear_intrazone`,
implementing `tau(i,j,k) = D[z(i),j] + c(j)k^alpha` with `c(j) = beta*sqrt(A_j)/speed`,
`beta = 0.714` (a standard two-dimensional empirical choice) and `alpha = 0.5`.
Run the alpha sensitivity check as separate, fully identified suites, for example:

```bash
python -m mvp_sim.experiments.run_suite --output results/alpha_03 --batch-alpha 0.3
python -m mvp_sim.experiments.run_suite --output results/alpha_05 --batch-alpha 0.5
python -m mvp_sim.experiments.run_suite --output results/alpha_07 --batch-alpha 0.7
```

`A_j` is estimated from the bounding box
of destinations routed to zone `j`. Every cost parameter is recorded in each run
and in the manifest, and the validator fails if two policies in a cell used
different ones.

> **The most consequential bug found.** That item's acceptance check — "confirm
> that CALS uses the same service-cost definition as the simulator" — was failing.
> `cals.py` had its own `_tau`, reading the legacy `ainfo.alpha` / `ainfo.zone_area`
> fields. Under the sublinear model those are unset, so it silently took its
> `else` branch and returned `intrazone = 0.0`: **CALS was scoring batching as
> free while the simulator charged `c(j)k^alpha` for it.** CALS was therefore
> optimising a different objective than it was measured against, and the
> experiment partly measured that mismatch rather than the policy. Batch service
> time now has exactly one definition, `TravelCost.service_time`, which both
> `orders_cost` and CALS call; a test asserts they agree for every batch size.
> Fixing it improved CALS by roughly 5-9% on the cells checked (Yantai, full
> fleet, seed 1: `cals_noweights` 62.74 -> 59.83, `cals_mixed` 87.79 -> 79.56)
> and left ERF and SN untouched, as expected — they never called `_tau`.
> `cal.py` had the same defect and was fixed the same way, though it is not in
> the canonical set.

**P0.3 — utilization.** Drivers now record every non-idle interval
(travel-to-restaurant, batch delivery, repositioning). Utilization is the
*union* of those intervals clipped to the measurement window, divided by the
window. Values are in `[0,1]` by construction, asserted in the metric and checked
by the validator.

**P0.4 — nested supply sweeps.** The roster is shuffled once per replicate and
supply levels are prefixes, so `D_10 ⊂ D_25 ⊂ D_50 ⊂ D_75 ⊂ D_100`. Selected
driver ids and the roster seed are saved with every run and the nesting is
verified after the fact. (Previously a single `sub_rng` was reused across
fractions, so each level was an independent sample, not a superset.)

**P1.5 — replicates.** `--seeds` takes any number; the aggregator reports mean,
sd and a t-based 95% CI, and records which seeds contributed.

**P1.6 — frozen policy set.** ERF, EAF, NN; CALS at no-weights / urgency-only /
coverage-only / mixed; SN and SN-without-repositioning. All nine run by default.
Weights and the SN adjuster are read off each instance and recorded, so a new
tunable cannot be added and silently omitted from the record.

**P1.7 — completion accounting.** Every run records `arrived_orders`,
`delivered_orders`, `undelivered_orders` and `completion_rate`. The engine
**drains**: it runs until the event queue empties, so an order arriving before
the horizon is served even if that finishes after it. Applied identically to
every policy. In the verification run undelivered was 0 everywhere, so flow times
cover the same population for all policies.

## Things that need a decision from you

**1. The paper's data subset sentence is wrong.** Section V says "one
configuration uses all deliveries from May 1st through May 10th". The experiments
actually use a single day, **June 10 (`ds=0610`)** — that is what
`month_extractor.py` was hardcoded to, and it reproduces Table I *exactly* for all
five cities (cq 4088/348/316, hz 8225/449/349, jl 213/82/11, sh 6115/406/461,
yt 1051/278/99). Fix the sentence, or run a different subset with `--day`.

**2. Warm-up is proportional to the trace.** The canonical runner excludes the
first 5% of each seed's arrival horizon (`--warmup-fraction 0.05`). This scales
across cities instead of allowing a fixed five-minute cutoff to discard most of
the smaller traces. The resolved duration and fraction are recorded in every
scenario and run. `--warmup MINUTES` remains an explicit mutually exclusive
override for reproducing older experiments.

**3. Utilization saturates, and there are now two versions.**
`driver_utilization` (over `[warmup, horizon]`) is pinned at 1.000 for every
policy in the overloaded cities, so it cannot distinguish anything there. That is
a true measurement, not a bug: Jilin's 213 orders all arrive by t=15 and the fleet
needs until t=113 to clear them. `driver_utilization_makespan` (over
`[warmup, last completion]`) stays informative — 0.57 to 0.97 in Yantai. Caveat:
its denominator is the single last completion, so it is outlier-sensitive. Decide
which to report; the paper's promise to report utilization "only if it persists
across corrected replicated runs" is the right instinct.

**4. Jilin and Yantai sit outside the paper's stated regime.** Section IV-A claims
`Z < D ≈ R`. Chongqing (316 drivers / 348 restaurants), Hangzhou (349/449) and
Shanghai (461/406) fit. Jilin (11/82) and Yantai (99/278) do not — they are
heavily supply-constrained, which is why they saturate.

**5. The cost-matrix diagonal decision is resolved.** `cost_maker.py` now writes
`matrix[i][i] = 0.0`. The matrix therefore represents only inter-zone travel;
within-zone service is charged once, by `c(j)k^alpha`. The diagonal is recorded
in every run so results generated under the old convention cannot be mixed in.

## Not done

P2 (regenerating paper tables/figures and rewriting the claims) was out of scope.
`aggregate/` has the machine-readable inputs those tables need. The abstract and
introduction still carry the old headline percentages — do not restore or quote
them until they come from `results_paired.csv`.
