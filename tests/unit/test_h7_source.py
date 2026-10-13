"""H7 bounded original-byte rendering and fail-closed source admission."""

import math
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("size", [(3543, 2362), (600, 800), (0.1, 200000)])
def test_render_scale_bounds_actual_rounded_bitmap(size):
    from proofops.adapters.local.source_h7 import render_scale

    scale = render_scale(*size, 16_000_000)
    assert 0 < scale <= 3
    assert math.ceil(size[0] * scale) * math.ceil(size[1] * scale) <= 16_000_000
    if size == (600, 800):
        assert scale == 3


@pytest.mark.parametrize("size", [(0, 800), (600, float("nan")), (-1, 800)])
def test_invalid_page_size_is_rejected(size):
    from proofops.adapters.local.source_h7 import render_scale

    with pytest.raises(ValueError):
        render_scale(*size, 16_000_000)


@pytest.fixture
def tolerant_reader(monkeypatch):
    from pdfplumber.utils.exceptions import PdfminerException
    from proofops.adapters.local import evidence_source_h7 as h7
    from proofops.adapters.local import source_h7

    original = h7._exec_private

    def failed(*a, **k):
        raise PdfminerException("Unexpected EOF")

    def private(*a, **k):
        module = original(*a, **k)
        module.pdfplumber = SimpleNamespace(open=failed)
        return module

    monkeypatch.setattr(h7, "_exec_private", private)
    monkeypatch.setattr(source_h7, "_ocr", lambda png: dict(text="ESG policy 10% achieved"))
    return h7


def test_tolerant_original_proof_replays_without_parser_mutation(tolerant_reader):
    from proofops.application.evidence.span_citations import verify_source_ref

    from tests.integration.test_claim_source_v3 import synthetic

    source, graph, ref = synthetic("ESG policy 10% achieved")
    receipt = tolerant_reader.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert receipt["original_reader"] == "PDFium-and-pypdf-original"
    record = receipt["records"][0]
    assert record["status"] == "verified"
    assert record["proof"]["rendered"]["source_sha256"] == graph.source_sha256
    scoped = tolerant_reader.replay_evidence_sources(
        receipt, graph, source, tenant_id=graph.tenant_id
    )
    assert scoped.blocks == graph.blocks
    assert (
        verify_source_ref(ref, scoped, tenant_id=graph.tenant_id).verification_state == "verified"
    )
    altered = deepcopy(receipt)
    altered["records"][0]["proof"]["rendered"]["scale"] = 1.5
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        tolerant_reader.replay_evidence_sources(altered, graph, source, tenant_id=graph.tenant_id)
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        tolerant_reader.replay_evidence_sources(
            receipt, graph, source + b"x", tenant_id=graph.tenant_id
        )
    with pytest.raises(ValueError):
        tolerant_reader.attest_evidence_sources(
            graph, source, tenant_id="22222222-2222-4222-8222-222222222222"
        )


@pytest.mark.parametrize(
    "parser,native",
    [
        ("ESG policy 11% achieved", "ESG policy 10% achieved"),
        ("ESG policy 1 0% achieved", "ESG policy 10% achieved"),
        ("ESG policy 10 % achieved", "ESG policy 10% achieved"),
        ("ESG policy 10% achieved OTHER ROW 999 tonnes", "ESG policy 10% achieved"),
        ("ESG policy", "ESG policy 10% achieved"),
    ],
)
def test_tolerant_original_never_admits_changed_or_partial_text(tolerant_reader, parser, native):
    from tests.integration.test_claim_source_v3 import synthetic

    source, graph, _ = synthetic(parser, native)
    receipt = tolerant_reader.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert not any(r["status"] == "verified" for r in receipt["records"])


@pytest.mark.parametrize("quality", ["unreadable", "conflicted", "unlocated"])
def test_tolerant_quality_holds_remain_holds(tolerant_reader, quality):
    from tests.integration.test_claim_source_v3 import synthetic

    source, graph, _ = synthetic("ESG policy 10% achieved")
    graph = replace(graph, blocks=(replace(graph.blocks[0], quality=quality),))
    receipt = tolerant_reader.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "unresolved"


