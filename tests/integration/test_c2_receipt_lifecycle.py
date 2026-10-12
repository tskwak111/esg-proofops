"""Synthetic inputs; real guarded tags, SQLite, CAS, loader and export encoding.

Original-PDF and paid-provider validation are the separate evaluation artifacts.
The experimental profile remains disabled, including reviewer activation.
"""

import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local.job_store import LocalSQLiteJobStore
from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.local.tag_store import LocalTagStore
from proofops.application.authorization import AuthContext
from proofops.application.budget import TokenUsage
from proofops.application.evidence.retrieval import (
    freeze_packet,
    freeze_track_packet,
    retrieve_evidence,
)
from proofops.application.exports import (
    REVISION_RECORDS_V2,
    decode_revision_record,
    encode_revision_record,
)
from proofops.application.reviews import ReviewInputs, ReviewRejected, ReviewService
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.fact_assembly_c2 import assemble
from proofops.application.tagging.service import RawTagResponse
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext

from tests.acceptance.test_retrieval import SyntheticSearch
from tests.acceptance.test_tagging import execute, setup
from tests.unit.test_c2_assembly import case, seal

RUN = "44444444-4444-4444-8444-444444444444"


def inputs_for(tmp_path):
    data, votes = case()
    graph, context, pack = data["graph"], data["context"], data["rulepack"]
    claim = context.claim
    original = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=claim.tenant_id,
        run_id=RUN,
        index_generation="synthetic-v1",
        rulepack=pack,
        document_context={},
        token_counter=lambda t: len(t) // 4,
    )
    track = TrackCandidate(claim, "management", None)
    packet = freeze_track_packet(original, track=track, rulepack=pack)
    raw = packet.to_dict()
    raw.pop("packet_sha256")
    packet = freeze_packet(raw | dict(c2_sources=data["packet"].to_dict()["c2_sources"]))
    for v in votes:
        v["identity"]["packet_sha256"] = packet.packet_sha256
    receipt = assemble(
        [seal(v) for v in votes], context=context, graph=graph, packet=packet, rulepack=pack
    )
    tagging = setup(tmp_path)

    def responder(request):
        rid = request["replicate_id"]
        elements = [
            dict(
                element_id=f"M{i}",
                state="present" if i <= 4 else "unknown",
                evidence_refs=[asdict(claim.source_refs[0])] if i <= 4 else [],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            )
            for i in range(1, 7)
        ]
        value = dict(
            claim_id=claim.claim_id,
            packet_sha256=packet.packet_sha256,
            replicate_id=rid,
            track="management",
            safe_harbor_category=None,
            elements=elements,
            superlative_quote=None,
            warnings=[],
        )
        return RawTagResponse(
            json.dumps(value), TokenUsage(10, 10, 0, 0, 1, "succeeded", f"fixture-{rid}"), True
        )

    tagging.update(
        packet=packet,
        context=context,
        track=track,
        original=graph,
        rulepack=pack,
        relation_tags={},
        invoke=responder,
    )
    runs = execute(tagging)
    consensus = form_consensus(
        runs,
        packet=packet,
        rulepack=pack,
        tenant_id=claim.tenant_id,
        tag_revision=1,
        profile="partial-facts-v2",
    )
    assert consensus.confirmed_tags
    inputs = ReviewInputs(
        RUN,
        context,
        graph,
        pack,
        RuleContext(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            local_synthetic=True,
        ),
        packet,
        original,
        runs,
        consensus,
        {},
        fact_assembly_profile="partial-facts-v2",
        fact_assembly_receipt=receipt,
    )
    inputs.validate()
    return inputs


def test_positive_candidate_sqlite_resume_reload_cas_export_and_old_hashes(tmp_path, monkeypatch):
    inputs = inputs_for(tmp_path)
    claim = inputs.context.claim
    assert inputs.fact_assembly_receipt.to_dict()["candidate_auto_confirmed"]
    jobs = LocalSQLiteJobStore(tmp_path / "state.sqlite")
    jobs.create_run(claim.tenant_id, RUN, claim.document_version_id)
    store = LocalSQLiteReviewStore(jobs)
    service = ReviewService(store, load_inputs=lambda *args: inputs)
    review = service.publish(inputs)
    before = store.history(claim.tenant_id, RUN, claim.claim_id)
    assert service.publish(inputs) == review  # resume writes no new revision
    assert before == store.history(claim.tenant_id, RUN, claim.claim_id)
    raw = before["tags"][0]["inputs"]
    assert raw["fact_assembly_receipt"] == inputs.fact_assembly_receipt.to_dict()
    runstore = LocalSQLiteRunStore(jobs.path)
    tags = LocalTagStore(runstore, None, None)
    # Supply an explicit synthetic immutable extraction/checkpoint boundary.
    # The loader below still reconstructs every stored run, consensus and receipt.
    envelope = dict(claims=[dict(claim_id=claim.claim_id, review_inputs=raw)])
    evidence = ({}, SimpleNamespace(claims=(claim,)), inputs.original)
    monkeypatch.setattr(tags, "_load_snapshot_with_evidence", lambda *a: (envelope, evidence))
    get_run = runstore.jobs.get_run
    monkeypatch.setattr(runstore.jobs, "get_run", lambda *a: get_run(*a) | dict(tag_job={}))
    monkeypatch.setattr(runstore, "snapshot", lambda *a: dict(rulepack=asdict(inputs.rulepack)))
    reopened = tags.load_inputs(claim.tenant_id, RUN, claim.claim_id)
    assert reopened.snapshot() == inputs.snapshot()
    actor = AuthContext(
        "operator", claim.tenant_id, "reviewer", frozenset({"viewer", "reviewer"}), "test"
    )
    body = dict(
        base_tag_revision=1,
        track="management",
        reason="원문 태깅 검토",
        elements=[asdict(e) for e in inputs.consensus.candidate_elements],
    )
    with pytest.raises(ReviewRejected) as stale:
        service.resolve_review(
            actor, review["review_id"], body, if_match='"2"', idempotency_key="c2-stale-cas-request"
        )
    assert (stale.value.status, stale.value.code) == (412, "STALE_REVIEW_REVISION")
    with pytest.raises(ReviewRejected, match="C2_PUBLICATION_DISABLED"):
        service.resolve_review(
            actor, review["review_id"], body, if_match='"1"', idempotency_key="c2-fresh-cas-request"
        )
    after = store.history(claim.tenant_id, RUN, claim.claim_id)
    assert after == before
    record = encode_revision_record(before["tags"][0], None, raw)
    export_hash = canonical_hash(record)
    decoded = decode_revision_record(json.loads(json.dumps(record)), encoding=REVISION_RECORDS_V2)
    assert decoded["original_inputs"]["fact_assembly_receipt"] == raw["fact_assembly_receipt"]
    assert decoded["decision"] is None
    assert canonical_hash(record) == export_hash
    assert canonical_hash(before) == canonical_hash(after)


def test_receipt_identity_tampering_or_public_decision_refused_before_storage(tmp_path):
    from proofops.adapters.local.tag_store import _fact_assembly_reader

    inputs = inputs_for(tmp_path)
    raw = inputs.fact_assembly_receipt.to_dict()
    raw["public_auto_confirmed"] = True
    changed = replace(inputs, fact_assembly_receipt=_fact_assembly_reader(raw))
    with pytest.raises(ReviewRejected, match="FACT_ASSEMBLY_REPLAY"):
        changed.validate()
