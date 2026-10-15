"""FXF bounded original page pixels, exact OCR and immutable receipt composition."""

import io
from hashlib import sha256

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from tests.integration.test_claim_source_v4_visibility import CASES, changed_pdf


def test_large_page_is_bounded_and_original_bytes_are_bound():
    from proofops.adapters.local.source_fxf import render_page

    source, _ = changed_pdf()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    for name in ("mediabox", "cropbox"):
        setattr(writer.pages[0], name, RectangleObject([0, 0, 3543, 2362]))
    output = io.BytesIO()
    writer.write(output)
    source = output.getvalue()
    image = render_page(source, 1)
    m = image["manifest"]
    assert m["source_sha256"] == sha256(source).hexdigest()
    assert m["png_sha256"] == sha256(image["png"]).hexdigest()
    assert m["pixel_size"][0] * m["pixel_size"][1] <= 16_000_000
    assert 1 < m["scale"] < 3
    assert m["draw_annotations"] is True
    assert render_page(source, 1) == image
    with pytest.raises(ValueError):
        render_page(source, 2)


def test_glyph_confirmation_rejects_changed_text_spacing_location_and_uncertainty():
    from copy import deepcopy

    from proofops.adapters.local.claim_source_fxf import _glyph_match

    text = "emissions 1234 tCO2e in 2025"
    # One synthetic OCR polygon; each exact native character lies within it.
    glyphs = [dict(char=c, bbox=[10, 10, 12, 12]) for c in text if not c.isspace()]
    proof = dict(canonical_quote=text, glyphs=glyphs)
    reading = dict(
        status="read",
        text=text,
        words=[dict(text=text, confidence=1.0, pdf_polygon=[[0, 0], [30, 0], [30, 30], [0, 30]])],
    )
    assert _glyph_match(reading, proof)
    for changed in (
        "emissions 1235 tCO2e in 2025",
        "emissions 1 234 tCO2e in 2025",
        "emissions 1234 tCO2e in 2026",
        "emissions 1234 tCO₂e in 2025",
    ):
        bad = deepcopy(reading)
        bad["text"] = changed
        bad["words"][0]["text"] = changed
        assert not _glyph_match(bad, proof)
    for change in ("location", "confidence", "duplicate"):
        bad = deepcopy(reading)
        if change == "location":
            bad["words"][0]["pdf_polygon"] = [[50, 50], [80, 50], [80, 80], [50, 80]]
        if change == "confidence":
            bad["words"][0]["confidence"] = 0.97
        if change == "duplicate":
            bad["text"] += " " + text
        assert not _glyph_match(bad, proof)


class MissingStore:
    def fetch(self, *args, **kwargs):
        raise ValueError("OCR_REPLAY_PAGE_MISSING")

    def validate(self, *args, **kwargs):
        raise AssertionError("no trusted collection exists")


