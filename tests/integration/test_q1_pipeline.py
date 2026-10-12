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