def test_tolerant_widget_and_clipped_glyph_remain_unresolved(tolerant_reader):
    from pypdf.generic import DictionaryObject, NameObject, RectangleObject

    from tests.integration.test_claim_source_v3 import synthetic

    annotation = DictionaryObject(
        {
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): RectangleObject([70, 705, 400, 735]),
        }
    )
    source, graph, _ = synthetic("ESG policy 10% achieved", annotation=annotation)
    result = tolerant_reader.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert result["records"][0]["reason"] == "interactive_visibility_requires_review"
    source, graph, _ = synthetic("ESG policy 10% achieved")
    from proofops.application.ingest.graph_fusion import fuse_candidates

    batch = graph.candidates[0]
    candidate = batch.blocks[0]
    clipped = replace(candidate, source=replace(candidate.source, native_bbox=(80, 705, 400, 735)))
    graph = fuse_candidates((replace(batch, blocks=(clipped,)),), tenant_id=graph.tenant_id)
    result = tolerant_reader.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert result["records"][0]["status"] == "unresolved"


def test_tolerant_metadata_mismatch_is_a_hold(tolerant_reader, monkeypatch):
    from proofops.adapters.local import source_h7

    from tests.integration.test_claim_source_v3 import synthetic

    def mismatch(*a):
        raise ValueError("H7_PAGE_MAPPING_MISMATCH")

    monkeypatch.setattr(source_h7, "OriginalPage", mismatch)
    source, graph, _ = synthetic("ESG policy 10% achieved")
    result = tolerant_reader.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert result["records"][0]["status"] == "unresolved"
    assert result["records"][0]["error"] == "H7_PAGE_MAPPING_MISMATCH"


def test_pixel_transform_is_exact_and_bounded(monkeypatch):
    from proofops.adapters.local import source_h7

    from tests.integration.test_claim_source_v3 import synthetic

    source, _, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(source_h7, "_ocr", lambda png: dict(text="independent pixels"))
    raster = source_h7.RasterReader(source, max_pixels=1_000_000)
    box = (70.125, 65.25, 400.75, 95.875)
    try:
        result = raster.read(
            SimpleNamespace(page_number=1, width=600, height=800), box, padding_px=6
        )
        assert result["status"] == "read"
        assert result["scale"] < 3
        assert math.prod(result["page_pixels"]) <= 1_000_000
        actual = result["pixel_to_pdf_bbox"]
        assert actual[0] <= box[0] < actual[0] + 1 / result["scale"]
        assert actual[1] <= box[1] < actual[1] + 1 / result["scale"]
        assert actual[2] >= box[2] > actual[2] - 1 / result["scale"]
        assert actual[3] >= box[3] > actual[3] - 1 / result["scale"]
        a, _, _, d, e, f = result["crop_to_pdf"]
        assert (6 * a + e, 6 * d + f) == pytest.approx(actual[:2])
        assert (
            raster.read(SimpleNamespace(page_number=1, width=599, height=800), box)["status"]
            == "unresolved"
        )
    finally:
        raster.close()


def test_h7_is_explicit_and_h6_hash_is_unchanged():
    from proofops.adapters.local import evidence_source_h7, upstage_ocr_profile_v15
    from proofops.adapters.local.claim_source_policies import claim_source_reader
    from proofops.adapters.local.evidence_source_policies import evidence_source_reader
    from proofops.application.analysis_profile import (
        FINALS_H6_POLICY,
        FINALS_H7_POLICY,
        V2_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        canonical_hash(FINALS_H6_POLICY)
        == "6dbc7c31f75f28e61656f7e4db0e5479f70d83f9506b38e9e473c677ff6e7dd3"
    )
    pin = canonical_hash(FINALS_H7_POLICY)
    assert pin != canonical_hash(FINALS_H6_POLICY)
    assert policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_H7_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_H7_POLICY
    assert policy_for(V2_PROFILE) == V2_POLICY
    assert (
        claim_source_reader(upstage_ocr_profile_v15.claim_source_policy())
        == upstage_ocr_profile_v15
    )
    assert evidence_source_reader(evidence_source_h7.policy()) == evidence_source_h7


