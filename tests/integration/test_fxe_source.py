"""FXE original-region pixels and strict replay; historical readers stay immutable."""

import io
import math
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_claim_source_v4_visibility import CASES, TEXT, changed_pdf


def test_large_page_crop_preserves_nominal_pixels_without_full_page_allocation(monkeypatch):
    from proofops.adapters.local import source_fxe as raster

    source, _ = changed_pdf()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.pages[0].mediabox = RectangleObject([0, 0, 3543, 2362])
    writer.pages[0].cropbox = RectangleObject([0, 0, 3543, 2362])
    output = io.BytesIO()
    writer.write(output)
    source = output.getvalue()
    box = (70.125, 1621.25, 340.75, 1661.875)
    captured = []
    monkeypatch.setattr(
        raster.source_h7, "_ocr", lambda png: captured.append(png) or {"text": TEXT}
    )
    reader = raster.RasterReader(source)
    read = reader.read(SimpleNamespace(page_number=1, width=3543, height=2362), box, padding_px=6)
    assert read["status"] == "read"
    assert read["scale"] == 3
    assert math.prod(read["rendered_pixels"]) < 200_000
    assert math.prod(read["page_pixels"]) > raster.MAX_PIXELS
    # Compare decoded pixels with the original full render, not a fabricated crop.
    with pdfium.PdfDocument(source) as doc, closing(doc[0]) as page:
        with closing(page.render(scale=3, draw_annots=True)) as bitmap:
            with bitmap.to_pil() as full:
                expected = full.crop(read["pixel_bbox"]).convert("RGB")
    with Image.open(io.BytesIO(captured[0])) as actual:
        assert (
            actual.crop((6, 6, actual.width - 6, actual.height - 6)).convert("RGB").tobytes()
            == expected.tobytes()
        )
    assert (
        reader.read(SimpleNamespace(page_number=1, width=3542, height=2362), box)["status"]
        == "unresolved"
    )
    assert (
        reader.read(SimpleNamespace(page_number=1, width=3543, height=2362), (0, 0, 3543, 2362))[
            "status"
        ]
        == "unresolved"
    )


def test_visible_active_clip_uses_portable_pixels_and_replays(monkeypatch):
    from proofops.adapters.local import claim_source_fxe as reader

    source, graph = changed_pdf(b"0 0 m 600 800 l 0 800 l h W n")
    ref = graph.blocks[0].source_ref()
    monkeypatch.setattr(reader.source_fxe.source_h7, "_ocr", lambda png: {"text": TEXT})
    before = asdict(graph)
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    record = receipt["records"][0]
    assert record["status"] == "verified"
    assert record["render_type_proof"]["status"] == "pixel_required"
    assert record["pixel_attempts"][0]["source_sha256"] == graph.source_sha256
    assert reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT) == receipt
    assert asdict(graph) == before
    bad = replace(ref, quote=TEXT.replace("1234", "1235"))
    assert (
        reader.attest_claim_spans(graph, source, (bad,), tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, source + b"x", (ref,), tenant_id=TENANT)
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, source, (ref,), tenant_id="wrong-tenant")


@pytest.mark.parametrize("name,prefix,suffix", CASES, ids=[c[0] for c in CASES])
def test_fxa_hidden_pixels_cannot_become_verified(name, prefix, suffix):
    from proofops.adapters.local import claim_source_fxe as reader
    from proofops.adapters.local.local_raster_reader import runtime_policy

    if runtime_policy()["status"] != "ready":
        pytest.skip("requires the pinned Linux CPU OCR runtime")
    source, graph = changed_pdf(prefix, suffix)
    receipt = reader.attest_claim_spans(
        graph, source, (graph.blocks[0].source_ref(),), tenant_id=TENANT
    )
    assert receipt["records"][0]["status"] == "unresolved"


def test_new_profile_does_not_reinterpret_v23_policy():
    from proofops.adapters.local import upstage_ocr_profile_fxe as fxe
    from proofops.adapters.local import upstage_ocr_profile_v21 as old
    from proofops.adapters.local.claim_source_policies import page_ocr_profile, publication_reader
    from proofops.application.analysis_profile import (
        FINALS_I23_POLICY,
        FXE_POLICY,
        V2_PROFILE,
        policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert page_ocr_profile(fxe.PROFILE, policy=fxe.claim_source_policy()) is fxe
    assert publication_reader(fxe.claim_source_policy()) is fxe
    assert page_ocr_profile(old.PROFILE, policy=old.claim_source_policy()) is old
    assert fxe.native_policy() == old.native_policy()
    assert fxe.table_span_policy() == old.table_span_policy()
    assert (
        canonical_hash(FINALS_I23_POLICY)
        == "66669e915909dc62460931410c06215c4e520688523ada7f9bdb0e89724541b7"
    )
    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(FXE_POLICY)) == FXE_POLICY
    changed = deepcopy(fxe.claim_source_policy())
    changed["verifier_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        publication_reader(changed)


def test_composed_reader_replays_whole_receipt_and_rejects_forgery(monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_fxe as fxe

    from tests.integration.test_claim_source_v4 import inputs

    monkeypatch.setattr(fxe.PageOCRStore, "from_env", lambda: SimpleNamespace())
    source, graph = inputs([(72, 720, TEXT)], TEXT, (70, 710, 340, 741))
    ref = graph.blocks[0].source_ref()
    reader = fxe.for_run("55555555-5555-4555-8555-555555555555")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "verified"
    assert receipt["records"] == receipt["previous_receipt"]["records"]
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=TENANT) == receipt
    )
    altered = deepcopy(receipt)
    altered["records"][0]["ref"]["quote"] = TEXT.replace("1234", "1235")
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(altered, graph, source, (ref,), tenant_id=TENANT)
