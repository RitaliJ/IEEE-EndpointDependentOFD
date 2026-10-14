"""The canonical experiment suite: one command, one manifest, one set of tables.

    python -m mvp_sim.experiments.run_suite --output results/canonical

Runs every policy against a shared order trace and driver roster, for each city,
each replicate seed, and each driver-supply level, then aggregates the runs and
writes a validation report.

Guarantees the suite is responsible for:
  * within a (city, seed) replicate every policy replays one identical trace,
    roster and cost model -- see experiments/scenario.py;
  * supply levels are nested prefixes of one shuffled roster, so raising supply
    only adds drivers;
  * every run records the parameters that define its experimental cell, so the
    aggregator can refuse to compare runs that do not match.

Output layout:
    <output>/manifest.json            code commit, data subset, seeds, policies
    <output>/prepared/<city>/         zones/orders/drivers/cost_matrix JSON
    <output>/scenarios/<city>_seed<S>.json
    <output>/runs/<city>/seed<S>/frac<PPP>/<policy>/
    <output>/aggregate/*.csv
    <output>/validation_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from mvp_sim.experiments import aggregate, validate
from mvp_sim.experiments.cainiao_data import (
    DEFAULT_COST_FUNCTION,
    DRIVER_SWEEP_FRACTIONS,
    _build_policies,
    describe_policy,
    prepare_data,
    run_baseline,
)
from mvp_sim.experiments.scenario import (
    CANONICAL_DAY, WARMUP_FRACTION, Scenario, build_scenario, roster_prefix,
)

# City code -> raw CSV, relative to the repo's data directory.
CITY_CSV: dict[str, str] = {
    "cq": "data/delivery/delivery_cq.csv",
    "hz": "data/delivery/delivery_hz.csv",
    "jl": "data/delivery/delivery_jl.csv",
    "sh": "data/delivery/delivery_sh.csv",
    "yt": "data/delivery/delivery_yt.csv",
}
ALL_CITIES: list[str] = ["cq", "hz", "jl", "sh", "yt"]

# Replicate seeds. Each is an independent redraw of the arrival trace and roster
# ordering; within a replicate every policy sees the identical realisation.
DEFAULT_SEEDS: list[int] = [1, 2, 3]


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL, text=True
        )
        return bool(out.strip())
    except Exception:
        return False


def _run_dir(output: str, city: str, seed: int, fraction: float, policy: str) -> str:
    return os.path.join(output, "runs", city, f"seed{seed}",
                        f"frac{round(fraction * 100):03d}", policy)


def _execute(task: dict) -> dict:
    """Run one (city, seed, fraction, policy) cell. Executed in a worker process."""
    scenario = Scenario.load(task["scenario_path"])
    policies = dict(_build_policies(sweep_sn=task["sweep_sn"], seed=task["seed"]))
    policy = policies[task["policy"]]

    started = time.perf_counter()
    results = run_baseline(
        zones_path=task["zones_path"],
        cost_matrix_path=task["cost_matrix_path"],
        scenario=scenario,
        output=task["output"],
        policy=policy,
        policy_name=task["policy"],
        drivers_override=roster_prefix(scenario, task["fraction"]),
        supply_fraction=task["fraction"],
        save_dir_override=task["save_dir"],
        make_plots=task["make_plots"],
        per_driver_plots=False,
        order_gantt_plot=False,
        light=task["light"],
    )
    runtime = {
        "runtime_seconds": time.perf_counter() - started,
        "simulation_runtime_seconds": results.config.get("simulation_runtime_seconds"),
    }
    with open(os.path.join(task["save_dir"], "runtime.json"), "w") as f:
        json.dump(runtime, f, indent=2)
    return {
        "city": task["city"],
        "seed": task["seed"],
        "fraction": task["fraction"],
        "policy": task["policy"],
        "seconds": round(runtime["runtime_seconds"], 2),
        "flow_time_avg": results.metrics.get("flow_time", {}).get("avg"),
        "undelivered": results.metrics.get("undelivered_orders"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical experiment suite")
    parser.add_argument("--output", required=True, help="Directory to write the suite into")
    parser.add_argument("--cities", nargs="+", default=ALL_CITIES, choices=ALL_CITIES,
                        help="City codes to run (default: all five)")
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS,
                        help=f"Replicate seeds (default: {DEFAULT_SEEDS})")
    parser.add_argument("--driver-sweep", action="store_true",
                        help=f"Run the nested supply sweep {DRIVER_SWEEP_FRACTIONS} "
                             "instead of the full fleet only")
    parser.add_argument("--fractions", nargs="+", type=float, default=None,
                        help="Override the supply levels to run")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="Parallel worker processes")
    parser.add_argument("--day", default=CANONICAL_DAY,
                        help=f"ds (MMDD) subset (default {CANONICAL_DAY}, reproduces Table I)")
    parser.add_argument("--cost-function", default=DEFAULT_COST_FUNCTION)
    parser.add_argument("--speed", type=float, default=1.0,
                        help="km per minute for converting haversine km to minutes")
    parser.add_argument("--batch-alpha", type=float, default=0.5,
                        help="Sublinear within-zone batch exponent (default: 0.5). "
                             "Use separate output directories to run an alpha sensitivity check")
    warmup = parser.add_mutually_exclusive_group()
    warmup.add_argument("--warmup", type=float, default=None,
                        help="Explicit warm-up duration in simulation minutes")
    warmup.add_argument("--warmup-fraction", type=float, default=WARMUP_FRACTION,
                        help=f"Fraction of each trace's arrival horizon excluded from metrics "
                             f"(default: {WARMUP_FRACTION})")
    parser.add_argument("--sweep-sn", action="store_true",
                        help="Tuning sweep over the SN adjuster. Keep this OUT of the "
                             "run used for headline numbers")
    parser.add_argument("--baseline", default="erf",
                        help="Policy used as the denominator in the paired table")
    parser.add_argument("--plots", action="store_true",
                        help="Render per-run plots (slow; off by default)")
    parser.add_argument("--full-artifacts", action="store_true",
                        help="Also write events.log and orders.json per run. Neither is "
                             "read by the aggregator or validator; they take a 675-run "
                             "suite from roughly 250 MB to roughly 5 GB")
    parser.add_argument("--data-root", default=".",
                        help="Repo root containing data/ (default: cwd)")
    args = parser.parse_args()

    # Capture provenance before creating the output directory. Otherwise the
    # suite's own untracked results can make a clean checkout report itself as
    # dirty in manifest.json.
    code_commit = _git_commit()
    working_tree_dirty = _git_dirty()

    fractions = args.fractions or (DRIVER_SWEEP_FRACTIONS if args.driver_sweep else [1.0])
    os.makedirs(args.output, exist_ok=True)

    # ---- prepare each city once; prepared data is a pure function of (csv, day, speed)
    prepared: dict[str, dict] = {}
    for city in args.cities:
        csv_path = os.path.join(args.data_root, CITY_CSV[city])
        if not os.path.exists(csv_path):
            raise SystemExit(f"missing raw data for {city}: {csv_path}")
        prep_dir = os.path.join(args.output, "prepared", city)
        print(f"[prepare] {city} <- {csv_path}", flush=True)
        zones, cost_matrix, drivers, orders, summary = prepare_data(
            csv_path, prep_dir, data_day=args.day, speed_km_per_min=args.speed,
        )
        prepared[city] = {
            "zones_path": zones, "cost_matrix_path": cost_matrix,
            "drivers_path": drivers, "orders_path": orders, "data_summary": summary,
        }

    # ---- one scenario per (city, seed)
    scenarios: dict[tuple[str, int], str] = {}
    scenario_manifests: list[dict] = []
    for city in args.cities:
        p = prepared[city]
        with open(p["cost_matrix_path"]) as f:
            raw_cm = json.load(f)
        for seed in args.seeds:
            scenario = build_scenario(
                zones_path=p["zones_path"],
                orders_path=p["orders_path"],
                drivers_path=p["drivers_path"],
                cost_matrix=raw_cm,
                city=city,
                experiment_seed=seed,
                roster_seed=seed,
                data_day=args.day,
                warmup_duration=args.warmup,
                warmup_fraction=args.warmup_fraction,
                cost_function=args.cost_function,
                speed_km_per_min=args.speed,
                batch_alpha=args.batch_alpha,
            )
            path = os.path.join(args.output, "scenarios", f"{city}_seed{seed}.json")
            scenario.save(path)
            scenarios[(city, seed)] = path
            scenario_manifests.append(scenario.manifest())
            print(f"[scenario] {city} seed={seed} orders={len(scenario.orders)} "
                  f"drivers={len(scenario.roster)} horizon={scenario.horizon} "
                  f"trace={scenario.trace_hash}", flush=True)

    # ---- manifest, written before the runs so a crashed suite is still identifiable
    policy_names = [name for name, _ in _build_policies(sweep_sn=args.sweep_sn, seed=0)]
    manifest = {
        "code_commit": code_commit,
        "working_tree_dirty": working_tree_dirty,
        "python": sys.version.split()[0],
        "command": " ".join(sys.argv),
        "cities": args.cities,
        "seeds": args.seeds,
        "supply_fractions": fractions,
        "policies": policy_names,
        "policy_configs": {
            name: describe_policy(pol)
            for name, pol in _build_policies(sweep_sn=args.sweep_sn, seed=0)
        },
        "data_day": args.day,
        "cost_function": args.cost_function,
        "speed_km_per_min": args.speed,
        "batch_alpha": args.batch_alpha,
        "warmup_duration": args.warmup,
        "warmup_fraction": None if args.warmup is not None else args.warmup_fraction,
        "completion_policy": (
            "drain: the engine runs until the event queue empties, so orders that "
            "arrive before the horizon are served to completion even if that happens "
            "after it. Applied identically to every policy. undelivered_orders "
            "records any order that still did not complete."
        ),
        "data_summaries": {c: prepared[c]["data_summary"] for c in args.cities},
        "scenarios": scenario_manifests,
    }
    with open(os.path.join(args.output, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Provenance warnings. These are not fatal -- a suite still runs -- but results
    # whose code version cannot be pinned should not go into the paper.
    if manifest["code_commit"] == "unknown":
        print("\n  WARNING: no git commit could be resolved, so manifest.json cannot "
              "pin the code that produced these results.\n"
              "           Commit before the run you intend to publish from.\n", flush=True)
    elif manifest["working_tree_dirty"]:
        print(f"\n  WARNING: working tree is dirty; manifest records commit "
              f"{manifest['code_commit'][:12]} but the code on disk differs from it.\n",
              flush=True)

    # ---- build the task list
    tasks: list[dict] = []
    for city in args.cities:
        p = prepared[city]
        for seed in args.seeds:
            for fraction in fractions:
                for policy_name in policy_names:
                    tasks.append({
                        "city": city, "seed": seed, "fraction": fraction,
                        "policy": policy_name, "sweep_sn": args.sweep_sn,
                        "scenario_path": scenarios[(city, seed)],
                        "zones_path": p["zones_path"],
                        "cost_matrix_path": p["cost_matrix_path"],
                        "output": args.output,
                        "save_dir": _run_dir(args.output, city, seed, fraction, policy_name),
                        "make_plots": args.plots,
                        "light": not args.full_artifacts,
                    })

    print(f"\n[run] {len(tasks)} runs across {args.jobs} workers\n", flush=True)
    started = time.time()
    done = 0
    failures: list[str] = []

    if args.jobs == 1:
        for task in tasks:
            try:
                info = _execute(task)
                done += 1
                print(f"  [{done}/{len(tasks)}] {info['city']} seed{info['seed']} "
                      f"frac{info['fraction']} {info['policy']} {info['seconds']}s", flush=True)
            except Exception as exc:
                failures.append(f"{task['city']}/{task['seed']}/{task['policy']}: {exc}")
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(_execute, t): t for t in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    info = future.result()
                    done += 1
                    print(f"  [{done}/{len(tasks)}] {info['city']} seed{info['seed']} "
                          f"frac{info['fraction']} {info['policy']} {info['seconds']}s", flush=True)
                except Exception as exc:
                    failures.append(f"{task['city']}/{task['seed']}/{task['policy']}: {exc}")

    elapsed = time.time() - started
    print(f"\n[run] {done}/{len(tasks)} succeeded in {elapsed/60:.1f} min", flush=True)
    for failure in failures:
        print(f"  FAILED {failure}", flush=True)

    # ---- aggregate and validate
    runs_root = os.path.join(args.output, "runs")
    agg_dir = os.path.join(args.output, "aggregate")
    stats = aggregate.aggregate_all(runs_root, agg_dir, baseline=args.baseline)
    print(f"[aggregate] {stats['n_runs']} runs -> {agg_dir}", flush=True)

    report_path = os.path.join(args.output, "validation_report.md")
    report = validate.build_report(runs_root, manifest_path=os.path.join(args.output, "manifest.json"))
    with open(report_path, "w") as f:
        f.write(report.text)
    print(f"[validate] {report.passed}/{report.total} checks passed -> {report_path}", flush=True)

    if failures or not report.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
