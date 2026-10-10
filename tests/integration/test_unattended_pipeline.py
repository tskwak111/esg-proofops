"""PT1: opt-in completion preserves source and confirmed revision boundaries."""

import json
from dataclasses import replace

from proofops.application.runs import RunService

from tests.integration.test_local_tag_runner import TENANT, verified_setup


def setup(tmp_path, monkeypatch):
    init = RunService.__init__

    def unattended(self, *args, **kwargs):
        kwargs["pipeline_profile"] = "unattended-v1"
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", unattended)
    return verified_setup(tmp_path, monkeypatch)


def test_unverified_proceeds_without_confirmed_revision(tmp_path, monkeypatch):
    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    discovery = replace(
        discovery, claims=tuple(replace(c, source_quality="unverified") for c in discovery.claims)
    )
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (extraction, discovery, graph))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    item = runner.tags.load_snapshot(TENANT, run_id)["claims"][0]
    assert len(item["tag_runs"]) == 3
    assert item["source_status"]["status"] == "unverified"
    assert item["source_status"]["display"] == "원문 확인 필요"
    assert item["decision"] is None and item["review_inputs"] is None
    assert item["provisional_grade"]["display"] == "잠정·미확정"


def test_claim_exception_isolated_and_private(tmp_path, monkeypatch):
    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    runner.preliminary = lambda *_: (_ for _ in ()).throw(RuntimeError("private source text"))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    assert envelope["claims"][0]["status"] == "failed"
    assert "private source text" not in json.dumps(envelope)
    assert envelope["completion"]["claims_terminal"] == len(envelope["claims"])


def test_budget_exhaustion_is_normal_completion(tmp_path, monkeypatch):
    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    from proofops.application.budget import BudgetExceeded

    runner.preliminary = lambda *_: (_ for _ in ()).throw(BudgetExceeded("BUDGET_EXHAUSTED"))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    item = runner.tags.load_snapshot(TENANT, run_id)["claims"][0]
    assert item["status"] == "budget_unanalyzed"
    assert item["reason_display"] == "예산 상한으로 미분석"


def test_two_of_three_provisional_keeps_unknown(tmp_path):
    from proofops.application.tagging.unattended import provisional_result
    from proofops.domain.rules.engine import RuleContext

    from tests.acceptance.test_tagging import execute
    from tests.acceptance.test_tagging import setup as tagging_setup

    inputs = tagging_setup(tmp_path)
    inputs["invoke"].changes[3] = {"element": {"state": "unknown", "evidence_refs": []}}
    runs = tuple(replace(run, product_variant=False) for run in execute(inputs))
    context = RuleContext(
        inputs["tenant_id"],
        inputs["context"].claim.document_version_id,
        inputs["context"].claim.claim_id,
        inputs["packet"].packet_sha256,
        local_synthetic=True,
    )
    result = provisional_result(runs, inputs["packet"], inputs["rulepack"], context)
    p1 = next(e for e in result["elements"] if e["element_id"] == "P1")
    assert p1["state"] == "present" and p1["votes"] == 2 and p1["provisional"] is True
    assert next(e for e in result["elements"] if e["element_id"] == "P2")["state"] == "unknown"
    assert result["evidence_grade"] == "E1"
    assert result["grade_basis"] == "reachable_floor"
    assert result["decision_status"] == "provisional"


def test_failed_claim_does_not_stop_later_claim(tmp_path, monkeypatch):
    from uuid import uuid4

    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    extraction, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    first = discovery.claims[0]
    later = replace(first, claim_id=str(uuid4()))
    discovery = replace(discovery, claims=(first, later))
    monkeypatch.setattr(runner.claims, "load_evidence", lambda *_: (extraction, discovery, graph))
    original = runner.preliminary

    def preliminary(claim, document):
        if claim.claim_id == first.claim_id:
            raise RuntimeError("private")
        return original(claim, document)

    runner.preliminary = preliminary
    # Exercise the real operation/fences; the added synthetic claim isn't in the
    # immutable extraction checkpoint, so do not attempt to publish that fixture.
    from tests.integration.test_local_tag_runner import tag_message

    message = tag_message(service, run_id, runner.clock())
    lease = service.store.jobs.claim_job(
        message, owner="PT1-test", now=runner.clock(), lease_seconds=300
    )
    result = json.loads(
        runner._execute(lease, service.store.snapshot(TENANT, run_id), {"synthetic_calls": 0})
    )
    assert result["stage_status"] == "completed"
    assert result["claims"][0]["status"] == "failed"
    assert len(result["claims"][1]["tag_runs"]) == 3


def test_unverified_dimensions_are_never_promoted():
    from proofops.application.tagging.preliminary import preliminary_request, validate_preliminary

    from tests.acceptance.test_binding import corpus

    graph, claim, refs = corpus()
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, quality="unverified") if b.source_id == refs[0].source_id else b
            for b in graph.blocks
        ),
    )
    claim = replace(claim, source_quality="unverified")
    packet = preliminary_request(claim, graph, tenant_id=claim.tenant_id, allow_unverified=True)
    quote = packet["untrusted_document_data"]["sources"][0]["text"]
    result = validate_preliminary(
        claim,
        graph,
        {
            "claim_id": claim.claim_id,
            "track": "performance",
            "safe_harbor_category": None,
            "track_confidence": 0.5,
            "dimensions": {
                "entity": None,
                "metric": {"source_index": 0, "quote": quote},
                "reporting_period": None,
            },
        },
        tenant_id=claim.tenant_id,
        allow_unverified=True,
    )
    assert result.track is not None
    assert result.context.dimensions["metric"] is None


def test_extraction_provider_failure_preserves_unknown_region():
    from proofops.application.claims import ExtractionOutputError
    from proofops_worker.extract_runner import _candidate_extract

    class Failed:
        def extract(self, packet):
            raise ValueError("OPENAI_HTTP_503")

    import pytest

    with pytest.raises(ExtractionOutputError):
        _candidate_extract(Failed(), {}, {"pipeline_profile": "unattended-v1"})
    with pytest.raises(ValueError, match="OPENAI_HTTP_503"):
        _candidate_extract(Failed(), {}, {})


def test_provisional_refuses_replayed_provider_response(tmp_path):
    from proofops.application.tagging.unattended import provisional_result
    from proofops.domain.rules.engine import RuleContext

    from tests.acceptance.test_tagging import execute
    from tests.acceptance.test_tagging import setup as tagging_setup

    inputs = tagging_setup(tmp_path)
    runs = execute(inputs)
    runs = tuple(
        replace(r, usage=replace(r.usage, provider_request_id="same-response")) for r in runs
    )
    context = RuleContext(
        inputs["tenant_id"],
        inputs["context"].claim.document_version_id,
        inputs["context"].claim.claim_id,
        inputs["packet"].packet_sha256,
        local_synthetic=True,
    )
    result = provisional_result(runs, inputs["packet"], inputs["rulepack"], context)
    assert result["reason"] == "PROVIDER_RESPONSE_REPLAY"
    assert result["evidence_grade"] is None
