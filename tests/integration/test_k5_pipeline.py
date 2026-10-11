import json
import os
import sqlite3
import sys
from argparse import Namespace
from dataclasses import asdict

import pytest
from proofops.application.analysis_profile import (
    FINALS_I4_POLICY,
    FINALS_K5_POLICY,
    apply_pilot_profile,
    policy_for,
)
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.ingest.k5_context import (
    configured_context,
    preliminary_context,
    sentence_context,
    superlative_errors,
)
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops_worker.live_tagging import LiveTaggingRuntime

from tests.acceptance.test_tagging import execute, setup
from tests.unit.test_k5_context import case


def test_explicit_pin_preserves_i4_and_extraction():
    assert (
        canonical_hash(FINALS_I4_POLICY)
        == "7381e57fb2ddc2bb75149eb7c0254c366cfb76a8478537f59075800a1ca193fe"
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I4_POLICY))
        == FINALS_I4_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_K5_POLICY))
        == FINALS_K5_POLICY
    )
    options = []
    for policy in (FINALS_I4_POLICY, FINALS_K5_POLICY):
        args = Namespace(
            analysis_profile="finals-unattended-v2", analysis_policy_sha256=canonical_hash(policy)
        )
        apply_pilot_profile(args)
        options.append({k: v for k, v in vars(args).items() if k.startswith("extraction_")})
    assert options[0] == options[1]
    graph, claim = case(["태양광 설비를 구축했습니다."], (0, "태양광 설비를 구축했습니다."))
    with pytest.raises(ValueError, match="POLICY_MISMATCH"):
        configured_context(
            claim, graph, FINALS_K5_POLICY | dict(sentence_context_policy_sha256="0" * 64)
        )


def test_k5_create_resume_freezes_the_new_policy_without_upgrading_old_runs(tmp_path, monkeypatch):
    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            "finals-unattended-v2",
            "--analysis-policy-sha256",
            canonical_hash(FINALS_K5_POLICY),
            "--pages",
            "1",
            "--claim-pages",
            "1",
            "--mixed-ocr-max-pages",
            "1",
        ],
    )
    assert pilot.main() == 0
    state = tmp_path / "state"
    with sqlite3.connect(state / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy"] == FINALS_K5_POLICY
    before = {name: (state / name).read_bytes() for name in ("settings.json", "pilot.json")}
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all((state / name).read_bytes() == raw for name, raw in before.items())


def test_preliminary_and_element_packets_receive_literal_context_without_evidence_credit(tmp_path):
    inputs = setup(tmp_path)
    graph, claim = inputs["original"], inputs["context"].claim
    context = sentence_context(claim, graph)
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.snapshot = dict(analysis_profile_policy=FINALS_K5_POLICY | dict(table_evidence=None))
    runtime.graph = graph
    before = inputs["packet"].to_dict()
    # Use only the K5 assembly boundary; other I4 policies are tested separately.
    runtime.snapshot["analysis_profile_policy"] = {
        k: v for k, v in FINALS_K5_POLICY.items() if k.startswith("sentence_context")
    }
    inputs["packet"] = runtime.display_packet(inputs["packet"], claim=claim)
    after = inputs["packet"].to_dict()
    assert after["sentence_context"] == context
    assert after["evidence_candidates"] == before["evidence_candidates"]
    runs = execute(inputs)
    assert len(runs) == 3
    for request in inputs["invoke"].requests:
        wire = json.loads(request["user_json"])["untrusted_document_data"]
        assert wire["sentence_context"] == context
        assert wire["sentence_context"]["rule_credit"] is False
    prep = preliminary_context(
        dict(context_policy=dict(max_context_chars=2000), untrusted_document_data={}), context
    )
    assert prep["untrusted_document_data"]["context_blocks"][0]["text"] == context["text"]
    saved = [r.raw_response_json for r in runs]
    assert [r.raw_response_json for r in execute(inputs)] == saved
    assert len(inputs["invoke"].requests) == 3


def test_tampered_context_refuses_dispatch_and_preserves_unknown(tmp_path):
    inputs = setup(tmp_path)
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    context = sentence_context(inputs["context"].claim, inputs["original"])
    data["sentence_context"] = context | dict(text="원문 없는 주어와 2030년 목표")
    inputs["packet"] = freeze_packet(data)
    with pytest.raises(DomainValidationError, match="SENTENCE_CONTEXT_SOURCE_MISMATCH"):
        execute(inputs)
    assert inputs["invoke"].requests == []


def test_superlative_is_never_lost_and_never_admits_unverified_context():
    texts = ["2024년 업계 최초로 네온 기술을 협력사와 함께", "개발해 온실가스를 절감했습니다."]
    graph, claim = case(texts, (1, texts[1]))
    context = sentence_context(claim, graph)
    assert superlative_errors("업계 최초", claim.quote, context) == []
    assert superlative_errors(None, claim.quote, context) == ["K5_SUPERLATIVE_REQUIRES_RETAG"]
    assert superlative_errors("세계 최고", claim.quote, context) == ["SUPERLATIVE_SOURCE_INVALID"]
    assert superlative_errors(
        "업계 최초", claim.quote, context | dict(verification_state="candidate")
    ) == ["SUPERLATIVE_SOURCE_INVALID"]


def test_actual_preliminary_transport_carries_context_and_keeps_numbered_sources(
    tmp_path, monkeypatch
):
    from tests.integration.test_upstage_preliminary_transport import configured_with_context

    adapter, _, calls, request, packet, claim, graph = configured_with_context(
        tmp_path, monkeypatch
    )
    numbered = packet["untrusted_document_data"]["sources"]
    context = sentence_context(claim, graph)
    packet = preliminary_context(packet, context)
    request["packet_sha256"] = canonical_hash(packet)
    request["user_json"] = json.dumps(packet, ensure_ascii=False)
    adapter.count_input_tokens(request, counter=lambda system, user: 20)
    adapter.invoke(request)  # the provider HTTP boundary is a test double
    assert len(calls) == 1
    wire = json.loads(calls[0]["messages"][1]["content"])["untrusted_document_data"]
    assert wire["sources"] == numbered
    assert "\n".join(b["text"] for b in wire["context_blocks"]) == context["text"]


def test_claim_api_projects_context_and_source_locations_without_new_tags(tmp_path, monkeypatch):
    from proofops_api.routers.claims import build_claims_router

    from tests.integration.test_local_tag_runner import TENANT, verified_setup
    from tests.integration.test_run_lifecycle import client, validate

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    claim = runner.claims.list(TENANT, run_id)[0]
    context = dict(
        policy=FINALS_K5_POLICY["sentence_context_policy"],
        text=claim.quote,
        source_refs=[asdict(r) for r in claim.source_refs],
        verification_state="candidate",
        role="parent_paragraph",
        rule_credit=False,
    )
    envelope["claims"][0]["sentence_context"] = context
    monkeypatch.setattr(runner.tags, "load_snapshot", lambda *args: envelope)
    http, auth = client(service)
    http.app.include_router(
        build_claims_router(runner.claims, auth, tags=runner.tags, clock=lambda: now[0])
    )
    response = http.get(f"/v1/runs/{run_id}/claims/{claim.claim_id}")
    assert response.status_code == 200, response.text
    validate("ClaimDetail", response.json())
    projected = response.json()["review_projection"]["sentence_context"]
    assert projected["text"] == context["text"]
    assert projected["source_refs"][0]["page_num"] == claim.source_refs[0].page_num
    assert response.json()["claim"]["decision"] is None
