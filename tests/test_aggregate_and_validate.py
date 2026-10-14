"""Aggregation and validation (FEEDBACK-V2 P1 items 5 and 7).

Replicated seeds must be reported with an uncertainty interval, percentage
improvements must be computed from paired runs inside one experimental cell, and
the validator must actually fail when a guarantee is violated -- a validation
report that cannot fail is worthless.
"""

import json
import os

import pytest

from mvp_sim.experiments import aggregate, validate


def write_run(root, *, city, seed, policy, fraction=1.0, flow_avg=100.0,
              trace_hash="T", roster_hash="R", driver_ids=(1, 2, 3),
              arrived=50, delivered=50, util_max=0.8, cost_function="sublinear_intrazone"):
    d = os.path.join(root, city, f"seed{seed}", f"frac{round(fraction*100):03d}", policy)
    os.makedirs(d, exist_ok=True)
    metrics = {
        "flow_time": {"avg": flow_avg, "min": 1.0, "max": 300.0,
                      "p90": flow_avg * 1.5, "p95": flow_avg * 1.8, "p99": flow_avg * 2.0},
        "travel_time": {"avg": 5.0, "min": 1.0, "max": 9.0, "p90": 7.0, "p95": 8.0, "p99": 9.0},
        "driver_utilization": {"avg": util_max / 2, "min": 0.0, "max": util_max,
                               "p90": 0.7, "p95": 0.75, "p99": 0.8},
        "driver_utilization_makespan": {"avg": 0.3, "min": 0.0, "max": 0.6,
                                        "p90": 0.5, "p95": 0.55, "p99": 0.6},
        "arrived_orders": arrived, "delivered_orders": delivered,
        "undelivered_orders": arrived - delivered,
        "completion_rate": delivered / arrived if arrived else 0.0,
        "avg_batch_size": 2.0, "batch_efficiency": 0.5, "makespan": 200.0,
    }
    config = {
        "experiment": "t", "policy": policy, "policy_config": {"class": policy},
        "seed": seed, "horizon": 100.0, "warmup_duration": 5.0,
        "num_drivers": len(driver_ids), "supply_fraction": fraction,
        "driver_ids": list(driver_ids),
        "scenario": {
            "city": city, "data_day": "0610", "experiment_seed": seed,
            "trace_hash": trace_hash, "roster_hash": roster_hash,
            "cost_params": {"cost_function": cost_function, "batch_alpha": 0.5,
                            "bhh_constant": 0.7124, "speed_km_per_min": 1.0,
                            "zone_area_estimator": "destination_bounding_box_km2",
                            "matrix_diagonal": 1.0},
        },
    }
    with open(os.path.join(d, "metrics.json"), "w") as f:
        json.dump(metrics, f)
    with open(os.path.join(d, "experiment_config.json"), "w") as f:
        json.dump(config, f)
    return d


@pytest.fixture
def good_suite(tmp_path):
    """Three seeds, two policies, two nested supply levels -- all guarantees hold."""
    root = str(tmp_path / "runs")
    for seed, (erf_flow, sn_flow) in zip((1, 2, 3), ((100.0, 80.0), (110.0, 88.0), (90.0, 72.0))):
        for fraction, ids in ((0.5, (1, 2)), (1.0, (1, 2, 3, 4))):
            write_run(root, city="jl", seed=seed, policy="erf", fraction=fraction,
                      flow_avg=erf_flow, driver_ids=ids, trace_hash=f"T{seed}")
            write_run(root, city="jl", seed=seed, policy="sn", fraction=fraction,
                      flow_avg=sn_flow, driver_ids=ids, trace_hash=f"T{seed}")
    return root


