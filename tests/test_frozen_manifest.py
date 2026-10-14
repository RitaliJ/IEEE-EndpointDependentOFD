"""The publication manifest must remain synchronized with executable defaults."""

import hashlib
import json
from pathlib import Path

from mvp_sim.experiments.aggregate import CELL_KEYS
from mvp_sim.experiments.cainiao_data import (
    DRIVER_SWEEP_FRACTIONS,
    CANONICAL_SN_ADJUSTER,
    _build_policies,
)
from mvp_sim.experiments.run_suite import ALL_CITIES, DEFAULT_SEEDS
from mvp_sim.experiments.scenario import (
    BATCH_ALPHA,
    BHH_CONSTANT,
    CANONICAL_DAY,
    WARMUP_FRACTION,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "experiment_configs" / "frozen_full_suite_v1.json"


def manifest():
    return json.loads(MANIFEST_PATH.read_text())


def test_frozen_semantics_match_executable_constants():
    m = manifest()
    assert m["dataset"]["data_day"] == CANONICAL_DAY
    assert m["dataset"]["cities"] == ALL_CITIES
    assert m["replication"]["seeds"] == DEFAULT_SEEDS
    assert m["fleet"]["fractions"] == DRIVER_SWEEP_FRACTIONS
    assert m["service_model"]["default_alpha"] == BATCH_ALPHA
    assert m["service_model"]["beta"] == BHH_CONSTANT
    assert m["warmup"]["fraction_of_arrival_horizon"] == WARMUP_FRACTION
    assert m["policies"][-2]["parameters"]["adjuster"] == CANONICAL_SN_ADJUSTER
    assert m["policies"][-1]["parameters"]["adjuster"] == CANONICAL_SN_ADJUSTER


def test_policy_names_and_pairing_keys_match_the_runner():
    m = manifest()
    expected_policies = [name for name, _policy in _build_policies(seed=0)]
    assert [p["name"] for p in m["policies"]] == expected_policies
    assert m["pairing"]["keys"] == CELL_KEYS + ["seed"]


def test_declared_run_counts_are_arithmetically_consistent():
    m = manifest()
    cities = len(m["dataset"]["cities"])
    seeds = len(m["replication"]["seeds"])
    fleets = len(m["fleet"]["fractions"])
    policies = len(m["policies"])
    assert m["run_count"]["expected_primary_runs"] == cities * seeds * fleets * policies
    assert m["run_count"]["expected_summary_rows"] == cities * fleets * policies
    assert m["run_count"]["expected_paired_rows"] == cities * seeds * fleets * (policies - 1)


def test_lockfile_fingerprint_is_current():
    m = manifest()
    digest = hashlib.sha256((ROOT / m["software"]["lockfile"]).read_bytes()).hexdigest()
    assert digest == m["software"]["lockfile_sha256"]
