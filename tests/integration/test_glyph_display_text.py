"""Fake glyph fixtures exercise the writer and real model/citation plumbing, no paid I/O."""

import json
from copy import deepcopy
from dataclasses import asdict
from threading import RLock

import pytest
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.application.claims import ExtractionOutputError
from proofops.application.ingest.display_text import POLICY, PROFILE, SYSTEM_SUFFIX
from proofops.application.tagging.preliminary import preliminary_request, validate_preliminary
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from tests.acceptance.test_binding import corpus
from tests.integration.test_upstage_extraction import (
    FakeProbe,
    _extraction_context_graph,
    packet,
)


def fixture_catalog(graph, deletions):
    catalog = object.__new__(GlyphDisplayCatalog)
    catalog.graph = graph
    catalog._blocks = {b.source_id: b for b in graph.blocks}
    catalog.identity = dict(
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
    )
    catalog._cache = {b.source_id: (deletions.get(b.source_id, []), []) for b in graph.blocks}
    catalog._lock = RLock()
    return catalog


@pytest.mark.parametrize("source_ids", [False, True])
@pytest.mark.parametrize("context", [False, True])
def test_extraction_display_wire_raw_restore_replay_and_tamper(tmp_path, source_ids, context):
    raw = "환 경 전담 부서는 환경 관리를 시행한다."
    graph, sid = _extraction_context_graph(text=raw, with_neighbors=context)
    catalog = fixture_catalog(graph, {sid: [1]})
    probe = FakeProbe()
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=source_ids, display_text_profile=PROFILE
    )
    data = packet(raw)
    data.update(source_sha256=graph.source_sha256, extraction_profile=asdict(extractor.profile))
    data["untrusted_document_data"]["source_id"] = sid
    if source_ids:
        sentence_id = extractor._sentence_index(raw, sid)[0][0]
        probe.content = json.dumps({"sentence_ids": [sentence_id]})
    else:
        probe.content = json.dumps({"claims": ["환경 전담 부서는 환경 관리를 시행한다."]})
    result = extractor.extract(data, context_graph=graph, display_catalog=catalog)
    span = result["spans"][0]
    assert span["quote"] == raw and (span["char_start"], span["char_end"]) == (0, len(raw))
    wire = json.loads(probe.calls[0]["user_json"])
    text = (
        wire["untrusted_document_data"]["source_sentences"][0]["text"]
        if source_ids
        else wire["untrusted_document_data"]["text"]
    )
    assert text == raw.replace("환 경", "환경")
    assert wire["display_policy"] == POLICY
    assert probe.calls[0]["system"].endswith(SYSTEM_SUFFIX)
    assert extractor.extract(data, context_graph=graph, display_catalog=catalog) == result
    assert len(probe.calls) == 1
    request = tmp_path / probe.calls[0]["request_id"] / "request.json"
    request.chmod(0o600)
    request.write_text("{}")
    with pytest.raises(ValueError, match="EXTRACTION_RECEIPT_EXISTS"):
        extractor.extract(data, context_graph=graph, display_catalog=catalog)


@pytest.mark.parametrize("quote", ["환경を 전담 부서", "環境担当部署", "없는 위치", "환경"])
def test_extraction_altered_foreign_and_repeated_display_quotes_reject(tmp_path, quote):
    raw = "환 경 전담 부서는 환경 관리를 시행한다."
    graph, sid = _extraction_context_graph(text=raw, with_neighbors=False)
    catalog = fixture_catalog(graph, {sid: [1]})
    probe = FakeProbe(json.dumps({"claims": [quote]}))
    extractor = UpstageClaimExtractor(probe, tmp_path, display_text_profile=PROFILE)
    data = packet(raw)
    data.update(source_sha256=graph.source_sha256, extraction_profile=asdict(extractor.profile))
    data["untrusted_document_data"]["source_id"] = sid
    with pytest.raises(ExtractionOutputError):
        extractor.extract(data, context_graph=graph, display_catalog=catalog)


def test_preliminary_display_restores_then_uses_unchanged_citation_gate():
    graph, claim, _ = corpus(claim_dimensions={"entity": "네 이버"})
    source = claim.source_refs[0]
    catalog = fixture_catalog(graph, {source.source_id: [source.quote.index("네 이버") + 1]})
    request = preliminary_request(claim, graph, tenant_id=graph.tenant_id)
    request["display_text"] = catalog.preliminary_pins(request, claim.source_refs)
    response = dict(
        claim_id=claim.claim_id,
        track="performance",
        safe_harbor_category=None,
        track_confidence=0.9,
        dimensions=dict(
            entity=dict(source_index=0, quote="네이버"), metric=None, reporting_period=None
        ),
    )
    restored = catalog.restore_preliminary(response, request)
    result = validate_preliminary(claim, graph, restored, tenant_id=graph.tenant_id)
    ref = result.context.dimensions["entity"]
    assert ref.quote == "네 이버" and ref.verification_state == "verified"
    assert (
        source.quote[ref.char_start - source.char_start : ref.char_end - source.char_start]
        == ref.quote
    )
    for bad in ["네이버を", "네 이버", "会社"]:
        altered = deepcopy(response)
        altered["dimensions"]["entity"]["quote"] = bad
        with pytest.raises(ValueError):
            catalog.restore_preliminary(altered, request)


