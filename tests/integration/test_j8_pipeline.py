"""J8 opt-in, production composition, immutable receipts and source boundaries."""

import json
import os
import sqlite3
import sys
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from proofops.application.analysis_profile import (
    J3_POLICY,
    J8_POLICY,
    J8_PROFILE,
    V2_POLICY,
    policy_for,
)
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.j8_cells_replay import OfflineProbe, extractor


def test_j8_free_create_and_resume_pins_candidate_policy(tmp_path, monkeypatch):
    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            J8_PROFILE,
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
    manifest = json.loads((state / "pilot.json").read_text())
    assert settings["extraction_j8"] is manifest["extraction_j8"] is True
    assert settings["extraction_j3"] is settings["extraction_w9"] is True
    with sqlite3.connect(state / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy"] == J8_POLICY
    assert snapshot["analysis_profile_policy_sha256"] == canonical_hash(J8_POLICY)
    for policy in (J3_POLICY, V2_POLICY):
        assert policy_for(policy["profile"], pinned_hash=canonical_hash(policy)) == policy
        assert canonical_hash(policy) != canonical_hash(J8_POLICY)
    before = {p: p.read_bytes() for p in (state / "settings.json", state / "pilot.json")}
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_j8_literal_cells_and_native_source_identity(tmp_path):
    from proofops.adapters.local import upstage_ocr_profile_v10 as native
    from proofops.application.ingest.j8_cells import graph_cells

    from tests.unit.test_pb4_source import naver_case

    graph, source, table = naver_case()
    e = extractor(OfflineProbe(), tmp_path)
    packet = dict(
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        untrusted_document_data=dict(
            source_id=table.source_id,
            page_num=table.page_num,
            kind="table",
            text=table.normalized_text,
        ),
    )
    system, wire, _ = e._source_id_wire(
        packet, table.normalized_text, canonical_hash(packet), graph
    )
    assert canonical_hash(system) == e.profile.prompt_sha256
    entries = wire["untrusted_document_data"]["source_sentences"]
    selected = next(s for s in entries if "12,932" in s["text"])
    spans, _ = e._resolve_payload(
        {"sentence_ids": [selected["sentence_id"]]},
        table.normalized_text,
        table.source_id,
        packet=packet,
        context_graph=graph,
    )
    ref = table.source_ref(
        normalized_char_start=spans[0].char_start, normalized_char_end=spans[0].char_end
    )
    assert (
        native.cell_proof(graph, source.content, [ref], tenant_id=graph.tenant_id)[0]["status"]
        == "verified"
    )
    with pytest.raises(ValueError, match="IDENTITY"):
        e._row_entries(
            dict(packet, tenant_id=str(uuid4())), table.normalized_text, [], context_graph=graph
        )
    with pytest.raises(ValueError, match="unknown or repeated"):
        e._resolve_payload(
            {"sentence_ids": ["invented"]},
            table.normalized_text,
            table.source_id,
            packet=packet,
            context_graph=graph,
        )
    with pytest.raises(ValueError, match="GRID"):
        graph_cells(table, replace(graph, edges=()))


def test_j8_receipts_are_distinct_and_reject_forged_ancestry(tmp_path):
    from tests.integration.test_upstage_extraction import FakeProbe, packet

    text = "• 환경 목표를 승인하며 성과를 모니터링 • 기후 목표 성과를 보수에 반영"
    data = packet(text)
    probe = FakeProbe(
        json.dumps({"sentence_ids": [f"{data['untrusted_document_data']['source_id']}:0"]})
    )
    old = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=True,
    )
    new = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=True,
        extraction_j8=True,
    )
    previous = old.extract(dict(data, extraction_profile=asdict(old.profile)))
    result = new.extract(dict(data, extraction_profile=asdict(new.profile)))
    assert previous["spans"] == result["spans"]
    assert old.profile.rule_sha256 != new.profile.rule_sha256
    assert old.profile.prompt_sha256 != new.profile.prompt_sha256
    saved = {p: p.read_bytes() for p in tmp_path.glob("*/result.json")}
    assert len(saved) == 2
    assert old.extract(dict(data, extraction_profile=asdict(old.profile))) == previous
    assert new.extract(dict(data, extraction_profile=asdict(new.profile))) == result
    assert all(p.read_bytes() == raw for p, raw in saved.items())
    target = next(p for p in saved if json.loads(p.read_text())["profile"] == asdict(new.profile))
    forged = json.loads(target.read_text())
    forged["j3_refinements"][0]["parent_start"] = 99
    target.chmod(0o600)
    target.write_text(json.dumps(forged))
    with pytest.raises(ValueError, match="EXTRACTION_RECEIPT_EXISTS"):
        new.extract(dict(data, extraction_profile=asdict(new.profile)))


def test_j8_requires_the_pinned_j3_w9_and_source_id_paths(tmp_path):
    for options in (
        {},
        {"extraction_j3": True},
        {"extraction_j3": True, "extraction_w9": True, "extraction_pb1": True},
    ):
        with pytest.raises(ValueError, match="J8"):
            UpstageClaimExtractor(OfflineProbe(), tmp_path, extraction_j8=True, **options)


@pytest.mark.parametrize("profile,enabled", [(J8_PROFILE, False), ("finals-unattended-v2", True)])
def test_runtime_rejects_mislabeled_j8_candidate_policy(tmp_path, profile, enabled):
    from proofops_api.local_runtime import load_local_runtime

    from tests.integration.test_local_runtime_config import (
        _budget_limits,
        _parser_snapshot,
        _probe_extraction_profile,
        _write_json,
    )

    settings = dict(
        build_root=str(tmp_path),
        budget_limits=_budget_limits(),
        extraction_profile=_probe_extraction_profile(),
        extraction_limits=dict(max_calls=2, max_output_tokens=128),
        pipeline_profile=profile,
        extraction_j3=True,
        extraction_w9=True,
        extraction_pb1=True,
        extraction_source_ids=True,
        extraction_table_rows=True,
    )
    if enabled:
        settings["extraction_j8"] = True
        from proofops.application.analysis_profile import FINALS_I2_POLICY

        settings["analysis_policy_sha256"] = canonical_hash(FINALS_I2_POLICY)
    config = _write_json(tmp_path / "settings.json", settings)
    parser = _write_json(tmp_path / "parser.json", _parser_snapshot())
    rejection = "LOCAL_RUNTIME_CONFIG_INVALID" if enabled else "EXTRACTION_J8_INVALID"
    with pytest.raises(ValueError, match=rejection):
        load_local_runtime(
            dict(
                LOCAL_RUN_SETTINGS_PATH=str(config),
                LOCAL_PARSER_PROFILE_PATH=str(parser),
                LOCAL_EXTRACTION_MODE="upstage_probe",
                LOCAL_TAGGING_MODE="upstage_local",
            )
        )
