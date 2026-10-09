"""MP1: real ODL routing, immutable provenance and conservative source admission."""

import io
import json
from dataclasses import asdict, replace
from hashlib import sha256
from uuid import uuid4

import pytest
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def document():
    writer = PdfWriter()
    for text in (
        "Energy use fell 20 percent in 2025.",
        "Reporting boundary includes all domestic factories. "
        "Methods and reporting period are stated in this report.",
        "",
    ):
        page = writer.add_blank_page(width=400, height=200)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        if len(text) > 60:
            text = text.replace("factories. ", "factories.) Tj 0 -16 Td (")
        content.set_data(f"BT /F1 12 Tf 40 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)
    stream = io.BytesIO()
    writer.write(stream)
    pdf = stream.getvalue()
    return SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(pdf).hexdigest(), "v1", pdf
    )


class Probe:
    def __init__(self, *, reject_ocr=False):
        self.calls = []
        self.reject_ocr = reject_ocr

    def parse_async(self, content, *, request_id, mode):
        pages = PdfReader(io.BytesIO(content)).pages
        texts = [page.extract_text().strip() for page in pages]
        self.calls.append((len(pages), mode))
        if self.reject_ocr and len(pages) > 1:
            raise ValueError("BUDGET_EXHAUSTED")
        batches = [
            {
                "model": "document-parse-260128",
                "usage": {"pages": len(pages), mode: list(range(1, len(pages) + 1))},
                "elements": [
                    dict(
                        page=i,
                        category="paragraph",
                        coordinates=[
                            {"x": 0.05, "y": 0.4},
                            {"x": 0.95, "y": 0.4},
                            {"x": 0.95, "y": 0.6},
                            {"x": 0.05, "y": 0.6},
                        ],
                        content={"text": text},
                    )
                    for i, text in enumerate(texts, 1)
                    if text
                ],
            }
        ]
        return dict(raw_batches=batches, response_sha256=canonical_hash(batches))


def profile(**kwargs):
    return ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2, 3),
        java_executable="/opt/homebrew/opt/openjdk@21/bin/java",
        timeout_seconds=120,
        table_auxiliary=False,
        parser_mode="mixed-v1",
        claim_physical_pages=(1,),
        **kwargs,
    )


@pytest.fixture
def mixed(tmp_path):
    source, config, probe = document(), profile(), Probe()
    parser = OpenDataLoaderParser(tmp_path, upstage_probe=probe)
    graph = parser.parse(source, config, tenant_id=source.tenant_id)
    directory = tmp_path / source.tenant_id / source.document_version_id / config.parse_manifest_id
    return source, config, probe, parser, graph, directory


def test_routes_only_claim_pages_and_retains_odl_evidence(mixed):
    source, config, probe, parser, graph, directory = mixed
    assert probe.calls == [(1, "standard")]
    assert {b.page_num for b in graph.blocks} == {1, 2}
    names = {b.parser_run_id: b.parser_name for b in graph.candidates}
    for block in graph.blocks:
        expected = "opendataloader" if block.page_num == 2 else "upstage_async_standard"
        assert {names[c.source.parser_run_id] for c in block.candidates} == {expected}
        assert {p["parser_name"] for p in block.to_dict()["provenance"]} == {expected}
    manifest = json.loads((directory / "manifest.json").read_bytes())
    assert manifest["page_parser_provenance"][1]["parser_names"] == ["opendataloader"]
    assert manifest["page_parser_provenance"][2]["state"] == "unreadable"
    assert any(i.page_num == 3 and i.state == "unreadable" for i in graph.issues)
    assert (
        parser.load_verified(source, config, tenant_id=source.tenant_id).to_dict()
        == graph.to_dict()
    )


def test_odl_glyph_source_check_and_unverified_admission(mixed):
    from proofops.adapters.local.source_verification import (
        attest_native_sources,
        replay_native_sources,
    )
    from proofops.application.evidence.citations import verify_source_ref

    source, _, _, _, graph, _ = mixed
    receipt = attest_native_sources(
        graph, source.content, tenant_id=source.tenant_id, geometry_mode="glyph"
    )
    restored = replay_native_sources(receipt, graph, source.content, tenant_id=source.tenant_id)
    evidence = next(b for b in restored.blocks if b.page_num == 2)
    record = next(r for r in receipt["records"] if r["source_id"] == evidence.source_id)
    assert record["status"] in {"verified", "unresolved"}
    if evidence.kind != "paragraph":
        assert record["status"] == "unresolved"
        assert record["reason"] == "relationship_validation_required"
    checked = verify_source_ref(evidence.source_ref(), restored, tenant_id=source.tenant_id)
    assert (checked.verification_state == "verified") == (record["status"] == "verified")
    if record["status"] != "verified":
        assert evidence.quality != "verified"  # original confirmation required, never present
    assert (
        replay_native_sources(receipt, graph, source.content, tenant_id=source.tenant_id)
        == restored
    )


