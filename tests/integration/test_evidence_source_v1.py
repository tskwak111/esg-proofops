"""EV1: pinned MP1 sources and hostile source-admission cases, no model calls."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_claim_source_v3 import synthetic
from tests.integration.test_native_table_admission import fixture, ocr


def reader():
    from proofops.adapters.local import evidence_source_verification_v1

    return evidence_source_verification_v1


def real_inputs(company):
    from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates

    data = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/evidence_source_v1" / (company + ".json")
        ).read_text()
    )
    root = Path("/Users/ss020/Dev/ESG_ProofOps")
    source = (root / data["source_path"]).read_bytes()
    assert sha256(source).hexdigest() == data["source_sha256"]
    batches = candidates_from_snapshot(data["batches"])
    graph = fuse_candidates(
        batches,
        tenant_id=batches[0].tenant_id,
        fusion_version=data["fusion_version"],
        mixed_parser=True,
    )
    return source, graph, data["ref"]


def attest(source, graph):
    return reader().attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)


@pytest.mark.parametrize("company", ["samsung", "kepco"])
def test_real_mp1_prose_recovers_without_promoting_table_or_rewriting_parser(company):
    from proofops.adapters.local.source_verification import attest_native_sources
    from proofops.application.evidence.span_citations import verify_source_ref
    from proofops.domain.values import SourceRef

    source, graph, raw = real_inputs(company)
    before = attest_native_sources(graph, source, tenant_id=graph.tenant_id)
    assert (
        next(r for r in before["records"] if r["source_id"] == raw["source_id"])["status"]
        == "unresolved"
    )
    receipt = attest(source, graph)
    result = next(r for r in receipt["records"] if r["source_id"] == raw["source_id"])
    assert result["status"] == "verified"
    scoped = reader().replay_evidence_sources(receipt, graph, source, tenant_id=graph.tenant_id)
    assert (
        verify_source_ref(SourceRef(**raw), scoped, tenant_id=graph.tenant_id).verification_state
        == "verified"
    )
    assert scoped.blocks == graph.blocks  # prose is exact-span approval only
    assert result["ref"] == asdict(SourceRef(**raw))
    assert result["proof"]["source_sha256"] == graph.source_sha256
    if company == "samsung":
        flat = next(b for b in graph.blocks if b.source_id.startswith("05a5a8e1"))
        assert (
            next(r for r in receipt["records"] if r["source_id"] == flat.source_id)["status"]
            == "unresolved"
        )
        numeric_spacing = next(
            r for r in receipt["records"] if r["source_id"].startswith("2fd5d6d7")
        )
        assert numeric_spacing["status"] == "unresolved"  # render lost space after numeric marker
        table_prose = next(r for r in receipt["records"] if r["source_id"].startswith("5686c817"))
        assert table_prose["status"] == "unresolved"
        tcfd_header = next(r for r in receipt["records"] if r["source_id"].startswith("3d451042"))
        assert tcfd_header["status"] == "unresolved"
        assert tcfd_header["reason"] == "detected_table_requires_ownership"


@pytest.mark.parametrize(
    "parser,native",
    [
        ("ESX policy 10% achieved", "ESG policy 10% achieved"),
        ("ESG policy 1 0% achieved", "ESG policy 10% achieved"),
        ("ESG policy 10 % achieved", "ESG policy 10% achieved"),
        ("ESG policy 10 M J achieved", "ESG policy 10 MJ achieved"),
        ("ESG policy 10% achieved OTHER ROW 999 tonnes", "ESG policy 10% achieved"),
    ],
)
def test_forged_text_numbers_units_and_row_splicing_rejected(parser, native):
    source, graph, _ = synthetic(parser, native)
    assert attest(source, graph)["records"][0]["status"] == "unresolved"


def test_exact_span_replay_tenant_source_policy_and_receipt_tamper(monkeypatch):
    v = reader()
    monkeypatch.setattr(v, "_rendered_text", ocr)
    source, graph, ref = synthetic("ESG policy 10% achieved")
    receipt = attest(source, graph)
    assert receipt["records"][0]["status"] == "verified"
    scoped = v.replay_evidence_sources(receipt, graph, source, tenant_id=TENANT)
    assert scoped.blocks == graph.blocks
    assert scoped.verified_spans[0].char_end == ref.char_end
    for modified in [dict(receipt, policy={}), dict(receipt, records=[])]:
        with pytest.raises(ValueError):
            v.replay_evidence_sources(modified, graph, source, tenant_id=TENANT)
    with pytest.raises(ValueError):
        v.replay_evidence_sources(receipt, graph, source + b"x", tenant_id=TENANT)
    with pytest.raises(ValueError):
        attest(source, replace(graph, tenant_id="00000000-0000-4000-8000-000000000999"))


def test_unreadable_conflict_and_unlocated_never_promoted(monkeypatch):
    v = reader()
    monkeypatch.setattr(v, "_rendered_text", ocr)
    source, graph, _ = synthetic("ESG policy 10% achieved")
    for quality in ["unreadable", "conflicted", "unlocated"]:
        changed = replace(graph, blocks=(replace(graph.blocks[0], quality=quality),))
        receipt = attest(source, changed)
        assert receipt["records"][0]["status"] == "unresolved"
        assert (
            v.replay_evidence_sources(receipt, changed, source, tenant_id=TENANT).blocks
            == changed.blocks
        )


def test_verified_complete_table_requires_all_cells_headers_and_order(monkeypatch):
    v = reader()
    monkeypatch.setattr(v, "_rendered_text", ocr)
    source, graph = fixture()
    receipt = attest(source, graph)
    checked = v.replay_evidence_sources(receipt, graph, source, tenant_id=TENANT)
    assert all(b.quality == "verified" for b in checked.blocks)
    assert checked.issues[0].state == "resolved"
    assert graph.issues[0].state == "open"
    from proofops.application.ingest.graph_fusion import fuse_candidates

    batch = graph.candidates[0]
    for field, value in [("column_number", 0), ("row_number", 9), ("row_span", 2)]:
        cells = tuple(
            replace(b, **{field: value}) if b.source.source_native_id == "C12" else b
            for b in batch.blocks
        )
        forged = fuse_candidates((replace(batch, blocks=cells),), tenant_id=TENANT)
        assert not any(r["status"] == "verified" for r in attest(source, forged)["records"])
    monkeypatch.setattr(v, "_rendered_text", lambda *a, **k: dict(status="read", text="FORGED"))
    assert not any(r["status"] == "verified" for r in attest(source, graph)["records"])


def test_sparse_table_with_missing_year_cell_cannot_be_promoted(monkeypatch):
    from proofops.application.ingest.graph_fusion import fuse_candidates

    v = reader()
    monkeypatch.setattr(v, "_rendered_text", ocr)
    source, graph = fixture()
    batch = graph.candidates[0]
    altered = []
    for b in batch.blocks:
        sid = b.source.source_native_id
        if sid == "C12":
            continue
        text = {"T": "Year\t2024\t2025\nMWh\t25", "R1": "MWh\t25"}.get(sid)
        altered.append(
            replace(b, source=replace(b.source, raw_text=text, char_end=len(text)))
            if text is not None
            else b
        )
    edges = tuple(e for e in batch.edges if e.source_native_id != "C12")
    sparse = fuse_candidates(
        (replace(batch, blocks=tuple(altered), edges=edges),), tenant_id=TENANT
    )
    assert not any(r["status"] == "verified" for r in attest(source, sparse)["records"])


def test_paragraph_cannot_admit_partial_crop_or_extra_hidden_native_text(monkeypatch):
    v = reader()
    source, graph, _ = synthetic("ESG policy", "ESG policy 10% achieved")
    monkeypatch.setattr(v, "_rendered_text", lambda *a, **k: dict(status="read", text="ESG policy"))
    assert attest(source, graph)["records"][0]["status"] == "unresolved"


def test_spaced_alphabetic_parser_preserves_raw_ref(monkeypatch):
    v = reader()
    monkeypatch.setattr(v, "_rendered_text", ocr)
    source, graph, ref = synthetic("E SG policy 10% achieved")
    r = attest(source, graph)["records"][0]
    assert r["status"] == "verified"
    assert r["ref"] == asdict(ref)
    assert r["proof"]["canonical_quote"] == "ESG policy 10% achieved"


@pytest.mark.parametrize(
    "subtype,appearance,overlap,expected",
    [
        ("/Link", False, True, "verified"),
        ("/Link", True, True, "unresolved"),
        ("/Widget", False, True, "unresolved"),
        ("/Widget", True, True, "unresolved"),
        ("/Widget", True, False, "verified"),
    ],
)
def test_glyph_local_annotations_preserve_visibility_guard(
    monkeypatch, subtype, appearance, overlap, expected
):
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        RectangleObject,
    )

    annotation = DictionaryObject(
        {
            NameObject("/Subtype"): NameObject(subtype),
            NameObject("/Rect"): RectangleObject(
                (80, 713, 95, 730) if overlap else (70, 704, 95, 708)
            ),
        }
    )
    if appearance:
        stream = DecodedStreamObject()
        stream.set_data(b"0 0 0 rg 0 0 20 20 re f")
        stream[NameObject("/BBox")] = RectangleObject((0, 0, 20, 20))
        stream[NameObject("/Subtype")] = NameObject("/Form")
        annotation[NameObject("/AP")] = DictionaryObject({NameObject("/N"): stream})
    source, graph, _ = synthetic("ESG policy 10% achieved", annotation=annotation)
    monkeypatch.setattr(reader(), "_rendered_text", ocr)
    assert attest(source, graph)["records"][0]["status"] == expected


def test_hidden_optional_content_and_clipped_glyphs_stay_unresolved(monkeypatch):
    import io

    from proofops.application.ingest.graph_fusion import fuse_candidates
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DictionaryObject, NameObject

    source, graph, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(reader(), "_rendered_text", ocr)
    batch = graph.candidates[0]
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.root_object[NameObject("/OCProperties")] = DictionaryObject()
    stream = io.BytesIO()
    writer.write(stream)
    hidden = stream.getvalue()
    changed = fuse_candidates(
        (replace(batch, source_sha256=sha256(hidden).hexdigest()),), tenant_id=TENANT
    )
    assert attest(hidden, changed)["records"][0]["status"] == "unresolved"
    clipped = replace(
        batch.blocks[0], source=replace(batch.blocks[0].source, native_bbox=(80, 705, 400, 735))
    )
    changed = fuse_candidates((replace(batch, blocks=(clipped,)),), tenant_id=TENANT)
    assert attest(source, changed)["records"][0]["status"] == "unresolved"


def test_wrong_physical_page_or_original_hash_is_not_a_recovery(monkeypatch):
    from proofops.application.ingest.graph_fusion import fuse_candidates

    source, graph, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(reader(), "_rendered_text", ocr)
    batch = graph.candidates[0]
    changed = replace(batch.blocks[0], source=replace(batch.blocks[0].source, physical_page=2))
    wrong_page = fuse_candidates((replace(batch, blocks=(changed,)),), tenant_id=TENANT)
    with pytest.raises(ValueError):
        attest(source, wrong_page)


def test_cross_column_paragraph_needs_explicit_table_even_when_ocr_matches(monkeypatch):
    from proofops.application.ingest.graph_fusion import fuse_candidates

    from tests.acceptance.test_parsing import candidate
    from tests.integration.test_claim_source_verification import geometry_pdf

    source = geometry_pdf([(72, 720, "Year"), (250, 720, "2024")])
    batch = replace(
        candidate("ev1-flat", [("P", "paragraph", "Year 2024", (70, 705, 350, 735), ())]),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    monkeypatch.setattr(
        reader(), "_rendered_text", lambda *a, **k: dict(status="read", text="Year 2024")
    )
    assert attest(source, graph)["records"][0]["status"] == "unresolved"
