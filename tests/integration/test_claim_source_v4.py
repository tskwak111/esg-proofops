"""Render-conditioned native span attestation and exact lineage regressions."""

import io
from dataclasses import replace
from hashlib import sha256

import pytest
from proofops.adapters.local import claim_source_verification_v4 as v4
from proofops.application.ingest.graph_fusion import fuse_candidates
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    RectangleObject,
)

from tests.acceptance.test_parsing import TENANT, candidate
from tests.integration.test_claim_source_verification import geometry_pdf, quote_ref


def inputs(lines, text, bbox):
    source = geometry_pdf(lines)
    batch = replace(
        candidate("source-v4", [("P", "paragraph", text, bbox, ())]),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    return source, graph


def add_page_image(source):
    """Overlay a one pixel image over the page while retaining its text layer."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    page = writer.pages[0]
    image = DecodedStreamObject()
    image.set_data(bytes((255, 255, 255)))
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_ref = writer._add_object(image)
    resources = page[NameObject("/Resources")]
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Im0"): image_ref})
    overlay = DecodedStreamObject()
    overlay.set_data(b"q 600 0 0 800 0 0 cm /Im0 Do Q")
    existing = page.raw_get(NameObject("/Contents"))
    contents = list(existing) if isinstance(existing, ArrayObject) else [existing]
    page[NameObject("/Contents")] = ArrayObject(contents + [writer._add_object(overlay)])
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def crop_page(source, crop_box):
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.pages[0].cropbox = RectangleObject(crop_box)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def rebind_source_hash(graph, source):
    digest = sha256(source).hexdigest()
    batches = tuple(replace(batch, source_sha256=digest) for batch in graph.candidates)
    return replace(graph, source_sha256=digest, candidates=batches)


def test_native_text_uses_exact_offsets_and_replays_without_pixel_reader(monkeypatch):
    quote = "emissions 1234 tCO2e in 2025"
    source, graph = inputs(
        [(72, 720, "emissions 1234 tCO2e"), (72, 700, "in 2025")],
        "emissions 1234 tCO2e in 2025",
        (70, 690, 300, 741),
    )
    ref = quote_ref(graph, graph.blocks[0].raw_text, quote)
    monkeypatch.setattr(
        v4.v3,
        "_rendered_text",
        lambda *a, **k: pytest.fail("native text admission must not require pixel OCR"),
    )
    receipt = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    record = receipt["records"][0]
    assert record["status"] == "verified"
    assert record["render_type_proof"]["status"] == "native_text"
    offset_map = record["native_offset_map"]
    assert offset_map["reversible"] is True
    assert offset_map["source_start"] == ref.char_start
    assert offset_map["source_end"] == ref.char_end
    assert len(offset_map["characters"]) == len(quote.replace(" ", ""))
    assert any(
        "\n" in boundary["native_whitespace"]
        for boundary in record["native_offset_map"]["boundaries"]
    )
    assert v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT) == receipt


def test_exact_offset_map_retains_zero_ink_trailing_source_whitespace():
    source_text = "emissions 1234 tCO2e "
    visible_text = source_text.rstrip()
    source, graph = inputs([(72, 720, visible_text)], source_text, (70, 710, 300, 741))
    ref = quote_ref(graph, source_text, source_text)
    record = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "verified"
    offset_map = record["native_offset_map"]
    edge = offset_map["edge_boundaries"][0]
    last_character = offset_map["characters"][-1]
    assert edge["kind"] == "trailing_whitespace"
    assert edge["source_start"] == ref.char_end - 1
    assert edge["source_end"] == ref.char_end
    assert edge["source_whitespace"] == " "
    assert edge["native_text_boundary"] == last_character["native_text_offset"] + 1
    assert edge["before_pdfium_char_index"] == last_character["pdfium_char_index"]
    assert edge["after_pdfium_char_index"] is None


def test_image_backed_text_layer_requires_pixel_confirmation(monkeypatch):
    text = "emissions 1234 tCO2e in 2025"
    plain, graph = inputs([(72, 720, text)], text, (70, 710, 340, 741))
    source = add_page_image(plain)
    graph = replace(graph, source_sha256=sha256(source).hexdigest())
    batch = replace(graph.candidates[0], source_sha256=graph.source_sha256)
    graph = replace(graph, candidates=(batch,))
    ref = graph.blocks[0].source_ref()
    from proofops.adapters.local import claim_source_verification as strict
    from proofops.adapters.local import claim_span_bullet_alignment as bullet

    # Inject the same failing pixel read across the full v3 chain on Linux
    # and macOS, so this checks a mismatch rather than platform availability.
    for module in (strict, bullet, v4.v3):
        monkeypatch.setattr(
            module,
            "_rendered_text",
            lambda *a, **k: dict(status="read", text="incorrect OCR value 1235"),
        )
    record = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "unresolved"
    assert record["reason"] == "rendered_quote_unresolved"
    assert record["render_type_proof"]["reason"] == "non_text_object_overlaps_quote"
    assert record["pixel_fallback"]["status"] == "unresolved"


def test_lineage_comparison_holds_manifest_and_scope_mismatches():
    text = "LG globally certifies 15 of 17 production sites."
    source, graph = inputs([(72, 720, text)], text, (70, 710, 450, 741))
    ref = quote_ref(graph, text, "15 of 17 production sites")
    receipt = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    original = receipt["records"][0]
    assert original["status"] == "verified"
    altered = dict(receipt, parse_manifest_id="22222222-2222-4222-8222-222222222222")
    comparison = v4.compare_source_lineage(receipt, original, altered, original)
    assert comparison["status"] == "held"
    assert comparison["diagnostic_only"] is True
    assert "parse_manifest_id" in comparison["mismatches"]

    wrong_scope = replace(ref, quote="15 of 17 production sites globally", char_end=ref.char_end)
    rejected = v4.attest_claim_spans(graph, source, (wrong_scope,), tenant_id=TENANT)
    assert rejected["records"][0]["status"] == "unresolved"
    assert rejected["records"][0]["reason"] == "source_ref_mismatch"

    wrong_number = replace(ref, quote=ref.quote.replace("15 of 17", "15 of 18"))
    assert (
        v4.attest_claim_spans(graph, source, (wrong_number,), tenant_id=TENANT)["records"][0][
            "status"
        ]
        == "unresolved"
    )
    whole = quote_ref(graph, text, text)
    wrong_entity = replace(whole, quote=text.replace("LG", "SK"))
    assert (
        v4.attest_claim_spans(graph, source, (wrong_entity,), tenant_id=TENANT)["records"][0][
            "status"
        ]
        == "unresolved"
    )


def test_wrong_page_and_policy_tampering_are_rejected():
    text = "emissions 1234 tCO2e"
    source, graph = inputs([(72, 720, text)], text, (70, 710, 300, 741))
    ref = graph.blocks[0].source_ref()
    wrong_page = replace(ref, page_num=2)
    record = v4.attest_claim_spans(graph, source, (wrong_page,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "unresolved"
    assert record["reason"] == "source_ref_mismatch"

    from proofops.adapters.local import claim_source_policies

    policy = v4.claim_source_policy()
    assert claim_source_policies.claim_source_reader(policy) is v4
    assert claim_source_policies.publication_reader(policy) is v4
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        claim_source_policies.claim_source_reader(dict(policy, verifier_sha256="f" * 64))


def test_v4_profile_is_opt_in_and_default_remains_v3():
    from argparse import Namespace

    from proofops.application.analysis_profile import PROFILE, apply_pilot_profile

    explicit = Namespace(analysis_profile=PROFILE, resume=False, claim_source_profile=v4.PROFILE)
    apply_pilot_profile(explicit)
    assert explicit.claim_source_profile == v4.PROFILE

    default = Namespace(analysis_profile=PROFILE, resume=False)
    apply_pilot_profile(default)
    assert default.claim_source_profile == "claim-source-v3"


def test_text_layer_quote_outside_visible_page_crop_stays_held():
    text = "emissions 1234 tCO2e"
    source, graph = inputs([(72, 720, text)], text, (70, 710, 300, 741))
    source = crop_page(source, (0, 0, 60, 800))
    graph = rebind_source_hash(graph, source)
    ref = graph.blocks[0].source_ref()
    record = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "unresolved"
    assert record["reason"] == "geometry_unsupported"
