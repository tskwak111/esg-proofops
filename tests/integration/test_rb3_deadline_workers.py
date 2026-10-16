"""Deadline holds keep finished tags, source validation and cancellation fences."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from proofops.application.ports.jobs import LeaseLost
from proofops.application.rb3_deadline import POLICY, POLICY_V2, Deadline

from tests.integration.test_local_tag_runner import TENANT, tag_message
from tests.integration.test_unattended_pipeline import setup


def operation(tmp_path, monkeypatch, policy=POLICY):
    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    first = discovery.claims[0]
    discovery = replace(
        discovery, claims=(first, *(replace(first, claim_id=str(uuid4())) for _ in range(2)))
    )
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (extraction, discovery, graph))
    snapshot = service.store.snapshot(TENANT, run_id) | dict(
        analysis_profile_policy=dict(rb3_deadline=policy)
    )
    message = tag_message(service, run_id, runner.clock())
    lease = service.store.jobs.claim_job(
        message, owner="rb3-test", now=runner.clock(), lease_seconds=300
    )
    now = [0.0]
    runner.rb3_deadline = Deadline(policy["hard_cap_seconds"], policy=policy, clock=lambda: now[0])
    return runner, snapshot, lease, now


@pytest.mark.parametrize("policy,cutoff", [(POLICY, 1200), (POLICY_V2, 2400)])
def test_completed_claim_retains_three_replicas_remaining_claims_are_time_holds(
    tmp_path, monkeypatch, policy, cutoff
):
    runner, snapshot, lease, now = operation(tmp_path, monkeypatch, policy)
    original = runner.preliminary
    calls = []

    def preliminary(claim, graph):
        calls.append(claim.claim_id)
        answer = original(claim, graph)
        now[0] = cutoff
        return answer

    runner.preliminary = preliminary
    result = json.loads(runner._execute(lease, snapshot, {"synthetic_calls": 0}))
    first, *held = result["claims"]
    assert len(first["tag_runs"]) == 3
    assert first["reason"] != "TIME_BUDGET"
    assert len(calls) == 1
    assert len(held) == 2
    assert all(item["reason"] == "TIME_BUDGET" for item in held)
    assert all(not item["tag_runs"] and item["decision"] is None for item in held)
    assert all(item["source_status"]["status"] == "verified" for item in held)
    assert all(item["provisional_grade"]["elements"] == [] for item in held)
    assert result["completion"]["claims_terminal"] == 3


@pytest.mark.parametrize("policy,cutoff", [(POLICY, 1200), (POLICY_V2, 2400)])
def test_deadline_never_bypasses_lease_loss(tmp_path, monkeypatch, policy, cutoff):
    runner, snapshot, lease, now = operation(tmp_path, monkeypatch, policy)
    now[0] = cutoff
    monkeypatch.setattr(runner.store.jobs, "can_call", lambda *a, **k: False)
    with pytest.raises(LeaseLost):
        runner._execute(lease, snapshot, {"synthetic_calls": 0})


@pytest.mark.parametrize("policy,cutoff", [(POLICY, 1200), (POLICY_V2, 2400)])
def test_deadline_does_not_skip_source_verification(tmp_path, monkeypatch, policy, cutoff):
    runner, snapshot, lease, now = operation(tmp_path, monkeypatch, policy)
    now[0] = cutoff

    def reject(*args):
        raise ValueError("SOURCE_TAMPERED")

    monkeypatch.setattr(runner.claims, "load_evidence", reject)
    with pytest.raises(ValueError, match="SOURCE_TAMPERED"):
        runner._execute(lease, snapshot, {"synthetic_calls": 0})


@pytest.mark.parametrize("continuation", [False, True])
@pytest.mark.parametrize("policy,cutoff", [(POLICY, 800), (POLICY_V2, 1500)])
def test_extraction_cutoff_preserves_paid_receipts_and_pending_sources(
    tmp_path, monkeypatch, continuation, policy, cutoff
):
    from proofops.adapters.local.claim_store import _deferred_reason
    from proofops_worker import extract_runner

    from tests.integration.test_extract_batch_continuation import published_state, setup_run
    from tests.integration.test_real_extract_runner import _freeze_upstage_price_clock

    _freeze_upstage_price_clock.__wrapped__(monkeypatch)
    service, run_id, runner, _, probe, _ = setup_run(tmp_path, monkeypatch, paragraphs=5, limit=2)
    now = [0.0]
    budget = Deadline(policy["hard_cap_seconds"], policy=policy, clock=lambda: now[0])
    # The transport fixture uses its historical synthetic profile. Bind only the
    # admission seam to the real deadline; keep its original snapshot/fences intact.
    monkeypatch.setattr(extract_runner, "rb3_admit", lambda r, s, stage: budget.admit(stage))
    if continuation:
        assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    previous = published_state(runner) if continuation else None
    before = len(probe.calls)
    complete = probe.complete

    def complete_and_expire(*args, **kwargs):
        response = complete(*args, **kwargs)
        now[0] = cutoff
        return response

    probe.complete = complete_and_expire
    if continuation:
        assert runner.run_batch(tenant_id=TENANT, run_id=run_id)["status"] == "committed"
    else:
        assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    state = published_state(runner)
    assert len(probe.calls) == before + 1
    assert len(state["model_processed"]) == before + 1
    assert not state["failed"]
    assert any(
        _deferred_reason(r["raw_response_json"]) == "TIME_BUDGET" for r in state["pending"].values()
    )
    if previous:
        assert all(
            state["model_processed"][sid] == receipt
            for sid, receipt in previous["model_processed"].items()
        )
    assert runner.run_batch(tenant_id=TENANT, run_id=run_id) == dict(
        status="partial", stop_code="TIME_BUDGET"
    )
    assert len(probe.calls) == before + 1
