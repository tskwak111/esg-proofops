"""Execution-only pipeline: independent progress, bounded work and immutable pins."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash
from proofops_worker.spt_pipeline import configured, run_claims


def claim(index, quote="목표"):
    return SimpleNamespace(
        claim_id=str(index),
        quote=quote,
        source_quality="verified",
        source_refs=[SimpleNamespace(page_num=1, source_id="source", char_start=index)],
    )


def test_ready_claim_advances_while_another_claim_is_waiting():
    blocked, advanced = Event(), Event()
    lock = Lock()
    active = peak = 0

    def process(item):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            if item.claim_id == "0":
                blocked.set()
                assert advanced.wait(3)
            else:
                assert blocked.wait(3)
                advanced.set()
            return item.claim_id
        finally:
            with lock:
                active -= 1

    # One HTTP slot permits two in-progress claims; local work cannot impose
    # a whole-claim barrier. Results retain the original enumeration.
    assert run_claims(process, [claim(0), claim(1)], http_workers=1) == ["0", "1"]
    assert peak == 2


def test_queue_is_bounded_and_exception_does_not_start_remaining_claims():
    entered, release = Event(), Event()
    calls = []

    def process(item):
        calls.append(item.claim_id)
        entered.set()
        assert release.wait(3)
        raise ValueError("LEASE_LOST")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_claims, process, [claim(i) for i in range(50)], http_workers=2)
        assert entered.wait(3)
        release.set()
        with pytest.raises(ValueError, match="LEASE_LOST"):
            future.result()
    assert len(calls) <= 4


def test_priority_retains_source_and_budget_class_and_starts_long_tail_first():
    seen = []
    items = [claim(0, "목표"), claim(1, "목표" * 20), claim(2, "일반" * 50)]
    items.append(claim(3, "목표" * 100))
    items[-1].source_quality = "unresolved"
    assert run_claims(lambda c: seen.append(c.claim_id) or c.claim_id, items, http_workers=1) == [
        "0",
        "1",
        "2",
        "3",
    ]
    assert seen[0] == "1"
    assert seen.index("2") < seen.index("3")


def test_opt_in_default_replay_and_guard_policy():
    selected = profiles.SPT_POLICY
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I29B_POLICY)
        )
        == profiles.FINALS_I29B_POLICY
    )
    for policy in (profiles.FINALS_I29B_POLICY, profiles.FINALS_I29_POLICY, selected):
        assert (
            profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
        )
    assert configured(selected)
    assert not configured(profiles.FINALS_I29B_POLICY)
    assert selected == profiles.FINALS_I29B_POLICY | {
        "integration_profile": "spt_claim_pipeline_v1",
        "spt_claim_pipeline": selected["spt_claim_pipeline"],
    }
    with pytest.raises(ValueError, match="SPT_PIPELINE_POLICY_MISMATCH"):
        configured(selected | {"spt_claim_pipeline": {}})


def test_hosted_pin_and_presentation(tmp_path, monkeypatch):
    from tests.integration.test_i28_profile import test_hosted_child_preserves_integrated_pins
    from tests.unit.test_s2_result_annotations import (
        test_result_keeps_occurrence_metadata_with_legacy_facade,
    )

    test_hosted_child_preserves_integrated_pins(tmp_path, profiles.SPT_POLICY)
    test_result_keeps_occurrence_metadata_with_legacy_facade(
        tmp_path, monkeypatch, profiles.SPT_POLICY
    )
