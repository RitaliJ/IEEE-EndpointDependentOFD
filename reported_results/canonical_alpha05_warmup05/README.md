# Frozen full-suite analysis

Generated from commit `bc462b407edc42cf26ee313b614d6a092685c355` and the validated suite
`canonical_alpha05_warmup05` without rerunning simulations.

Reproduce from the repository root:

```bash
MPLCONFIGDIR=/tmp/cs145-mpl .venv/bin/python -m mvp_sim.experiments.analyze_suite \
  --suite results/canonical_alpha05_warmup05 \
  --out reported_results/canonical_alpha05_warmup05
```

## Scope

- Cities: Chongqing, Hangzhou, Jilin, Shanghai, Yantai
- Day: `0610`; seeds: [1, 2, 3]
- Driver supply: [0.1, 0.25, 0.5, 0.75, 1.0]
- Policies: 9; runs: 675
- Alpha: 0.5; warm-up: first 5%
- All 8 validation checks passed and every arrived order completed.

## Reading the artifacts

`flow_time_by_supply.png` is the primary outcome figure. `paired_flow_improvement.png`
uses ERF as the within-city, within-seed, within-fleet baseline; positive values mean
lower flow time. `utilization_by_supply.png` uses makespan-based utilization.
The CSVs retain the underlying means, standard deviations, replicate counts, and
paired percentage changes.

Across cities at full fleet, the lowest unweighted mean flow time is
**CALS, no weights**. The largest mean runtime across all experimental cells is from
**CALS, mixed**. These summaries weight cities equally only after the
run-level results are grouped; paper claims should preferably report city-specific
paired effects rather than a single pooled headline number.

Error bars are two-sided 95% t intervals (`t₂ = 4.303`) based on only three seeds
and should be presented as uncertainty indicators, not strong inferential evidence.