def test_h7_claim_subset_uses_all_ref_guards(tolerant_reader, monkeypatch, tmp_path):
    from proofops.adapters.local import upstage_ocr_profile_v14 as h6
    from proofops.adapters.local import upstage_ocr_profile_v15 as h7

    from tests.integration.test_claim_source_v3 import synthetic
    from tests.integration.test_upstage_ocr_page import store

    source, graph, whole = synthetic("ESG policy 10% achieved")
    ref = replace(whole, char_start=11, char_end=14, quote="10%")
    wrong = replace(ref, quote="11%")

    def baseline(self, graph, source, refs, *, tenant_id):
        from dataclasses import asdict

        return dict(
            records=[
                dict(ref=asdict(r), status="unresolved", reason="native_text_unreadable")
                for r in refs
            ],
            pb1_cell_proofs=[],
        )

    monkeypatch.setattr(h6.Reader, "attest_claim_spans", baseline)
    reader = h7.Reader(
        store(tmp_path, lambda *a: pytest.fail("paid OCR called")), run_id="h7-subset"
    )
    receipt = reader.attest_claim_spans(graph, source, (ref, wrong), tenant_id=graph.tenant_id)
    assert [r["status"] for r in receipt["records"]] == ["verified", "unresolved"]
    reader.recompute_claim_receipt(receipt, graph, source, (ref, wrong), tenant_id=graph.tenant_id)
    altered = deepcopy(receipt)
    altered["records"][1]["status"] = "verified"
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(
            altered, graph, source, (ref, wrong), tenant_id=graph.tenant_id
        )


def test_h7_normal_native_and_claim_replay_cannot_buy_ocr(monkeypatch, tmp_path):
    from proofops.adapters.local import source_verification
    from proofops.adapters.local import upstage_ocr_profile_v15 as h7
    from proofops.application.analysis_profile import (
        FINALS_H7_POLICY,
        V2_PROFILE,
        apply_pilot_profile,
    )
    from proofops.domain.provenance import canonical_hash

    from tests.integration.test_claim_source_v3 import synthetic
    from tests.integration.test_upstage_ocr_page import store

    args = SimpleNamespace(
        analysis_profile=V2_PROFILE, analysis_policy_sha256=canonical_hash(FINALS_H7_POLICY)
    )
    apply_pilot_profile(args)
    assert args.claim_source_profile == h7.PROFILE
    assert args.parser_local_resource_policy == "selected-pdf-h6-v1"
    monkeypatch.setattr(
        source_verification,
        "_rendered_text",
        lambda *a, **k: dict(
            status="read", text="ESG policy 10% achieved", pixel_bbox=[210, 195, 1200, 285], scale=3
        ),
    )
    source, graph, ref = synthetic("ESG policy 10% achieved")
    reader = h7.Reader(
        store(tmp_path, lambda *a: pytest.fail("H7 bought normal-page OCR")), run_id="h7-normal"
    )
    native = reader.attest_native_sources(graph, source, tenant_id=graph.tenant_id)
    assert native["records"][0]["status"] == "verified"
    assert (
        reader.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id)
        .blocks[0]
        .quality
        == "verified"
    )
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)


@pytest.mark.parametrize("declaration", ["ocg_null", "form_null", "xfa_null"])
def test_raw_catalog_visibility_declarations_are_never_bypassed(monkeypatch, declaration):
    import io
    from hashlib import sha256

    from proofops.adapters.local import evidence_source_h7 as h7
    from proofops.adapters.local import source_verification
    from proofops.application.ingest.graph_fusion import fuse_candidates
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NullObject

    from tests.integration.test_claim_source_v3 import synthetic

    source, graph, _ = synthetic("ESG policy 10% achieved")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    if declaration == "ocg_null":
        writer._root_object[NameObject("/OCProperties")] = NullObject()
    elif declaration == "form_null":
        writer._root_object[NameObject("/AcroForm")] = NullObject()
    else:
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
            {NameObject("/Fields"): ArrayObject(), NameObject("/XFA"): NullObject()}
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    source = buffer.getvalue()
    batch = replace(graph.candidates[0], source_sha256=sha256(source).hexdigest())
    graph = fuse_candidates((batch,), tenant_id=graph.tenant_id)
    monkeypatch.setattr(
        source_verification,
        "_rendered_text",
        lambda *a, **k: dict(
            status="read",
            text="ESG policy 10% achieved",
            scale=3,
            pixel_bbox=[210, 195, 1200, 285],
            image_sha256="a" * 64,
        ),
    )
    receipt = h7.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "unresolved"
