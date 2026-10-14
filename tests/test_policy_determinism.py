"""Policy randomness must be explicitly seeded (FEEDBACK-V2 P0 item 1).

ERF, EAF and NN schedule a retry after a random delay. That draw used to come
from the module-global `random`, so a run depended on import order and on
whatever else had touched the global stream -- the master experiment seed did not
fully determine the result.
"""

import random

import pytest

from mvp_sim.policies.general_policies import eaf, erf, nearest_neighbor

POLICIES = [
    pytest.param(erf.ERF, id="ERF"),
    pytest.param(eaf.EAF, id="EAF"),
    pytest.param(nearest_neighbor.NearestNeighbor, id="NN"),
]


def draws(policy, n: int = 40) -> list[int]:
    """The retry delays a policy would schedule, in order."""
    return [policy._rng.randint(1, policy.max_policy_wait) for _ in range(n)]


@pytest.mark.parametrize("cls", POLICIES)
class TestSeeding:
    def test_same_seed_gives_the_same_sequence(self, cls):
        assert draws(cls(seed=17)) == draws(cls(seed=17))

    def test_different_seeds_give_different_sequences(self, cls):
        assert draws(cls(seed=1)) != draws(cls(seed=2))

    def test_policy_does_not_consume_the_global_stream(self, cls):
        """Constructing and drawing must leave `random`'s global state untouched."""
        random.seed(1234)
        expected = [random.random() for _ in range(5)]

        random.seed(1234)
        draws(cls(seed=99), n=100)
        after = [random.random() for _ in range(5)]

        assert after == expected

    def test_policy_is_unaffected_by_the_global_stream(self, cls):
        """Perturbing `random` globally must not change a policy's draws."""
        baseline = draws(cls(seed=5))

        random.seed(999)
        for _ in range(1000):
            random.random()

        assert draws(cls(seed=5)) == baseline

    def test_seed_is_recorded_on_the_instance(self, cls):
        """describe_policy reads tunables off the instance, so they must be public."""
        policy = cls(seed=42)
        assert policy.seed == 42
        assert policy.max_policy_wait > 0

    def test_delays_stay_within_the_configured_bound(self, cls):
        policy = cls(seed=3, max_policy_wait=7)
        assert all(1 <= d <= 7 for d in draws(policy, n=200))


class TestPolicyDescription:
    def test_describe_policy_captures_tunables_and_hides_run_state(self):
        from mvp_sim.experiments.cainiao_data import describe_policy
        from mvp_sim.policies.general_policies import cals, sn

        desc = describe_policy(cals.CALS(w_a=2.0, w_c=5.0))
        assert desc["class"] == "CALS"
        assert desc["w_a"] == 2.0 and desc["w_c"] == 5.0
        assert not any(k.startswith("_") for k in desc)

        assert describe_policy(sn.SN(adjuster=0.5))["adjuster"] == 0.5
        assert describe_policy(erf.ERF(seed=8))["seed"] == 8

    def test_canonical_policy_set_is_complete(self):
        """The comparison frozen in FEEDBACK-V2 item 6."""
        from mvp_sim.experiments.cainiao_data import _build_policies

        names = [n for n, _ in _build_policies(seed=0)]
        for required in ("erf", "eaf", "nearest_neighbor",
                         "cals_noweights", "cals_urgency", "cals_coverage", "cals_mixed",
                         "sn", "sn_noreposition"):
            assert required in names, f"{required} missing from the canonical set"

    def test_canonical_set_has_no_duplicate_names(self):
        from mvp_sim.experiments.cainiao_data import _build_policies

        names = [n for n, _ in _build_policies(seed=0)]
        assert len(names) == len(set(names))