def test_bounded_ocr_fallback_and_exhausted_budget(tmp_path):
    source = document()
    config = profile(mixed_ocr_max_pages=1)
    probe = Probe(reject_ocr=True)
    parser = OpenDataLoaderParser(tmp_path, upstage_probe=probe)
    graph = parser.parse(source, config, tenant_id=source.tenant_id)
    assert probe.calls == [(2, "standard"), (1, "standard")]
    assert any(i.page_num == 3 and i.state == "unreadable" for i in graph.issues)
    assert (
        parser.load_verified(source, config, tenant_id=source.tenant_id).to_dict()
        == graph.to_dict()
    )


def test_rejects_changed_routing_and_invalid_claim_selection(mixed):
    source, config, _, parser, _, directory = mixed
    with pytest.raises(ValueError):
        replace(config, claim_physical_pages=(4,))
    with pytest.raises(ParseFailure):
        parser.load_verified(
            source, replace(config, claim_physical_pages=(2,)), tenant_id=source.tenant_id
        )
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["page_parser_provenance"][1]["parser_names"] = ["upstage_async_standard"]
    path.chmod(0o600)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ParseFailure):
        parser.load_verified(source, config, tenant_id=source.tenant_id)


@pytest.mark.parametrize("mode", ["local", "upstage"])
def test_single_mode_snapshots_remain_byte_identical(mode):
    config = ParserProfile(str(uuid4()), parser_mode=mode)
    legacy = asdict(config)
    legacy.pop("claim_physical_pages", None)
    legacy.pop("mixed_ocr_max_pages", None)
    for field in ("table_text_y_tolerance", "table_source_policy_sha256", "table_structure_repair"):
        legacy.pop(field)
    for field in ("vision_parse", "upstage_glyph_boxes", "upstage_region_words"):
        legacy.pop(field)
    if mode == "local":
        legacy.pop("parser_mode")
    assert canonical_hash(config.invocation_snapshot()) == canonical_hash(legacy)
    assert json.dumps(config.invocation_snapshot(), sort_keys=True) == json.dumps(
        legacy, sort_keys=True
    )


def test_mixed_parser_requires_raster_consent_before_dispatch(tmp_path):
    from tests.integration.test_run_lifecycle import client, setup

    service, body = setup(tmp_path)
    config = profile()
    service.parser_profile = config.config_snapshot()
    service.parser_profile_hash = config.config_hash()
    http, _ = client(service)
    response = http.post("/v1/runs", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIG_GATE_BLOCKED"


def test_mixed_provenance_does_not_suppress_local_parser_conflicts():
    from proofops.adapters.parsing.mixed_routing import annotate
    from proofops.application.ingest.graph_fusion import fuse_candidates

    from tests.acceptance.test_parsing import TENANT, candidate

    a = candidate("opendataloader", [("A", "table_cell", "1234", (10, 10, 100, 30), ())])
    b = candidate("pdfplumber", [("B", "table_cell", "1284", (10, 10, 100, 30), ())])
    graph = fuse_candidates(
        (annotate(a), annotate(b)), tenant_id=TENANT, fusion_version=5, mixed_parser=True
    )
    assert len(graph.blocks) == 1
    assert graph.blocks[0].quality == "conflicted"
    assert graph.blocks[0].winner is None


def test_paid_ocr_fallback_preserves_unlocated_candidate(tmp_path):
    class OCRProbe(Probe):
        def parse_async(self, content, *, request_id, mode):
            result = super().parse_async(content, request_id=request_id, mode=mode)
            pages = PdfReader(io.BytesIO(content)).pages
            for i, page in enumerate(pages, 1):
                if not page.extract_text().strip():
                    result["raw_batches"][0]["elements"].append(
                        dict(
                            page=i,
                            category="paragraph",
                            content={"text": "OCR-only reporting boundary"},
                            coordinates=[
                                {"x": 0.1, "y": 0.1},
                                {"x": 0.9, "y": 0.1},
                                {"x": 0.9, "y": 0.9},
                                {"x": 0.1, "y": 0.9},
                            ],
                        )
                    )
            result["response_sha256"] = canonical_hash(result["raw_batches"])
            return result

    source, config, probe = document(), profile(mixed_ocr_max_pages=1), OCRProbe()
    parser = OpenDataLoaderParser(tmp_path, upstage_probe=probe)
    graph = parser.parse(source, config, tenant_id=source.tenant_id)
    evidence = [b for b in graph.blocks if b.page_num == 3]
    assert evidence and all(b.quality == "unlocated" for b in evidence)
    assert probe.calls[0] == (2, "standard")
    loaded = parser.load_verified(source, config, tenant_id=source.tenant_id)
    assert loaded == graph
    assert all(b.quality != "verified" for b in evidence)