class TestSummaryStatistics:
    def test_runtime_artifact_is_included_in_long_rows(self, tmp_path):
        root = str(tmp_path / "runs")
        d = write_run(root, city="jl", seed=1, policy="erf")
        with open(os.path.join(d, "runtime.json"), "w") as f:
            json.dump({"runtime_seconds": 1.25, "simulation_runtime_seconds": 0.75}, f)
        row = aggregate.load_runs(root)[0]
        assert row["runtime_seconds"] == pytest.approx(1.25)
        assert row["simulation_runtime_seconds"] == pytest.approx(0.75)

    def test_replicates_are_collapsed_with_an_interval(self, good_suite, tmp_path):
        rows = aggregate.load_runs(good_suite)
        out = str(tmp_path / "summary.csv")
        summary = aggregate.write_summary(rows, out)

        erf_full = [s for s in summary
                    if s["policy"] == "erf" and s["supply_fraction"] == 1.0]
        assert len(erf_full) == 1
        row = erf_full[0]
        assert row["n_seeds"] == 3
        # mean of 100, 110, 90
        assert row["flow_time.avg.mean"] == pytest.approx(100.0)
        assert row["flow_time.avg.sd"] == pytest.approx(10.0)
        # t multiplier at df=2 is 4.303, so the half width is 4.303*10/sqrt(3)
        assert row["flow_time.avg.ci95"] == pytest.approx(4.303 * 10.0 / (3 ** 0.5), rel=1e-3)

    def test_single_replicate_reports_no_interval(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf")
        rows = aggregate.load_runs(root)
        summary = aggregate.write_summary(rows, str(tmp_path / "s.csv"))
        assert summary[0]["n_seeds"] == 1
        # Blank, not 0.0 -- a zero would read as "measured to be exactly zero".
        assert summary[0]["flow_time.avg.ci95"] == ""

    def test_t_multiplier_beats_the_normal_approximation_for_small_n(self):
        assert aggregate._t95(2) == pytest.approx(4.303)
        assert aggregate._t95(2) > 1.96

    def test_summary_never_pools_across_different_cells(self, tmp_path):
        """Runs from different supply levels must not be averaged together."""
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", fraction=0.5, driver_ids=(1,))
        write_run(root, city="jl", seed=1, policy="erf", fraction=1.0, driver_ids=(1, 2))
        rows = aggregate.load_runs(root)
        summary = aggregate.write_summary(rows, str(tmp_path / "s.csv"))
        assert len(summary) == 2
        assert all(s["n_seeds"] == 1 for s in summary)


class TestPairedComparison:
    def test_improvements_are_computed_per_seed(self, good_suite, tmp_path):
        rows = aggregate.load_runs(good_suite)
        paired = aggregate.write_paired(rows, str(tmp_path / "p.csv"), baseline="erf")

        full = [p for p in paired if p["supply_fraction"] == 1.0 and p["policy"] == "sn"]
        assert len(full) == 3, "one paired comparison per seed"
        # Every seed is a 20% reduction in mean flow time.
        for entry in full:
            assert entry["flow_time.avg.pct_change"] == pytest.approx(-20.0)

    def test_baseline_is_not_compared_to_itself(self, good_suite, tmp_path):
        rows = aggregate.load_runs(good_suite)
        paired = aggregate.write_paired(rows, str(tmp_path / "p.csv"), baseline="erf")
        assert all(p["policy"] != "erf" for p in paired)

    def test_cells_without_the_baseline_are_skipped(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="sn")
        rows = aggregate.load_runs(root)
        paired = aggregate.write_paired(rows, str(tmp_path / "p.csv"), baseline="erf")
        assert paired == []

    def test_pairing_never_crosses_traces(self, tmp_path):
        """Two policies run on different traces must not be paired."""
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", trace_hash="A")
        write_run(root, city="jl", seed=1, policy="sn", trace_hash="B")
        rows = aggregate.load_runs(root)
        paired = aggregate.write_paired(rows, str(tmp_path / "p.csv"), baseline="erf")
        assert paired == [], "different trace_hash means different cells"


class TestValidatorCatchesViolations:
    def test_manifest_detects_an_incomplete_suite(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({
            "cities": ["jl"], "seeds": [1], "supply_fractions": [1.0],
            "policies": ["erf", "sn"],
        }))
        report = validate.build_report(root, manifest_path=str(manifest))
        assert not report.ok
        assert any("exactly one run" in c.name and not c.ok for c in report.checks)

    def test_clean_suite_passes_every_check(self, good_suite):
        report = validate.build_report(good_suite)
        assert report.ok, report.text
        assert report.total >= 6

    def test_diverging_traces_are_caught(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", trace_hash="A", arrived=50, delivered=50)
        write_run(root, city="jl", seed=1, policy="sn", trace_hash="B", arrived=60, delivered=60)
        report = validate.build_report(root)
        assert not report.ok
        assert any("trace" in c.name and not c.ok for c in report.checks)

    def test_mismatched_rosters_are_caught(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", driver_ids=(1, 2, 3))
        write_run(root, city="jl", seed=1, policy="sn", driver_ids=(4, 5, 6))
        report = validate.build_report(root)
        assert not report.ok
        assert any("roster" in c.name and not c.ok for c in report.checks)

    def test_non_nested_supply_levels_are_caught(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", fraction=0.5, driver_ids=(1, 2))
        write_run(root, city="jl", seed=1, policy="erf", fraction=1.0, driver_ids=(3, 4, 5))
        report = validate.build_report(root)
        assert not report.ok
        assert any("nested" in c.name and not c.ok for c in report.checks)

    def test_out_of_range_utilization_is_caught(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", util_max=1.4)
        report = validate.build_report(root)
        assert not report.ok
        assert any("utilization" in c.name and not c.ok for c in report.checks)

    def test_mismatched_cost_parameters_are_caught(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", cost_function="sublinear_intrazone")
        write_run(root, city="jl", seed=1, policy="sn", cost_function="zone_fixed_cost_matrix")
        report = validate.build_report(root)
        assert not report.ok
        assert any("cost parameters" in c.name and not c.ok for c in report.checks)

    def test_unfinished_orders_are_reported(self, tmp_path):
        root = str(tmp_path / "runs")
        write_run(root, city="jl", seed=1, policy="erf", arrived=50, delivered=42)
        report = validate.build_report(root)
        assert not report.ok
        assert any("unfinished" in c.name and not c.ok for c in report.checks)

    def test_empty_run_directory_fails_loudly(self, tmp_path):
        report = validate.build_report(str(tmp_path / "nothing"))
        assert not report.ok
