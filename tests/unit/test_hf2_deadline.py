"""HF2 extends admission while preserving v1 replay and the parent's hard cap."""

from types import SimpleNamespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.application import rb3_deadline as rb3
from proofops.domain.provenance import canonical_hash

V29_HASH = "6dfce1611d0293822638a569bebd40c5e6bafcaf5fffe70922016dead84c1b1d"


def test_v29b_changes_only_deadline_and_keeps_v29_replay():
    current = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I29B_POLICY)
    )
    assert current["integration_profile"] == "finals-20261016-v29b"
    assert current == profiles.FINALS_I29_POLICY | dict(
        integration_profile="finals-20261016-v29b", rb3_deadline=rb3.POLICY_V2
    )
    assert canonical_hash(profiles.FINALS_I29_POLICY) == V29_HASH
    for selected in (current, profiles.FINALS_I29_POLICY, profiles.FINALS_I29_INITIAL_POLICY):
        pin = canonical_hash(selected)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected


def test_v2_admits_observed_lgchem_timeline_and_latches_at_new_cutoffs():
    now = [0.0]
    budget = rb3.Deadline(9999, policy=rb3.POLICY_V2, clock=lambda: now[0])
    assert budget.hard_deadline == 2700
    now[0] = 203 + 304
    assert budget.admit("extract") and budget.admit("tag")
    now[0] += 725
    assert budget.admit("tag")  # v1 stopped at 1200, before this measured tag finish
    now[0] = 1500
    assert not budget.admit("extract") and budget.admit("tag")
    now[0] = 2399.999
    assert budget.admit("tag")
    now[0] = 2400
    assert not budget.admit("tag")
    now[0] = 0
    assert not budget.admit("extract") and not budget.admit("tag")
    assert budget.summary() == dict(policy=rb3.POLICY_V2, stopped_stages=["extract", "tag"])


def test_v2_never_extends_shorter_parent_deadline():
    budget = rb3.Deadline(1800, policy=rb3.POLICY_V2, clock=lambda: 0)
    assert budget.hard_deadline == 1800


@pytest.mark.parametrize("version", ["POLICY", "POLICY_V2"])
def test_parent_selects_exact_policy(monkeypatch, version):
    policy = getattr(rb3, version)
    monkeypatch.setenv(rb3.DEADLINE_ENV, "9999999999")
    assert rb3.configured(dict(rb3_deadline=policy))
    budget = rb3.from_parent(dict(rb3_deadline=policy))
    assert budget.summary()["policy"] == policy
    assert 0 < budget.hard_deadline - budget.clock() <= policy["hard_cap_seconds"]
    monkeypatch.delenv(rb3.DEADLINE_ENV)
    with pytest.raises(ValueError, match="RB3_DEADLINE_REQUIRED"):
        rb3.from_parent(dict(rb3_deadline=policy))
    with pytest.raises(ValueError, match="RB3_DEADLINE_POLICY_MISMATCH"):
        rb3.configured(dict(rb3_deadline=policy | dict(tag_reserve_seconds=0)))


def test_runtime_cannot_use_v2_budget_for_historical_v1_snapshot():
    runner = SimpleNamespace(rb3_deadline=rb3.Deadline(2700, policy=rb3.POLICY_V2))
    with pytest.raises(ValueError, match="RB3_DEADLINE_POLICY_MISMATCH"):
        rb3.admit(runner, dict(analysis_profile_policy=dict(rb3_deadline=rb3.POLICY)), "tag")


def test_hosted_default_watchdog_supports_2700_seconds(monkeypatch):
    import os
    import subprocess
    import sys

    monkeypatch.delenv("HOSTED_ANALYSIS_TIMEOUT_SECONDS", raising=False)
    code = (
        "from proofops_api.hosted_analysis import ANALYSIS_TIMEOUT_SECONDS;"
        "print(ANALYSIS_TIMEOUT_SECONDS)"
    )
    assert subprocess.check_output([sys.executable, "-c", code], text=True).strip() == "2700"
    assert (
        subprocess.check_output(
            [sys.executable, "-c", code],
            text=True,
            env=os.environ | {"HOSTED_ANALYSIS_TIMEOUT_SECONDS": "1800"},
        ).strip()
        == "1800"
    )


def test_hosted_child_accepts_new_and_historical_v29(tmp_path):
    from tests.integration.test_i28_profile import test_hosted_child_preserves_integrated_pins

    for selected in (profiles.V2_POLICY, profiles.FINALS_I29_POLICY):
        test_hosted_child_preserves_integrated_pins(tmp_path, selected)
