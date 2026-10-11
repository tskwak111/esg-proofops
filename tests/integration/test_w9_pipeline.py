"""Real parser grid → source-ID wire → restored cell spans, without dispatch."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from proofops.adapters.parsing.upstage_document import candidate_batch
from proofops.application.ingest.graph_fusion import ParserProfile, fuse_candidates
from proofops.application.ingest.w9_tables import PROFILE
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.w9_table_replay import OfflineProbe, packet
from tests.unit.test_pb1_source import fixture
from tests.unit.test_pb4_source import FIXTURE, naver_case


def test_real_multiline_parser_wire_and_response_use_the_same_cell_ids(tmp_path):
    _, source, _ = naver_case()
    profile = ParserProfile(str(uuid4()), parser_mode="upstage", table_claims_profile=PROFILE)
    raw = json.loads((FIXTURE / "naver-p88-table.json").read_text())
    batch, _ = candidate_batch(
        source,
        profile,
        (1,),
        [
            dict(
                model="document-parse-260128",
                usage=dict(pages=1, enhanced=[1]),
                elements=raw["elements"],
            )
        ],
        mode="enhanced",
        config_hash=profile.config_hash(),
    )
    graph = fuse_candidates((batch,), tenant_id=source.tenant_id)
    table = next(b for b in graph.blocks if b.kind == "table")
    assert PROFILE in table.candidates[table.winner].context
    extractor = UpstageClaimExtractor(
        OfflineProbe(),
        tmp_path,
        extraction_source_ids=True,
        extraction_context=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
    )
    data = packet(graph, table)
    system, wire, _ = extractor._source_id_wire(
        data, table.normalized_text, canonical_hash(data), graph
    )
    assert canonical_hash(system) == extractor.profile.prompt_sha256
    entries = wire["untrusted_document_data"]["source_sentences"]
    selected = next(e for e in entries if "12,932" in e["text"])
    assert "\t" not in selected["text"] and "16,673" not in selected["text"]
    spans, _ = extractor._resolve_payload(
        {"sentence_ids": [selected["sentence_id"]]},
        table.normalized_text,
        table.source_id,
        packet=data,
        context_graph=graph,
    )
    assert len(spans) == 1 and spans[0].quote == selected["text"]
    from proofops.adapters.local import upstage_ocr_profile_v10 as native

    ref = table.source_ref(
        normalized_char_start=spans[0].char_start, normalized_char_end=spans[0].char_end
    )
    assert (
        native.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "verified"
    )
    with pytest.raises(ValueError, match="unknown or repeated sentence id"):
        extractor._resolve_payload(
            {"sentence_ids": ["invented"]},
            table.normalized_text,
            table.source_id,
            packet=data,
            context_graph=graph,
        )
    bad = dict(data, tenant_id=str(uuid4()))
    with pytest.raises(ValueError, match="IDENTITY"):
        extractor._row_entries(bad, table.normalized_text, [], context_graph=graph)


def test_pb1_and_w9_receipts_are_separate_and_free(tmp_path):
    graph, _, _ = fixture()
    batches = tuple(
        replace(b, blocks=tuple(replace(c, context=(*c.context, PROFILE)) for c in b.blocks))
        for b in graph.candidates
    )
    graph = fuse_candidates(batches, tenant_id=graph.tenant_id)
    table = next(b for b in graph.blocks if b.kind == "table")
    data = packet(graph, table)
    legacy = UpstageClaimExtractor(
        OfflineProbe(), tmp_path, extraction_context=True, extraction_pb1=True
    )
    new = UpstageClaimExtractor(
        OfflineProbe(), tmp_path, extraction_context=True, extraction_pb1=True, extraction_w9=True
    )
    old = legacy.extract(data, context_graph=graph)
    new_result = new.extract(data, context_graph=graph)
    assert new_result == old
    assert len(list(tmp_path.glob("pb1-*"))) == 2
    assert new.extract(data, context_graph=graph) == new_result
    assert len(list(tmp_path.glob("pb1-*"))) == 2


def test_new_pilot_persists_w9_and_resume_keeps_its_pins(tmp_path, monkeypatch):
    import os
    import sys

    from proofops.application.analysis_profile import V2_POLICY

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
    assert settings["extraction_w9"] is manifest["extraction_w9"] is True
    assert json.loads((state / "parser.json").read_text())["table_claims_profile"] == PROFILE
    assert (
        settings["extraction_profile"]["rule_sha256"]
        != UpstageClaimExtractor(
            OfflineProbe(), tmp_path / "old", extraction_pb1=True
        ).profile.rule_sha256
    )
    saved = {p.name: p.read_bytes() for p in (state / "pilot.json", state / "settings.json")}
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all((state / name).read_bytes() == raw for name, raw in saved.items())
    assert V2_POLICY["table_claims"] == PROFILE
