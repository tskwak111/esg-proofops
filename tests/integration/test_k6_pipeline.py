import json
from argparse import Namespace
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.application.analysis_profile import (
    FINALS_I4_POLICY,
    FINALS_K6_POLICY,
    apply_pilot_profile,
    publication_policy_for,
)
from proofops.domain.provenance import canonical_hash


def test_k6_is_explicit_and_old_i4_pins_and_prompts_are_unchanged():
    from proofops.adapters.local import i4_parse_scope, parse_table_cache

    assert (
        canonical_hash(FINALS_I4_POLICY)
        == "7381e57fb2ddc2bb75149eb7c0254c366cfb76a8478537f59075800a1ca193fe"
    )
    for policy, enabled in ((FINALS_I4_POLICY, False), (FINALS_K6_POLICY, True)):
        args = Namespace(
            analysis_profile="finals-unattended-v2", analysis_policy_sha256=canonical_hash(policy)
        )
        apply_pilot_profile(args)
        assert args.extraction_k6 is enabled
        assert (
            publication_policy_for(args.analysis_profile, pinned_hash=args.analysis_policy_sha256)
            == policy
        )
        snapshot = dict(
            analysis_profile_policy=policy, analysis_profile_policy_sha256=canonical_hash(policy)
        )
        with i4_parse_scope.for_snapshot(snapshot, "tenant", "run"):
            assert parse_table_cache._scope.get()[:2] == ("tenant", "run")
    assert FINALS_K6_POLICY["tagging_prompt_policy"] == FINALS_I4_POLICY["tagging_prompt_policy"]


def test_repeated_units_traverse_real_transport_restore_and_legacy_stays_unknown():
    from proofops.application.tagging.k6_citations import POLICY
    from proofops.application.tagging.pb6_citation_restore import POLICY as OLD
    from proofops_agent.upstage_tagging import UpstageTaggingTransport

    adapter = object.__new__(UpstageTaggingTransport)
    adapter._settings = SimpleNamespace(model_profile="upstage-compact-source-quotes-v5")
    adapter._display_catalog = None
    raw = "• 약 2,944 tCO₂를 저장, 연간 약 156 tCO₂ 흡수 (커넥트원 포함, 국립공주대학교 연구 결과)"
    refs = {"e0": dict(source_id="own", quote=raw, char_start=100, char_end=100 + len(raw))}
    payload = dict(
        elements=[
            dict(
                element_id="P1",
                state="present",
                normalized_value="2,944",
                evidence_refs=[dict(id="e0", quote=q) for q in ("2,944", "tCO₂", "156", "tCO₂")],
                credited_from=None,
            )
        ],
        warnings=[],
    )
    old = adapter.restore_payload(deepcopy(payload), refs, policy=OLD)
    assert old["elements"][0]["state"] == "unknown"
    restored = adapter.restore_payload(deepcopy(payload), refs, policy=POLICY)
    assert restored["elements"][0]["state"] == "present"
    for r in restored["elements"][0]["evidence_refs"]:
        assert raw[r["char_start"] - 100 : r["char_end"] - 100] == r["quote"]
    assert "156 tCO₂" in {r["quote"] for r in restored["elements"][0]["evidence_refs"]}
    unknown = deepcopy(payload)
    unknown["elements"][0].update(state="unknown", evidence_refs=[])
    assert (
        adapter.restore_payload(unknown, refs, policy=POLICY)["elements"][0]["state"] == "unknown"
    )


def test_boundary_candidates_cannot_grant_assurance_or_skip_source_verification():
    from proofops.application.evidence.retrieval import freeze_packet
    from proofops.application.tagging.k6_facilities import augment_packet

    from tests.acceptance.test_binding import corpus

    graph, claim, _ = corpus()
    ref = graph.blocks[0].source_ref()
    dimensions = dict(
        facility=dict(state="source_verified", source_refs=[asdict(ref)], rule_credit=False)
    )
    packet = freeze_packet(dict(allowed_elements=["M2", "P3", "P4"], evidence_candidates=[]))
    result = augment_packet(packet, dimensions, graph, tenant_id=graph.tenant_id).to_dict()
    assert result["evidence_candidates"][0]["allowed_elements"] == ["M2", "P3"]
    assert not any(k in result for k in ("elements", "assurance", "evidence_grade"))
    unverified = replace(
        graph, blocks=tuple(replace(b, quality="unverified") for b in graph.blocks)
    )
    assert augment_packet(packet, dimensions, unverified, tenant_id=graph.tenant_id) == packet
    with pytest.raises(Exception):
        augment_packet(packet, dimensions, graph, tenant_id="00000000-0000-0000-0000-000000000000")


def test_risk_goal_vote_is_vetoed_in_real_preliminary_validation(tmp_path, monkeypatch):
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.integration.test_live_tagging_worker import configured

    runtime, claim, graph, _, _, _ = configured(tmp_path, monkeypatch, context=True)
    quote = "에너지 사용량 증가가 예상됨에 따라 고효율 설비 투자 필요성 증가"
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
    runtime.snapshot["analysis_profile_policy"] = FINALS_K6_POLICY
    checked = []

    def replicas(prefix, selected, packet, settings, transport, records, validate, **kwargs):
        checked.append(prefix)
        with pytest.raises(ValueError, match="K6_RISK_WITHOUT_COMPANY_COMMITMENT"):
            validate(
                dict(
                    claim_id=selected.claim_id,
                    track="goal",
                    track_confidence=0.9,
                    safe_harbor_category=None,
                    dimensions=dict(entity=None, metric=None, reporting_period=None),
                )
            )
        return None

    monkeypatch.setattr(runtime, "_source_replicas", replicas)
    assert LiveTaggingRuntime.preliminary(runtime, claim, graph) is None
    assert checked == ["preliminary"]


def test_k6_settings_and_resume_use_matching_policy(tmp_path, monkeypatch):
    import os
    import sqlite3
    import sys

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
            canonical_hash(FINALS_K6_POLICY),
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
    assert settings["extraction_k6"] is True
    env = dict(
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
    )
    selected = load_local_runtime(env)
    assert selected["analysis_policy_sha256"] == canonical_hash(FINALS_K6_POLICY)
    tampered = settings.copy()
    tampered.pop("extraction_k6")
    wrong = state / "wrong-k6-settings.json"
    wrong.write_text(json.dumps(tampered))
    with pytest.raises(ValueError):
        load_local_runtime(env | dict(LOCAL_RUN_SETTINGS_PATH=str(wrong)))
    with sqlite3.connect(state / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy"] == FINALS_K6_POLICY
    before = (state / "settings.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert (state / "settings.json").read_bytes() == before