@pytest.mark.parametrize(
    "case",
    [
        "allowed",
        "no_real_space",
        "wide_gap",
        "different_line",
        "nonconsecutive",
        "no_control",
        "threshold_equal",
    ],
)
def test_glyph_writer_requires_every_geometric_and_actual_space_condition(case):
    graph, sid = _extraction_context_graph(text="환 경 조직", with_neighbors=False)
    block = graph.blocks[0]
    catalog = fixture_catalog(graph, {})
    # Same pinned block; only independently mapped glyph boxes are inspected.
    words = [
        dict(index=i, text=text, bbox=box)
        for i, text, box in [
            (0, "환", [12, 72, 20, 82]),
            (1, "경", [21, 72, 28, 82]),
            (2, "조직", [34, 72, 48, 82]),
        ]
    ]
    matched = {
        w["index"]: dict(ink_bbox=w["bbox"], pdfium_char_indices=ids)
        for w, ids in zip(words, [[0], [1], [3, 4]], strict=True)
    }
    spaces = {2}
    if case == "no_real_space":
        spaces = set()
    if case == "wide_gap":
        words[1]["bbox"][0] = 23
    if case == "different_line":
        words[1]["bbox"][1:4:2] = [84, 94]
    if case == "nonconsecutive":
        matched[1]["pdfium_char_indices"] = [2]
    if case == "no_control":
        matched[2]["pdfium_char_indices"] = [2, 3]
    if case == "threshold_equal":
        words[2]["bbox"][0] = 29.5
    catalog._pages = {25: (words, matched, spaces, "a" * 64)}
    deleted, _ = catalog._build(block)
    assert deleted == ([1] if case == "allowed" else [])


def test_element_transport_displays_and_restores_without_trusting_packet_map(tmp_path, monkeypatch):
    from proofops_agent.upstage_tagging import QUOTE_V5_PROFILE

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, calls, request = configured(tmp_path, monkeypatch, QUOTE_V5_PROFILE)
    graph, claim, _ = corpus(claim_dimensions={"entity": "네 이버"})
    ref = asdict(claim.source_refs[0])
    catalog = fixture_catalog(graph, {ref["source_id"]: [ref["quote"].index("네 이버") + 1]})
    adapter._display_catalog = catalog
    data = dict(
        atomic_quote=ref["quote"],
        document_context={},
        claim_source_refs=[ref],
        allowed_elements=["G1", "P2"],
        evidence_candidates=[dict(source_refs=[ref])],
    )
    data["display_text"] = catalog.element_pins(data)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"] = data
    request["user_json"] = json.dumps(user)
    system, wire, refs, _, _ = adapter._wire_request(request)
    displayed = json.loads(wire)["untrusted_document_data"]
    assert "네이버" in displayed["atomic_quote"]
    assert "네이버" in displayed["evidence_catalog"]["e0"]["quote"]
    assert "네이버" in displayed["claim_source_refs"][0]["quote"]
    assert "네 이버" not in wire
    assert system.endswith(SYSTEM_SUFFIX) and not calls
    restored = adapter._restore_ref(dict(id="e0", quote="네이버"), refs)
    assert restored["quote"] == "네 이버"
    assert restored["bbox"] == ref["bbox"]
    forged = deepcopy(refs)
    forged["e0"]["_display"]["deleted_offsets"] = []
    with pytest.raises(ValueError, match="DISPLAY_MAP_MISMATCH"):
        adapter._restore_ref(dict(id="e0", quote="네이버"), forged)
    user["untrusted_document_data"]["display_text"]["sources"][0]["raw_boundaries"] = [0]
    request["user_json"] = json.dumps(user)
    with pytest.raises(ValueError, match="DISPLAY_PACKET_MISMATCH"):
        adapter._wire_request(request)


