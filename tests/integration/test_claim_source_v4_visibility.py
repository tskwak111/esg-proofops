"""Hidden/clipped original bytes cannot take the native prose shortcut."""

import io
from dataclasses import asdict
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest
from proofops.adapters.local import claim_source_verification_v4 as v4
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, FloatObject, NameObject

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_claim_source_v4 import inputs, rebind_source_hash

TEXT = "emissions 1234 tCO2e in 2025"
CASES = [
    ("r16_all_hidden", b"0 0 1 1 re W n", b""),
    ("r16_digits_clipped", b"0 0 125 800 re W n", b""),
    ("r16_evenodd_hole", b"0 0 600 800 re 65 700 300 50 re W* n", b""),
    ("r16_invisible_mode", b"3 Tr", b""),
    ("nonzero_hole", b"0 0 600 800 re 65 700 m 65 750 l 365 750 l 365 700 l h W n", b""),
    ("triangular_clip", b"0 0 m 600 0 l 0 800 l h W n", b""),
    ("text_clip", b"BT /F1 12 Tf 7 Tr 0 0 Td (X) Tj ET 0 Tr", b""),
    ("white_paint", b"1 g", b""),
    ("zero_alpha", b"/Hidden gs", b""),
    ("vector_cover", b"", b"1 g 65 700 300 50 re f"),
    ("text_cover", b"", b"BT /F1 12 Tf 1 g 72 720 Td (emissions) Tj ET"),
]


