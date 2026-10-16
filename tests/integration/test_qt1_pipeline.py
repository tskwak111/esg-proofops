import json
import os
import sys
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest
from proofops.application.analysis_profile import (
    FINALS_I23_POLICY,
    QT1_POLICY,
    apply_pilot_profile,
    policy_for,
    publication_policy_for,
)
from proofops.domain.provenance import canonical_hash


def graph(case):
    from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates

    value = json.loads(
        (Path(__file__).parents[1] / "fixtures/qt1/selected-parse.json").read_text()
    )[case]
    return fuse_candidates(
        candidates_from_snapshot(value["snapshot"]),
        tenant_id=value["snapshot"][0]["tenant_id"],
        fusion_version=value["fusion_version"],
        mixed_parser=True,
    )


def flags(policy):
    args = Namespace(
        analysis_profile="finals-unattended-v2", analysis_policy_sha256=canonical_hash(policy)
    )
    apply_pilot_profile(args)
    return {k: v for k, v in vars(args).items() if k.startswith("extraction_") and type(v) is bool}


def packet(g, b):
    return dict(
        tenant_id=g.tenant_id,
        document_version_id=g.document_version_id,
        parse_manifest_id=g.parse_manifest_id,
        source_sha256=g.source_sha256,
        untrusted_document_data=dict(
            source_id=b.source_id, page_num=b.page_num, kind=b.kind, text=b.normalized_text
        ),
    )


def test_production_extractor_reconciles_and_replays_without_transport(tmp_path):
    from proofops_agent.upstage_extraction import UpstageClaimExtractor
    from proofops_worker.extract_runner import _is_text_candidate

    from evaluation.w7_sentence_replay import NoTransport

    g = graph("kakao")
    b = next(b for b in g.blocks if b.source_id == "329e3926-72d9-5f66-8274-1f75f2251b0a")
    old = UpstageClaimExtractor(NoTransport(), tmp_path / "old", **flags(FINALS_I23_POLICY))
    new = UpstageClaimExtractor(NoTransport(), tmp_path / "new", **flags(QT1_POLICY))
    assert old.extract(packet(g, b), context_graph=g) == {"spans": []}
    recovered = new.extract(packet(g, b), context_graph=g)
    assert len(recovered["spans"]) == 5
    assert new.extract(packet(g, b), context_graph=g) == recovered
    assert old.profile.rule_sha256 != new.profile.rule_sha256
    assert old.profile.prompt_sha256 == new.profile.prompt_sha256
    assert _is_text_candidate(
        b.kind, b.normalized_text, graph=g, source_id=b.source_id, extraction_qt1=True
    )
    receipt = next((tmp_path / "new").glob("qt1-*.json"))
    saved = json.loads(receipt.read_text())
    assert all(x["status"] == "missing" for x in saved["coverage"])
    assert saved["candidates"][0]["unit"]["quote"] == "%"
    assert saved["candidates"][0]["values"][1]["quote"] == "11.5%"
    receipt.chmod(0o600)
    receipt.write_text("{}")
    with pytest.raises(ValueError, match="QT1_EXTRACTION_REPLAY_MISMATCH"):
        new.extract(packet(g, b), context_graph=g)
    with pytest.raises(ValueError):
        new.extract(
            packet(g, b) | dict(tenant_id="00000000-0000-0000-0000-000000000000"), context_graph=g
        )


def test_scoped_footnote_year_and_model_caption_never_borrow_page_year():
    from proofops.application.ingest.qt1_tables import candidates_for

    g = graph("kakao")
    b = next(b for b in g.blocks if b.source_id == "6f7a8883-6fcc-5df8-ace8-38cecd4c6732")
    row = next(r for r in candidates_for(b, g) if "253 tCO" in r["quote"])
    assert row["values"][0]["year"] == "2025"
    assert "2025년 운영 실적 기준" in row["values"][0]["year_source"]["source_ref"]["quote"]
    assert row["values"][0]["quote"] == "253 tCO₂eq"
    assert "물 재이용량(m3)을 함께" in row["values"][0]["year_source"]["source_ref"]["quote"]
    assert not row["eligible_for_scoring"]
    lg = graph("lg")
    contribution = next(
        x for x in lg.blocks if x.source_id == "468098f5-1dd5-5e48-9672-c38667557f84"
    )
    assert all(v["year"] == "2030" for r in candidates_for(contribution, lg) for v in r["values"])
    other = replace(g, tenant_id="00000000-0000-0000-0000-000000000000")
    # The public extractor, not this local metadata helper, validates graph/packet tenant.
    assert other.tenant_id != g.tenant_id
    g = graph("lge")
    b = next(b for b in g.blocks if b.source_id == "c41115f7-e1f9-59f5-9d22-58ff14bd737b")
    row = next(r for r in candidates_for(b, g) if "0.71kg" in r["quote"])
    assert "50UR8250KNA" in row["context_sources"][0]["source_ref"]["quote"]
    assert all(v["year"] is None for v in row["values"])
    # The same-page prose's 2024 is not a table header or footnote.
    assert candidates_for(replace(b, quality="conflicted", winner=None), g) == []
    unlocated = replace(
        b,
        candidates=tuple(
            replace(c, source=replace(c.source, native_bbox=None), parser_bbox=None)
            for c in b.candidates
        ),
    )
    assert candidates_for(unlocated, g) == []


def test_new_profile_create_resume_and_tamper_guard(tmp_path, monkeypatch):
    from proofops_api.local_runtime import load_local_runtime

    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I23_POLICY))
        == FINALS_I23_POLICY
    )
    pin = canonical_hash(QT1_POLICY)
    assert publication_policy_for("finals-unattended-v2", pinned_hash=pin) == QT1_POLICY
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            "finals-unattended-v2",
            "--analysis-policy-sha256",
            pin,
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
    path = state / "settings.json"
    saved = path.read_bytes()
    settings = json.loads(saved)
    assert settings["extraction_qt1"] is True
    env = dict(
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(path),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
    )
    load_local_runtime(env)  # Validates settings; worker composition consumes the opt-in.
    path.write_text(json.dumps(settings | dict(extraction_qt1=False)))
    with pytest.raises(ValueError):
        load_local_runtime(env)
    path.write_bytes(saved)
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0 and path.read_bytes() == saved