def test_missing_pixels_remain_unresolved_and_cold_replay_never_fetches(monkeypatch):
    from copy import deepcopy

    from proofops.adapters.local import claim_source_fxf as reader

    from tests.acceptance.test_parsing import TENANT

    source, graph = changed_pdf(b"0 0 m 600 800 l 0 800 l h W n")
    refs = (graph.blocks[0].source_ref(),)
    store = MissingStore()
    receipt = reader.attest_claim_spans(
        graph, source, refs, tenant_id=TENANT, run_id="test", store=store
    )
    assert receipt["records"][0]["status"] == "unresolved"
    assert receipt["page_reads"][0]["failure"] == "OCR_REPLAY_PAGE_MISSING"
    monkeypatch.setattr(
        store, "fetch", lambda *a, **k: pytest.fail("cold replay called acquisition")
    )
    assert (
        reader.attest_claim_spans(
            graph,
            source,
            refs,
            tenant_id=TENANT,
            run_id="test",
            store=store,
            saved_pages=receipt["page_reads"],
        )
        == receipt
    )
    bad = deepcopy(receipt["page_reads"])
    bad[0]["manifest"]["png_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="REPLAY_PAGE_MISMATCH"):
        reader.attest_claim_spans(
            graph, source, refs, tenant_id=TENANT, run_id="test", store=store, saved_pages=bad
        )
    bad = deepcopy(receipt["page_reads"])
    bad[0]["collection"] = {"request_id": "forged"}
    with pytest.raises(AssertionError, match="no trusted collection"):
        reader.attest_claim_spans(
            graph, source, refs, tenant_id=TENANT, run_id="test", store=store, saved_pages=bad
        )
    for source2, tenant in ((source + b"x", TENANT), (source, "wrong-tenant")):
        with pytest.raises(ValueError):
            reader.attest_claim_spans(
                graph, source2, refs, tenant_id=tenant, run_id="test", store=store
            )


def test_profile_dispatch_and_composed_cold_replay(monkeypatch):
    from copy import deepcopy

    from proofops.adapters.local import upstage_ocr_profile_fxe as old
    from proofops.adapters.local import upstage_ocr_profile_fxf as new
    from proofops.adapters.local.claim_source_policies import page_ocr_profile, publication_reader
    from proofops.application.analysis_profile import (
        FINALS_I23_POLICY,
        FXE_POLICY,
        FXF_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    from tests.acceptance.test_parsing import TENANT

    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I23_POLICY))["integration_profile"]
        == "finals-20261015-v23"
    )
    assert (
        canonical_hash(FXE_POLICY)
        == "7e74fff1c7f7795512c93321e21cee387c00e2f829d57bd8e56b26b07cadbcd0"
    )
    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(FXF_POLICY)) == FXF_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(FXF_POLICY)) == FXF_POLICY
    assert page_ocr_profile(new.PROFILE, policy=new.claim_source_policy()) is new
    assert publication_reader(new.claim_source_policy()) is new
    assert publication_reader(old.claim_source_policy()) is old
    assert new.native_policy() == old.native_policy()
    assert new.table_span_policy() == old.table_span_policy()
    monkeypatch.setattr(new.PageOCRStore, "from_env", lambda: MissingStore())
    source, graph = changed_pdf()
    refs = (graph.blocks[0].source_ref(),)
    reader = new.for_run("55555555-5555-4555-8555-555555555555")
    receipt = reader.attest_claim_spans(graph, source, refs, tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "verified"
    assert reader.recompute_claim_receipt(receipt, graph, source, refs, tenant_id=TENANT) == receipt
    for key in ("records", "policy", "run_id", "previous_receipt"):
        bad = deepcopy(receipt)
        if key == "records":
            bad[key][0]["ref"]["quote"] = "emissions 9999 tCO2e in 2025"
        if key == "policy":
            bad[key]["verifier_sha256"] = "0" * 64
        if key == "run_id":
            bad[key] = "other-run"
        if key == "previous_receipt":
            bad[key] = None
        with pytest.raises(ValueError):
            reader.recompute_claim_receipt(bad, graph, source, refs, tenant_id=TENANT)


@pytest.mark.parametrize("name,prefix,suffix", CASES, ids=[case[0] for case in CASES])
def test_fxa_visibility_counterexamples_remain_unresolved(name, prefix, suffix, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_fxf as reader
    from proofops.adapters.local.local_raster_reader import runtime_policy

    from tests.acceptance.test_parsing import TENANT

    if runtime_policy()["status"] != "ready":
        pytest.skip("requires the pinned Linux CPU OCR runtime")
    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: MissingStore())
    source, graph = changed_pdf(prefix, suffix)
    receipt = reader.attest_claim_spans(
        graph,
        source,
        (graph.blocks[0].source_ref(),),
        tenant_id=TENANT,
        run_id="55555555-5555-4555-8555-555555555555",
    )
    assert receipt["records"][0]["status"] == "unresolved"


def test_deleted_recovery_cannot_acquire_ocr_during_composed_replay(monkeypatch):
    from copy import deepcopy

    from proofops.adapters.local import upstage_ocr_profile_fxf as profile

    from tests.acceptance.test_parsing import TENANT

    store = MissingStore()
    monkeypatch.setattr(profile.PageOCRStore, "from_env", lambda: store)
    source, graph = changed_pdf(b"0 0 1 1 re W n")
    refs = (graph.blocks[0].source_ref(),)
    reader = profile.for_run("55555555-5555-4555-8555-555555555555")
    receipt = reader.attest_claim_spans(graph, source, refs, tenant_id=TENANT)
    assert receipt["recovery_receipt"]["page_reads"]
    original = reader.previous.recompute_claim_receipt
    # The already verified parent contract is independent of this child replay test.
    monkeypatch.setattr(
        reader.previous, "recompute_claim_receipt", lambda *a, **k: receipt["previous_receipt"]
    )
    monkeypatch.setattr(store, "fetch", lambda *a, **k: pytest.fail("cold replay acquired pixels"))
    bad = deepcopy(receipt)
    bad["recovery_receipt"] = None
    with pytest.raises(ValueError, match="FXF_REPLAY_PAGE_MISMATCH"):
        reader.recompute_claim_receipt(bad, graph, source, refs, tenant_id=TENANT)
    monkeypatch.setattr(reader.previous, "recompute_claim_receipt", original)


def test_pixel_mapping_agrees_with_pdfium_integer_viewport():
    import ctypes
    from contextlib import closing

    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    from proofops.adapters.local.source_fxf import render_page

    source, _ = changed_pdf()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.pages[0].mediabox = RectangleObject([0, 0, 600.1, 800.3])
    writer.pages[0].cropbox = writer.pages[0].mediabox
    buffer = io.BytesIO()
    writer.write(buffer)
    source = buffer.getvalue()
    image = render_page(source, 1)
    m = image["manifest"]
    with pdfium.PdfDocument(source) as doc, closing(doc[0]) as page:
        w, h = m["pixel_size"]
        for px, py in ((0, 0), (w, h), (w // 3, h // 3)):
            x, y = ctypes.c_double(), ctypes.c_double()
            assert raw.FPDF_DeviceToPage(
                page, 0, 0, w, h, 0, px, py, ctypes.byref(x), ctypes.byref(y)
            )
            assert x.value == pytest.approx(px * m["width_pt"] / w)
            assert page.get_height() - y.value == pytest.approx(py * m["height_pt"] / h)