def changed_pdf(prefix=b"", suffix=b""):
    source, graph = inputs([(72, 720, TEXT)], TEXT, (70, 710, 340, 741))
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    page = writer.pages[0]
    page["/Resources"][NameObject("/ExtGState")] = DictionaryObject(
        {NameObject("/Hidden"): DictionaryObject({NameObject("/ca"): FloatObject(0)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"q\n" + prefix + b"\n" + page.get_contents().get_data() + b"\n" + suffix + b"\nQ"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    source = output.getvalue()
    return source, rebind_source_hash(graph, source)


@pytest.fixture
def unread_pixels(monkeypatch):
    # Exercise the real frozen v3 chain, with an unavailable local OCR reader.
    from proofops.adapters.local import claim_source_verification as strict
    from proofops.adapters.local import claim_span_bullet_alignment as bullet

    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        return dict(status="unreadable", reason="offline_pixel_reader_unavailable")

    for module in (strict, bullet, v4.v3):
        monkeypatch.setattr(module, "_rendered_text", unavailable)
    return calls


@pytest.mark.parametrize("name,prefix,suffix", CASES, ids=[c[0] for c in CASES])
def test_hidden_or_uncertain_paint_requires_real_v3_gate(name, prefix, suffix, unread_pixels):
    source, graph = changed_pdf(prefix, suffix)
    ref = graph.blocks[0].source_ref()
    before = asdict(graph)
    record = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "unresolved"
    assert record["render_type_proof"]["status"] == "pixel_required"
    assert record["pixel_fallback"]["status"] == "unresolved"
    # v3 may hold an ambiguous native layer before attempting OCR.
    if name != "text_cover":
        assert unread_pixels
    assert asdict(graph) == before
    # The first hidden/hole cases have no ink at all, despite their text layer.
    if name in {
        "r16_all_hidden",
        "r16_evenodd_hole",
        "nonzero_hole",
        "triangular_clip",
        "text_clip",
        "white_paint",
        "zero_alpha",
        "vector_cover",
        "r16_invisible_mode",
    }:
        with pdfium.PdfDocument(source) as document:
            page = document[0]
            bitmap = page.render(scale=1)
            crop = bitmap.to_pil().convert("RGB").crop((70, 59, 340, 90))
            assert all(min(pixel) >= 240 for pixel in crop.get_flattened_data())
            bitmap.close()
            page.close()


def test_v21_cannot_recover_a_hidden_quote_through_previous_reader(monkeypatch, unread_pixels):
    from proofops.adapters.local import upstage_ocr_profile_v21 as reader

    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: SimpleNamespace())
    source, graph = changed_pdf(b"0 0 1 1 re W n")
    receipt = reader.attest_claim_spans(
        graph,
        source,
        (graph.blocks[0].source_ref(),),
        tenant_id=TENANT,
        run_id="55555555-5555-4555-8555-555555555555",
    )
    assert receipt["prose_receipt"]["records"][0]["status"] == "unresolved"
    assert receipt["records"][0]["status"] == "unresolved"
    assert receipt["artifact_sha256"] == canonical_hash(
        {key: value for key, value in receipt.items() if key != "artifact_sha256"}
    )


def test_visible_clipped_text_needs_matching_pixel_confirmation(monkeypatch):
    from proofops.adapters.local import claim_source_verification as strict
    from proofops.adapters.local import claim_span_bullet_alignment as bullet
    from proofops.adapters.local import selected_cell_table_verification as cells

    source, graph = changed_pdf(b"0 0 m 600 800 l 0 800 l h W n")
    ref = graph.blocks[0].source_ref()
    for module in (strict, bullet, v4.v3):
        monkeypatch.setattr(
            module, "_rendered_text", lambda *a, **k: dict(status="read", text=TEXT)
        )
    monkeypatch.setattr(cells, "_rendered_cell", lambda *a, **k: dict(status="read", text=TEXT))
    record = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "verified"
    assert record["render_type_proof"]["reason"] == "active_clip_requires_pixels"
    assert record["pixel_fallback"]["status"] == "verified"
    # A failed digit read may never be rescued by the unchanged native layer.
    for module in (strict, bullet, v4.v3):
        monkeypatch.setattr(
            module,
            "_rendered_text",
            lambda *a, **k: dict(status="read", text=TEXT.replace("1234", "1235")),
        )
    monkeypatch.setattr(
        cells,
        "_rendered_cell",
        lambda *a, **k: dict(status="read", text=TEXT.replace("1234", "1235")),
    )
    record = v4.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert record["status"] == "unresolved"


@pytest.mark.parametrize("api", ["FPDFPageObj_GetClipPath", "FPDFText_GetTextObject"])
def test_missing_visibility_api_requires_pixels(api, monkeypatch, unread_pixels):
    def unavailable(*args):
        raise RuntimeError("visibility_api_unavailable")

    source, graph = changed_pdf()
    monkeypatch.setattr(v4.raw, api, unavailable)
    record = v4.attest_claim_spans(
        graph, source, (graph.blocks[0].source_ref(),), tenant_id=TENANT
    )["records"][0]
    assert record["status"] == "unresolved"
    assert record["render_type_proof"]["status"] == "pixel_required"
    assert record["pixel_fallback"]["status"] == "unresolved"


@pytest.mark.parametrize("page_ocr", [False, True])
def test_old_exact_policy_replays_but_cannot_publish(page_ocr, monkeypatch):
    from proofops.adapters.local import claim_source_policies as policies
    from proofops.adapters.local import upstage_ocr_profile_v21 as current_page
    from proofops.adapters.local.historical_prose_replay import historical_prose_reader

    monkeypatch.setattr(current_page.PageOCRStore, "from_env", lambda: SimpleNamespace())
    old = historical_prose_reader(page_ocr=page_ocr)
    current = current_page if page_ocr else v4
    policy = old.claim_source_policy()
    assert policy != current.claim_source_policy()
    reader = policies.claim_source_reader(policy)
    source, graph = changed_pdf()
    refs = (graph.blocks[0].source_ref(),)
    run_id = "55555555-5555-4555-8555-555555555555"
    receipt = old.attest_claim_spans(graph, source, refs, tenant_id=TENANT, run_id=run_id)
    assert (
        reader.attest_claim_spans(graph, source, refs, tenant_id=TENANT, run_id=run_id) == receipt
    )
    assert receipt["records"][0]["status"] == "verified"
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_MISMATCH"):
        policies.publication_reader(policy)
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        policies.claim_source_reader(policy | dict(verifier_sha256="0" * 64))
    dependency = "previous_policy_sha256" if page_ocr else "base"
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        policies.claim_source_reader(policy | {dependency: "0" * 64})
    assert policies.publication_reader(current.claim_source_policy()) is current


def test_frozen_replay_bytes_are_authenticated(tmp_path, monkeypatch):
    from proofops.adapters.local import historical_prose_replay as historical

    for name in historical._PINNED:
        (tmp_path / name).write_bytes((historical._ROOT / name).read_bytes())
    path = tmp_path / "claim_source_v4_pre_visibility.py"
    path.write_bytes(path.read_bytes() + b"\n")
    monkeypatch.setattr(historical, "_ROOT", tmp_path)
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        historical.historical_prose_reader()