def test_preliminary_transport_sends_only_display_text_and_pins_map(tmp_path, monkeypatch):
    from tests.integration.test_upstage_preliminary_transport import configured

    adapter, _, calls, request, *_ = configured(tmp_path, monkeypatch)
    graph, claim, _ = corpus(claim_dimensions={"entity": "네 이버"})
    source = claim.source_refs[0]
    catalog = fixture_catalog(graph, {source.source_id: [source.quote.index("네 이버") + 1]})
    adapter._display_catalog = catalog
    envelope = preliminary_request(claim, graph, tenant_id=graph.tenant_id)
    envelope["display_text"] = catalog.preliminary_pins(envelope, claim.source_refs)
    request.update(
        claim_id=claim.claim_id,
        packet_sha256=canonical_hash(envelope),
        user_json=json.dumps(envelope),
    )
    system, wire, _, _, _ = adapter._wire_request(request)
    assert system.endswith(SYSTEM_SUFFIX) and not calls
    assert "네 이버" not in wire
    assert "네이버" in json.loads(wire)["untrusted_document_data"]["sources"][0]["text"]
    assert json.loads(wire)["display_map_sha256"] == canonical_hash(envelope["display_text"])
    envelope["display_text"]["sources"][0]["identity"]["page_num"] += 1
    request.update(packet_sha256=canonical_hash(envelope), user_json=json.dumps(envelope))
    with pytest.raises(ValueError, match="DISPLAY_PACKET_MISMATCH"):
        adapter._wire_request(request)


def test_unlocated_block_retains_raw_spacing():
    from dataclasses import replace

    graph, sid = _extraction_context_graph(text="환 경 조직", with_neighbors=False)
    block = graph.blocks[0]
    candidate = block.candidates[0]
    source = replace(candidate.source, native_bbox=None)
    candidate = replace(candidate, source=source)
    block = replace(block, candidates=(candidate,))
    graph = replace(graph, blocks=(block,))
    catalog = fixture_catalog(graph, {})
    catalog._cache.clear()
    pin = catalog.block_pin(sid)
    assert pin["text"] == block.raw_text and not pin["deleted_offsets"]


@pytest.mark.parametrize("resume", [False, True])
def test_saved_pilot_cannot_add_display_profile(tmp_path, monkeypatch, capsys, resume):
    import sys

    from evaluation import local_upstage_pilot as pilot

    state = tmp_path / "old"
    state.mkdir()
    manifest = state / "pilot.json"
    old = json.dumps({"source_path": "/tmp/example.pdf"})
    manifest.write_text(old)
    args = ["pilot", "--state", str(state), "--display-text-profile", PROFILE]
    if resume:
        args.append("--resume")
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        pilot.main()
    assert "profile" in capsys.readouterr().err
    assert manifest.read_text() == old and not (state / "settings.json").exists()


def test_new_run_pins_display_policy_and_old_run_omits_it(tmp_path):
    from uuid import uuid4

    from tests.integration.test_live_tagging_runtime_config import AUTH, _draft_pack, _live_service

    service, body, *_ = _live_service(tmp_path)
    body["rule_pack_id"] = _draft_pack(service, AUTH.tenant_id).rule_pack_id
    old = service.create(AUTH, body, str(uuid4()))
    old_snapshot = service.store.snapshot(AUTH.tenant_id, old["run_id"])
    assert "display_text_policy" not in old_snapshot
    service.display_text_policy = deepcopy(POLICY)
    new = service.create(AUTH, body, str(uuid4()))
    snapshot = service.store.snapshot(AUTH.tenant_id, new["run_id"])
    assert snapshot["display_text_policy"] == POLICY
    assert snapshot["input_hash"] == canonical_hash(
        {k: v for k, v in snapshot.items() if k != "input_hash"}
    )
    assert service.store.snapshot(AUTH.tenant_id, old["run_id"]) == old_snapshot


def test_display_pin_rejects_changed_document_location_and_offsets():
    graph, claim, _ = corpus(claim_dimensions={"entity": "네 이버"})
    ref = asdict(claim.source_refs[0])
    catalog = fixture_catalog(graph, {ref["source_id"]: [ref["quote"].index("네 이버") + 1]})
    for altered in [
        ref | {"document_version_id": "00000000-0000-4000-8000-000000000001"},
        ref | {"page_num": ref["page_num"] + 1},
        ref | {"bbox": [0, 0, 10, 10]},
        ref | {"char_start": ref["char_start"] + 1},
    ]:
        with pytest.raises(ValueError, match="DISPLAY_REF_MISMATCH"):
            catalog.pin(altered)
    with pytest.raises(ValueError, match="DISPLAY_SOURCE_MISMATCH"):
        GlyphDisplayCatalog(graph, b"foreign-original")


@pytest.mark.parametrize("attributes", [{}, {"display_catalog": None}])
def test_legacy_runtime_keeps_element_packet_without_display_catalog(attributes):
    from types import SimpleNamespace

    from proofops_worker.live_tagging import LiveTaggingRuntime

    packet = object()
    runtime = SimpleNamespace(**attributes)
    assert LiveTaggingRuntime.display_packet(runtime, packet) is packet
