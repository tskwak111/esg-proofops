"""RB3 admission never changes evidence or authorizes an unfinished decision."""

from types import SimpleNamespace

import pytest
from proofops.application.rb3_deadline import POLICY, Deadline, admit, held_claim
from proofops.domain.provenance import canonical_hash


def snapshot():
    return dict(analysis_profile_policy=dict(rb3_deadline=POLICY))


def test_soft_cutoffs_keep_the_original_hard_limit_and_latch():
    now = [0.0]
    budget = Deadline(1800, clock=lambda: now[0])
    assert budget.admit("extract")
    now[0] = 800
    assert not budget.admit("extract")
    assert budget.admit("tag")
    now[0] = 1200
    assert not budget.admit("tag")
    now[0] = 0  # a clock regression cannot reopen a stopped stage
    assert not budget.admit("tag")
    assert budget.summary()["stopped_stages"] == ["extract", "tag"]


def test_opt_in_requires_exact_policy_and_runtime():
    runner = SimpleNamespace()
    assert admit(runner, {}, "tag")
    with pytest.raises(ValueError, match="RB3_DEADLINE_REQUIRED"):
        admit(runner, snapshot(), "tag")
    runner.rb3_deadline = Deadline(1800, clock=lambda: 1200)
    assert not admit(runner, snapshot(), "tag")
    with pytest.raises(ValueError, match="RB3_DEADLINE_POLICY_MISMATCH"):
        admit(runner, dict(analysis_profile_policy=dict(rb3_deadline={})), "tag")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_hard_deadline_is_rejected(value):
    with pytest.raises(ValueError, match="RB3_DEADLINE_INVALID"):
        Deadline(value, clock=lambda: 0)


def test_time_hold_has_no_absence_or_confirmation_authority():
    claim = SimpleNamespace(claim_id="claim", source_quality="verified")
    record = held_claim(claim)
    assert record["reason"] == "TIME_BUDGET"
    assert record["source_status"]["status"] == "verified"
    assert not record["tag_runs"]
    assert record["decision"] is None and record["review_inputs"] is None
    provisional = record["provisional_grade"]
    assert provisional["evidence_grade"] is None
    assert provisional["elements"] == []
    assert provisional["hold_reasons"] == ["TIME_BUDGET"]
    assert "근거 없음" not in str(record)


def test_rb3_pin_is_registered_without_changing_fxh_or_default():
    from proofops.application.analysis_profile import (
        FINALS_I25_POLICY,
        FXH_POLICY,
        RB3_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )

    assert canonical_hash(FXH_POLICY) == (
        "aabfb9ee0a2351cb84b39b1474ccd45cbeb50bb33dee39d6f9a0f39189c41e09"
    )
    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I25_POLICY)) == FINALS_I25_POLICY
    )
    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(RB3_POLICY)) == RB3_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(RB3_POLICY)) == RB3_POLICY


def test_parent_passes_its_own_deadline_and_does_not_accept_inherited_override(
    tmp_path, monkeypatch
):
    import json
    import os
    import sys
    import time

    from proofops.application.rb3_deadline import DEADLINE_ENV, from_parent
    from proofops_api import hosted_analysis

    monkeypatch.setenv(DEADLINE_ENV, "999999999999")
    assert from_parent({}) is None
    monkeypatch.setattr(hosted_analysis, "ANALYSIS_TIMEOUT_SECONDS", 20)
    store = SimpleNamespace(settings=SimpleNamespace(max_active_runs=1))
    target = tmp_path / "observed.json"
    code = (
        "import json,os,sys,time;"
        "from pathlib import Path;"
        f"Path(sys.argv[1]).write_text(json.dumps([float(os.environ[{DEADLINE_ENV!r}]),"
        "time.monotonic()]))"
    )
    before = time.monotonic()
    with (tmp_path / "analysis.lock").open("a+b") as lock:
        hosted_analysis.run_analysis_process(
            [sys.executable, "-c", code, str(target)], store, {}, lock
        )
    deadline, observed = json.loads(target.read_text())
    assert before + 20 <= deadline <= time.monotonic() + 20
    assert 0 < deadline - observed <= 20
    assert os.environ[DEADLINE_ENV] == "999999999999"
