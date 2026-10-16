"""FXA native guards plus exact, glyph-local trusted OCR of original page pixels."""

from contextlib import nullcontext
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from pypdf.errors import PdfReadError

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import claim_source_verification_v4 as v4
from proofops.adapters.local import source_fxf, source_h7
from proofops.adapters.local import upstage_ocr_mapping_v2 as mapping
from proofops.adapters.local.source_attestation_errors import ocr_acquisition_failure_code
from proofops.adapters.local.upstage_ocr_page import parse_response
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash

MIN_CONFIDENCE = 0.98


def claim_source_policy():
    return dict(
        schema="claim_source_render_conditioned_policy_v1",
        profile="fxf_claim-source-v1",
        base=v4.claim_source_policy(),
        raster=source_fxf.policy(),
        mapping_sha256=sha256(Path(mapping.__file__).read_bytes()).hexdigest(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        min_confidence=MIN_CONFIDENCE,
        admission="exact-quote; every-native-glyph-center-in-its-OCR-word-polygon",
    )


def _glyph_match(reading, normalization):
    quote = normalization["canonical_quote"]
    text = v4.v3._plain(reading.get("text", ""))
    if reading.get("status") != "read" or not strict._unique_quote(text, quote):
        return False
    start, end = text.index(quote), text.index(quote) + len(quote)
    paired, cursor = [], 0
    for word in reading["words"]:
        word_text = v4.v3._plain(word["text"])
        for index, char in enumerate(word_text, cursor):
            if start <= index < end and not char.isspace():
                paired.append((char, word))
        cursor += len(word_text) + 1
    glyphs = normalization["glyphs"]
    if len(paired) != len(glyphs):
        return False
    for (char, word), glyph in zip(paired, glyphs, strict=True):
        if char != glyph["char"] or word["confidence"] < MIN_CONFIDENCE:
            return False
        left, top, right, bottom = glyph["bbox"]
        x, y = (left + right) / 2, (top + bottom) / 2
        polygon = word["pdf_polygon"]
        if any(
            (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) < 0
            for a, b in zip(polygon, polygon[1:] + polygon[:1])
        ):
            return False
    return True


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id, store, saved_pages=None):
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("CLAIM_SOURCE_MISMATCH")
    blocks = {b.source_id: b for b in graph.blocks}
    table_members = {e.source_id for e in graph.edges if e.relation == "table_parent"}
    records, page_cache, pages, responses = [], {}, {}, {}
    replay = {p["physical_page"]: p for p in saved_pages} if saved_pages is not None else None
    if replay is not None and len(replay) != len(saved_pages):
        raise ValueError("FXF_DUPLICATE_PAGE_RECEIPT")
    with pdfium.PdfDocument(source) as native:
        document = source_h7.OriginalDocument(source, native)
        for ref in refs:
            record = dict(ref=asdict(ref), status="unresolved", reason="source_invalid")
            records.append(record)
            block = blocks.get(ref.source_id)
            if block is None or ref.source_id in table_members:
                continue
            try:
                record.update(
                    v4._native_record(document, native, graph, block, ref, tenant_id, page_cache)
                )
            except (ValueError, PdfReadError, pdfium.PdfiumError, KeyError, TypeError):
                record.update(status="unresolved", reason="fxf_native_layout_unresolved")
                continue
            if record["status"] != "pixel_required":
                continue
            record.update(status="unresolved", reason="rendered_quote_unresolved")
            number = ref.page_num
            if number not in pages:
                if len(pages) >= 10:
                    record["reason"] = "fxf_page_limit"
                    continue
                # Render only after FXA has proved the exact original quote,
                # offsets, geometry and annotation/catalog eligibility.
                try:
                    image = source_fxf.render_page(source, number)
                except (ValueError, PdfReadError, pdfium.PdfiumError):
                    record["reason"] = "fxf_page_render_unresolved"
                    continue
                item = dict(physical_page=number, manifest=image["manifest"])
                if replay is not None:
                    retained = replay.get(number)
                    if retained is None or retained.get("manifest") != image["manifest"]:
                        raise ValueError("FXF_REPLAY_PAGE_MISMATCH")
                    if "collection" in retained:
                        collection = store.validate(
                            retained["collection"], image, tenant_id=tenant_id
                        )
                        item["collection"] = collection
                    elif (
                        retained.get("failure")
                        in {"OCR_REPLAY_PAGE_MISSING", "OCR_BUDGET_EXHAUSTED"}
                        or ocr_acquisition_failure_code(ValueError(retained.get("failure")))
                        is not None
                    ):
                        item["failure"] = retained["failure"]
                    else:
                        raise ValueError("FXF_REPLAY_PAGE_INVALID")
                else:
                    try:
                        scope = getattr(store, "claim_fallback_scope", None)
                        with scope(number) if scope else nullcontext():
                            collection = store.fetch(image, tenant_id=tenant_id, run_id=run_id)
                        item["collection"] = store.validate(collection, image, tenant_id=tenant_id)
                    except ValueError as error:
                        code = ocr_acquisition_failure_code(error)
                        if code is None and str(error) != "OCR_REPLAY_PAGE_MISSING":
                            raise
                        item["failure"] = code or "OCR_REPLAY_PAGE_MISSING"
                pages[number] = item
                if "collection" in item:
                    response = parse_response(bytes.fromhex(item["collection"]["response_hex"]))
                    if [response["width"], response["height"]] != image["manifest"]["pixel_size"]:
                        raise ValueError("FXF_OCR_PIXEL_SIZE_MISMATCH")
                    responses[number] = response
            item = pages[number]
            record["page_read_sha256"] = canonical_hash(item)
            if "failure" in item:
                record["reason"] = "fxf_page_ocr_unavailable:" + item["failure"]
                continue
            manifest = item["manifest"]
            # FPDF_RenderPageBitmap uses the rounded integer viewport. The
            # existing mapper uses its exact width/height-to-page transform.
            peers = [
                b.bbox
                for b in graph.blocks
                if b.source_id != ref.source_id
                and b.bbox is not None
                and b.candidates
                and b.candidates[0].source.physical_page == number
            ]
            reading = mapping.map_words(
                responses[number], manifest, ref.bbox, competing_boxes=peers
            )
            record["rendered"] = reading
            if _glyph_match(reading, record["normalization"]):
                record.update(status="verified", reason=None)
    body = dict(
        schema="fxf_claim_source_attestation_v1",
        policy=claim_source_policy(),
        tenant_id=tenant_id,
        run_id=run_id,
        source_sha256=graph.source_sha256,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        graph_sha256=canonical_hash(asdict(graph)),
        page_reads=list(pages.values()),
        records=records,
    )
    return body | dict(artifact_sha256=canonical_hash(body))
