"""Q1 opt-in wiring, persisted settings and forecast publication veto."""

import json
import os
import sys
from dataclasses import replace

import pytest
from proofops.application.analysis_profile import (
    FINALS_I9_POLICY,
    FINALS_Q1_POLICY,
    V2_POLICY,
    policy_for,
    publication_policy_for,
)
from proofops.domain.provenance import canonical_hash


def test_q1_keeps_existing_default_and_historical_pins():
    assert (
        canonical_hash(FINALS_I9_POLICY)
        == "b8086e636641355daf812bcbc8d0246a0bb14f57be5d81e77234a8b89f306c31"
    )
    assert V2_POLICY != FINALS_Q1_POLICY
    for policy in (FINALS_I9_POLICY, FINALS_Q1_POLICY):
        pin = canonical_hash(policy)
        assert policy_for("finals-unattended-v2", pinned_hash=pin) == policy
        assert publication_policy_for("finals-unattended-v2", pinned_hash=pin) == policy


def test_q1_create_resume_and_runtime_match_new_prompt_and_extraction_policy(tmp_path, monkeypatch):
    from proofops_api.local_runtime import load_local_runtime

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
            canonical_hash(FINALS_Q1_POLICY),
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
    settings = json.loads((state / "settings.json").read_text())
    assert settings["extraction_q1"] is True
    env = dict(
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
    )
    assert load_local_runtime(env)["analysis_policy_sha256"] == canonical_hash(FINALS_Q1_POLICY)
    forged = settings | dict(extraction_q1=False)
    (state / "forged.json").write_text(json.dumps(forged))
    with pytest.raises(ValueError):
        load_local_runtime(env | dict(LOCAL_RUN_SETTINGS_PATH=str(state / "forged.json")))
    before = (state / "settings.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert (state / "settings.json").read_bytes() == before


def test_q1_forecast_preliminary_cannot_reach_ordinary_rule_path(tmp_path, monkeypatch):
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.integration.test_live_tagging_worker import configured

    runtime, claim, graph, _, _, _ = configured(tmp_path, monkeypatch, context=True)
    quote = "2030년까지의 연도별 재무영향은 예상 매출액 대비 0.4% 미만입니다."
    ref = claim.source_refs[0]
    block = next(b for b in graph.blocks if b.source_id == ref.source_id)
    candidate = replace(
        block.candidates[block.winner],
        source=replace(block.candidates[block.winner].source, raw_text=quote, char_end=len(quote)),
    )
    changed = replace(block, candidates=(candidate,), winner=0, quality="verified")
    graph = replace(
        graph,
        blocks=tuple(changed if b.source_id == block.source_id else b for b in graph.blocks),
        candidates=tuple(
            replace(
                batch,
                blocks=tuple(
                    candidate if c == block.candidates[block.winner] else c for c in batch.blocks
                ),
            )
            for batch in graph.candidates
        ),
    )
    claim = replace(claim, quote=quote, source_refs=(changed.source_ref(),))
    runtime.graph = graph
    runtime.snapshot["analysis_profile_policy"] = FINALS_Q1_POLICY
    checked = []

    def replicas(prefix, selected, packet, settings, transport, records, validate, **kwargs):
        checked.append(prefix)
        with pytest.raises(ValueError, match="Q1_FORWARD_LOOKING_CATEGORY_REVIEW"):
            validate(
                dict(
                    claim_id=selected.claim_id,
                    track="performance",
                    track_confidence=0.9,
                    safe_harbor_category=None,
                    dimensions=dict(entity=None, metric=None, reporting_period=None),
                )
            )
        return None

    monkeypatch.setattr(runtime, "_source_replicas", replicas)
    assert LiveTaggingRuntime.preliminary(runtime, claim, graph) is None
    assert checked == ["preliminary"]


def test_forecast_hold_explanation_preserves_category_review():
    from proofops.application.tagging.quality import hold_projection
    from proofops.application.tagging.unattended import empty_provisional

    item = dict(
        provisional_grade=empty_provisional("Q1_FORWARD_LOOKING_CATEGORY_REVIEW"),
        preliminary_records=[
            dict(stable_reason=dict(error_code="Q1_FORWARD_LOOKING_CATEGORY_REVIEW"))
        ],
    )
    result = hold_projection(item, profile="k2-v1")
    assert result["evidence_grade"] is None and result["grade_range"] is None
    assert result["safe_harbor_candidate"] == "forward_looking"
    assert any("미래 전망" in reason for reason in result["hold_reasons"])
    assert "근거 없음" not in result["hold_reasons"]


def test_r12_element_renderer_and_request_pins_are_opt_in():
    from proofops.application.tagging.finals_i4 import elements_k4, preliminary_k4
    from proofops.application.tagging.k10_contract import elements
    from proofops.application.tagging.q1_contract import (
        R12_CLASSIFICATION_GUIDANCE,
        R12_ELEMENT_GUIDANCE,
        R12_POLICY,
    )

    schema = dict(type="object", properties={}, additionalProperties=False)
    classification = dict(track="management", safe_harbor_category=None)
    assert preliminary_k4(schema, quality_policy=R12_POLICY) == (
        preliminary_k4(schema) + R12_CLASSIFICATION_GUIDANCE
    )
    assert elements_k4(schema, classification, quality_policy=R12_POLICY) == (
        elements_k4(schema, classification) + R12_ELEMENT_GUIDANCE
    )
    prompt = elements(schema, classification, quality_policy=R12_POLICY)
    assert R12_ELEMENT_GUIDANCE in prompt
    assert "M5를 M1에 복사하지" in prompt
    assert len(prompt.encode()) < 16384


def test_r12_guard_preserves_period_rejection_and_historical_receipt(tmp_path):
    from dataclasses import asdict

    from proofops.application.evidence.binding import ClaimContext, local_relation_tags
    from proofops.application.evidence.retrieval import freeze_packet, freeze_track_packet
    from proofops.application.tagging.q1_contract import (
        R12_ELEMENT_GUIDANCE,
        R12_POLICY,
        SEMANTIC_POLICY,
    )
    from proofops.application.tagging.service import RawTagResponse, tag_replicates
    from proofops.application.tagging.tracks import TrackCandidate

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_tagging import setup

    inputs = setup(tmp_path)
    claim = inputs["context"].claim
    period = span(claim.source_refs[0], "Scope 1")
    # A non-date reporting role is diagnostic only, never repaired by R12.
    context = ClaimContext(claim, {"reporting_period": period})
    track = TrackCandidate(claim, "management", None)
    payload = {k: v for k, v in inputs["packet"].to_dict().items() if k != "packet_sha256"}
    for candidate in payload["evidence_candidates"]:
        candidate["allowed_elements"] = [f"M{i}" for i in range(1, 7)]
    payload.update(
        allowed_elements=[f"M{i}" for i in range(1, 7)],
        track="management",
        safe_harbor_category=None,
    )
    inputs.update(context=context, track=track, relation_tags=local_relation_tags(context))

    def invoke(request):
        response = inputs["invoke"](request)
        raw = json.loads(response.raw_response_json)
        raw["track"] = "management"
        raw["elements"] = [
            dict(
                element_id=f"M{i}",
                state="present" if i == 4 else "unknown",
                evidence_refs=[asdict(claim.source_refs[0])] if i == 4 else [],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            )
            for i in range(1, 7)
        ]
        return RawTagResponse(json.dumps(raw), response.usage, response.synthetic)

    outcomes = []
    for policy in (SEMANTIC_POLICY, R12_POLICY):
        settings = inputs["settings"]
        if policy == R12_POLICY:
            settings = replace(
                settings, system_prompt=settings.system_prompt + R12_ELEMENT_GUIDANCE
            )
        packet = freeze_track_packet(
            freeze_packet(payload | dict(structural_quality_policy=policy)),
            track=track,
            rulepack=inputs["rulepack"],
        )
        run = tag_replicates(**(inputs | dict(packet=packet, invoke=invoke, settings=settings)))
        outcomes.append(run)
    old, new = outcomes
    assert all(r.guarded for r in new)
    assert old[0].prompt_sha256 != new[0].prompt_sha256
    assert old[0].packet_sha256 != new[0].packet_sha256
    assert json.loads(new[0].raw_response_json)["elements"][3]["state"] == "present"
    assert new[0].guarded.elements[3].state == "unknown"
    assert new[0].guarded.elements[3].reason_code == "period_syntax_unsupported"
    assert "UNRESOLVED:M4:period_syntax_unsupported" in new[0].errors
    assert old[0].guarded.elements[3].reason_code is None

    from proofops.application.tagging.unattended import provisional_result
    from proofops.domain.rules.engine import RuleContext

    result = provisional_result(
        new,
        packet,
        inputs["rulepack"],
        RuleContext(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            local_synthetic=True,
        ),
        range_profile=True,
    )
    assert all(element["votes"] == 3 for element in result["elements"])


def test_r12_compiled_opt_in_prompt_survives_real_transport_json_projection(tmp_path, monkeypatch):
    from proofops.application.tagging.k10_contract import elements
    from proofops.application.tagging.q1_contract import R12_ELEMENT_GUIDANCE, R12_POLICY

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    approval = adapter._authorize(adapter._settings, request)
    assert approval.ready
    classification = dict(track="performance", safe_harbor_category=None)
    prompt = elements(
        dict(type="object", properties={}, additionalProperties=False),
        classification,
        quality_policy=R12_POLICY,
    )
    adapter._settings = replace(adapter._settings, system_prompt=prompt)
    approved_settings = adapter._settings

    def authorize(settings, dispatched):
        # This fixture explicitly approves this new opt-in prompt, not arbitrary settings.
        assert settings == approved_settings
        assert dispatched["system_prompt"].startswith(approved_settings.rendered_system)
        return approval

    adapter._authorize = authorize
    request["system_prompt"] = adapter._settings.system_for_track(**classification)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["structural_quality_policy"] = R12_POLICY
    request["user_json"] = json.dumps(user)
    system, wire, _, _, _ = adapter._wire_request(request)
    assert R12_ELEMENT_GUIDANCE in system
    assert "structural_quality_policy" not in json.loads(wire)["untrusted_document_data"]
    assert len((system + wire).encode()) < 16384
    assert not calls
