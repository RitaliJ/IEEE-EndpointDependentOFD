"""Post-run validation: prove the guarantees the comparison depends on.

Passing these checks is what makes the results quotable. Each corresponds to an
acceptance check in FEEDBACK-V2.md:

    trace equality      every policy in a cell replayed one identical order trace
    roster equality     every policy in a cell got the identical driver ids
    roster nesting      D_10 subset D_25 subset ... subset D_100
    utilization bounds  every per-driver utilization lies in [0, 1]
    cost parameters     every policy in a comparison used identical cost params
    completion          delivered + undelivered accounts for every arrived order

Run standalone against an existing suite:

    python -m mvp_sim.experiments.validate --runs results/canonical/runs
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    text: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _load(runs_root: str) -> list[dict]:
    runs: list[dict] = []
    for dirpath, _dirs, files in os.walk(runs_root):
        if "metrics.json" not in files or "experiment_config.json" not in files:
            continue
        with open(os.path.join(dirpath, "metrics.json")) as f:
            metrics = json.load(f)
        with open(os.path.join(dirpath, "experiment_config.json")) as f:
            config = json.load(f)
        runs.append({
            "dir": os.path.relpath(dirpath, runs_root),
            "metrics": metrics,
            "config": config,
            "scenario": config.get("scenario", {}),
        })
    return runs


def build_report(runs_root: str, manifest_path: str | None = None) -> Report:
    runs = _load(runs_root)
    checks: list[Check] = []
    manifest = None
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)

    if not runs:
        report = Report(checks=[Check("runs found", False, f"no runs under {runs_root}")])
        report.text = _render(report, 0, manifest_path)
        return report

    # A comparison cell: all runs that must be directly comparable to each other.
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for r in runs:
        key = (r["scenario"].get("city"), r["config"].get("seed"),
               r["config"].get("supply_fraction"))
        cells[key].append(r)

    # --- 0. suite completeness and uniqueness -------------------------------
    identities = [
        (r["scenario"].get("city"), r["config"].get("seed"),
         r["config"].get("supply_fraction"), r["config"].get("policy"))
        for r in runs
    ]
    duplicates = sorted({identity for identity in identities if identities.count(identity) > 1},
                        key=str)
    missing = []
    unexpected = []
    if manifest is not None:
        expected = {
            (city, seed, fraction, policy)
            for city in manifest.get("cities", [])
            for seed in manifest.get("seeds", [])
            for fraction in manifest.get("supply_fractions", [])
            for policy in manifest.get("policies", [])
        }
        actual = set(identities)
        missing = sorted(expected - actual, key=str)
        unexpected = sorted(actual - expected, key=str)
    checks.append(Check(
        "suite contains exactly one run for every declared experimental cell",
        not duplicates and not missing and not unexpected,
        (f"{len(identities)} unique runs match the manifest" if manifest is not None
         else f"{len(identities)} runs have unique identities")
        if not duplicates and not missing and not unexpected else
        f"duplicates={duplicates[:3]}; missing={missing[:3]}; unexpected={unexpected[:3]}",
    ))

    # --- 1. identical order trace within each cell ---------------------------
    bad = []
    for key, group in sorted(cells.items(), key=lambda kv: str(kv[0])):
        hashes = {r["scenario"].get("trace_hash") for r in group}
        counts = {r["metrics"].get("arrived_orders") for r in group}
        horizons = {r["config"].get("horizon") for r in group}
        if len(hashes) > 1 or len(counts) > 1 or len(horizons) > 1:
            bad.append(f"{key}: hashes={hashes} arrived={counts} horizons={horizons}")
    checks.append(Check(
        "identical order trace, arrival count and horizon across policies",
        not bad,
        "all cells consistent" if not bad else "; ".join(bad[:5]),
    ))

    # --- 2. identical driver roster within each cell -------------------------
    bad = []
    for key, group in sorted(cells.items(), key=lambda kv: str(kv[0])):
        rosters = {tuple(r["config"].get("driver_ids", [])) for r in group}
        if len(rosters) > 1:
            bad.append(f"{key}: {len(rosters)} distinct rosters")
    checks.append(Check(
        "identical driver roster across policies within a cell",
        not bad,
        "all cells consistent" if not bad else "; ".join(bad[:5]),
    ))

    # --- 3. nested supply levels ---------------------------------------------
    by_city_seed: dict[tuple, dict[float, set]] = defaultdict(dict)
    for r in runs:
        key = (r["scenario"].get("city"), r["config"].get("seed"))
        frac = r["config"].get("supply_fraction")
        by_city_seed[key][frac] = set(r["config"].get("driver_ids", []))

    bad = []
    checked_pairs = 0
    for key, by_frac in sorted(by_city_seed.items(), key=lambda kv: str(kv[0])):
        fracs = sorted(by_frac)
        for lo, hi in zip(fracs, fracs[1:]):
            checked_pairs += 1
            if not by_frac[lo] <= by_frac[hi]:
                missing = sorted(by_frac[lo] - by_frac[hi])[:5]
                bad.append(f"{key}: frac {lo} not subset of {hi} (e.g. dropped {missing})")
    checks.append(Check(
        "driver-supply levels are nested",
        not bad,
        (f"{checked_pairs} consecutive pairs nested" if checked_pairs
         else "only one supply level present, nothing to check")
        if not bad else "; ".join(bad[:5]),
    ))

    # --- 4. utilization in [0, 1] --------------------------------------------
    bad = []
    for r in runs:
        for name in ("driver_utilization", "driver_utilization_makespan"):
            stats = r["metrics"].get(name)
            if not isinstance(stats, dict):
                continue
            lo, hi = stats.get("min"), stats.get("max")
            if lo is None or hi is None:
                continue
            if lo < -1e-9 or hi > 1.0 + 1e-9:
                bad.append(f"{r['dir']} {name}: min={lo} max={hi}")
    checks.append(Check(
        "every per-driver utilization lies in [0, 1]",
        not bad,
        f"{len(runs)} runs within bounds" if not bad else "; ".join(bad[:5]),
    ))

    # --- 5. identical cost parameters within each cell -----------------------
    bad = []
    for key, group in sorted(cells.items(), key=lambda kv: str(kv[0])):
        signatures = set()
        for r in group:
            signatures.add(json.dumps({
                "params": r["scenario"].get("cost_params", {}),
                "matrix_sha": r["config"].get("cost_matrix_sha"),
            }, sort_keys=True, separators=(",", ":")))
        if len(signatures) > 1:
            bad.append(f"{key}: {len(signatures)} distinct cost configurations")
    checks.append(Check(
        "identical cost parameters across policies within a cell",
        not bad,
        "all cells consistent" if not bad else "; ".join(bad[:5]),
    ))

    # --- 6. completion accounting --------------------------------------------
    bad = []
    censored = []
    for r in runs:
        m = r["metrics"]
        arrived = m.get("arrived_orders")
        delivered = m.get("delivered_orders")
        undelivered = m.get("undelivered_orders")
        if None in (arrived, delivered, undelivered):
            continue
        if delivered + undelivered != arrived:
            bad.append(f"{r['dir']}: {delivered}+{undelivered} != {arrived}")
        if undelivered:
            censored.append(f"{r['dir']}: {undelivered} undelivered")
    checks.append(Check(
        "delivered + undelivered accounts for every arrived order",
        not bad,
        f"{len(runs)} runs balanced" if not bad else "; ".join(bad[:5]),
    ))
    checks.append(Check(
        "no policy leaves orders unfinished (flow times cover the same population)",
        not censored,
        "every arrived order completed in every run" if not censored
        else "; ".join(censored[:5]),
    ))

    report = Report(checks=checks)
    report.text = _render(report, len(runs), manifest_path)
    return report


def _render(report: Report, n_runs: int, manifest_path: str | None) -> str:
    lines = ["# Validation report", ""]
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        lines += [
            f"- code commit: `{manifest.get('code_commit')}`"
            + ("  **(working tree dirty)**" if manifest.get("working_tree_dirty") else ""),
            f"- command: `{manifest.get('command')}`",
            f"- cities: {manifest.get('cities')}",
            f"- seeds: {manifest.get('seeds')}",
            f"- supply fractions: {manifest.get('supply_fractions')}",
            f"- cost function: `{manifest.get('cost_function')}`",
            f"- data day: `{manifest.get('data_day')}`",
            "",
        ]
    lines += [f"{n_runs} runs checked.", "",
              "| check | result | detail |", "| --- | --- | --- |"]
    for check in report.checks:
        mark = "PASS" if check.ok else "FAIL"
        detail = check.detail.replace("|", "\\|")
        lines.append(f"| {check.name} | **{mark}** | {detail} |")
    lines += ["", f"**{report.passed}/{report.total} checks passed.**", ""]
    if not report.ok:
        lines.append("> Results are not quotable until every check passes.")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate a completed experiment suite")
    parser.add_argument("--runs", required=True, help="Directory containing run outputs")
    parser.add_argument("--manifest", default=None, help="Path to the suite manifest.json")
    parser.add_argument("--out", default=None, help="Write the report here instead of stdout")
    args = parser.parse_args()

    report = build_report(args.runs, manifest_path=args.manifest)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report.text)
        print(f"{report.passed}/{report.total} checks passed -> {args.out}")
    else:
        print(report.text)
    raise SystemExit(0 if report.ok else 1)
