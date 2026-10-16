"""Failed-span recovery from exact native glyphs and trusted cropped Upstage OCR.

No text correction, threshold relaxation or table ownership inference. Retained
collections are authenticated by the existing private ledger on every replay.
"""

import io
import math
from contextlib import closing, nullcontext
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from PIL import ImageOps
from pypdf.errors import PdfReadError

from proofops.adapters.local import claim_source_fxf as fxf
from proofops.adapters.local import claim_source_verification_v4 as native
from proofops.adapters.local import source_fxf, source_h7
from proofops.adapters.local import upstage_ocr_mapping_v2 as mapping
from proofops.adapters.local.local_raster_reader import interactive_catalog_requires_review
from proofops.adapters.local.source_attestation_errors import ocr_acquisition_failure_code
from proofops.adapters.local.upstage_ocr_page import MAX_PIXELS, parse_response
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash

SCALE = 3
PADDING = 6
MAX_REGIONS = 24


def policy():
    return dict(
        profile="cf4_original-region-v1",
        native=native.claim_source_policy(),
        pixels=source_fxf.policy(),
        glyph_match_sha256=sha256(Path(fxf.__file__).read_bytes()).hexdigest(),
        mapping_sha256=sha256(Path(mapping.__file__).read_bytes()).hexdigest(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        scale=SCALE,
        padding_px=PADDING,
        max_aspect_ratio=4,
        max_regions=MAX_REGIONS,
        min_confidence=fxf.MIN_CONFIDENCE,
        admission="exact-native-quote-and-OCR; every-glyph-center-in-own-word-polygon",
    )


def render_region(source, number, box):
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or type(number) is not int
        or len(box) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
    ):
        raise ValueError("CF4_RENDER_INPUT_INVALID")
    if interactive_catalog_requires_review(source):
        raise ValueError("CF4_INTERACTIVE_VISIBILITY")
    with pdfium.PdfDocument(source) as doc:
        if not 1 <= number <= len(doc):
            raise ValueError("CF4_PAGE_INVALID")
        with closing(doc[number - 1]) as page:
            w, h = page.get_size()
            media = page.get_mediabox()
            if (
                page.get_rotation()
                or media[:2] != (0, 0)
                or page.get_cropbox() != media
                or not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h)
            ):
                raise ValueError("CF4_PAGE_GEOMETRY_UNSUPPORTED")
            width, height = math.ceil(w * SCALE), math.ceil(h * SCALE)
            left, top = math.floor(box[0] * SCALE), math.floor(box[1] * SCALE)
            right, bottom = math.ceil(box[2] * SCALE), math.ceil(box[3] * SCALE)
            crop_width = right - left + 2 * PADDING
            vertical_padding = max(PADDING, math.ceil((crop_width / 4 - (bottom - top)) / 2))
            size = [crop_width, bottom - top + 2 * vertical_padding]
            if math.prod(size) > MAX_PIXELS:
                raise ValueError("CF4_RENDER_LIMIT")
            crop = tuple(
                math.nextafter(v / SCALE, -math.inf) if v else 0
                for v in (left, height - bottom, width - right, top)
            )
            with closing(page.render(scale=SCALE, crop=crop, draw_annots=True)) as bitmap:
                if (bitmap.width, bitmap.height) != (right - left, bottom - top):
                    raise ValueError("CF4_PIXEL_MAPPING_MISMATCH")
                with (
                    bitmap.to_pil() as image,
                    ImageOps.expand(
                        image,
                        border=(PADDING, vertical_padding, PADDING, vertical_padding),
                        fill="white",
                    ) as padded,
                ):
                    buffer = io.BytesIO()
                    padded.save(buffer, format="PNG")
    png = buffer.getvalue()
    if len(png) > 50 * 1024 * 1024:
        raise ValueError("CF4_RENDER_LIMIT")
    manifest = dict(
        profile="cf4_original-region-v1",
        source_sha256=sha256(source).hexdigest(),
        physical_page=number,
        bbox=list(box),
        width_pt=w,
        height_pt=h,
        rotation=0,
        media_box=list(media),
        crop_box=list(media),
        scale=SCALE,
        padding_px=PADDING,
        max_aspect_ratio=4,
        vertical_padding_px=vertical_padding,
        draw_annotations=True,
        pixel_size=size,
        pixel_bbox=[left, top, right, bottom],
        png_sha256=sha256(png).hexdigest(),
        crop_to_pdf=[
            1 / SCALE,
            0,
            0,
            1 / SCALE,
            (left - PADDING) / SCALE,
            (top - vertical_padding) / SCALE,
        ],
    )
    return dict(manifest=manifest, png=png)


def map_region(collection, manifest, ref, peers):
    response = parse_response(bytes.fromhex(collection["response_hex"]))
    if [response["width"], response["height"]] != manifest["pixel_size"]:
        raise ValueError("CF4_OCR_PIXEL_SIZE_MISMATCH")
    a, _, _, d, e, f = manifest["crop_to_pdf"]
    # Transform provider polygons into original PDF points before running the
    # existing text-independent ownership/reading-order mapper unchanged.
    response = dict(
        response,
        width=manifest["width_pt"],
        height=manifest["height_pt"],
        words=[
            dict(word, polygon=[[p[0] * a + e, p[1] * d + f] for p in word["polygon"]])
            for word in response["words"]
        ],
    )
    return mapping.map_words(response, manifest, ref.bbox, competing_boxes=peers)


def _failure(error):
    if str(error) in {
        "OCR_COLLECTION_FAILED_RESERVATION_RETAINED:OCR_RESPONSE_INVALID",
        "OCR_RESPONSE_INVALID",
    }:
        return "OCR_RESPONSE_INVALID"
    code = ocr_acquisition_failure_code(error)
    return code or ("OCR_REPLAY_PAGE_MISSING" if str(error) == "OCR_REPLAY_PAGE_MISSING" else None)


def attest_regions(graph, source, refs, *, tenant_id, run_id, store, saved_regions=None):
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("CLAIM_SOURCE_MISMATCH")
    blocks = {b.source_id: b for b in graph.blocks}
    table_members = {e.source_id for e in graph.edges if e.relation == "table_parent"}
    records, regions, page_cache = [], {}, {}
    retained = None
    if saved_regions is not None:
        retained = {canonical_hash(r["manifest"]): r for r in saved_regions}
        if len(retained) != len(saved_regions):
            raise ValueError("CF4_DUPLICATE_REGION_RECEIPT")
    with pdfium.PdfDocument(source) as pdf:
        document = source_h7.OriginalDocument(source, pdf)
        for ref in refs:
            record = dict(ref=asdict(ref), status="unresolved", reason="source_invalid")
            records.append(record)
            block = blocks.get(ref.source_id)
            if block is None or block.kind != "paragraph" or ref.source_id in table_members:
                continue
            try:
                try:
                    proof = native._native_record(
                        document, pdf, graph, block, ref, tenant_id, page_cache
                    )
                except (ValueError, KeyError, TypeError):
                    record["reason"] = "cf4_native_layout_unresolved"
                    continue
                if proof["status"] not in ("pixel_required", "verified"):
                    record.update(proof)
                    continue
                # Even native-only passes need independent OCR in this recovery.
                record.update(proof, status="unresolved", reason="cf4_pixel_quote_unresolved")
                glyphs = proof["normalization"]["glyphs"]
                box = (
                    min(g["bbox"][0] for g in glyphs),
                    min(g["bbox"][1] for g in glyphs),
                    max(g["bbox"][2] for g in glyphs),
                    max(g["bbox"][3] for g in glyphs),
                )
                key = (ref.page_num, box)
                if key not in regions:
                    if len(regions) >= MAX_REGIONS:
                        record["reason"] = "cf4_region_limit"
                        continue
                    try:
                        image = render_region(source, ref.page_num, box)
                    except ValueError as error:
                        record["reason"] = str(error)
                        continue
                    item = dict(manifest=image["manifest"])
                    if retained is not None:
                        saved = retained.get(canonical_hash(image["manifest"]))
                        if saved is None:
                            raise ValueError("CF4_REPLAY_REGION_MISMATCH")
                        if "collection" in saved:
                            item["collection"] = store.validate(
                                saved["collection"], image, tenant_id=tenant_id
                            )
                        elif _failure(ValueError(saved.get("failure"))):
                            item["failure"] = saved["failure"]
                        else:
                            raise ValueError("CF4_REPLAY_REGION_MISMATCH")
                    else:
                        try:
                            scope = getattr(store, "claim_fallback_scope", None)
                            with scope(ref.page_num) if scope else nullcontext():
                                collection = store.fetch(image, tenant_id=tenant_id, run_id=run_id)
                            item["collection"] = store.validate(
                                collection, image, tenant_id=tenant_id
                            )
                        except ValueError as error:
                            code = _failure(error)
                            if code is None:
                                raise
                            item["failure"] = code
                    regions[key] = item
                item = regions[key]
                record["cf4_region_sha256"] = canonical_hash(item)
                if "failure" in item:
                    record["reason"] = "cf4_ocr_unavailable:" + item["failure"]
                    continue
                peers = [
                    b.bbox
                    for b in graph.blocks
                    if b.source_id != ref.source_id
                    and b.bbox is not None
                    and b.candidates
                    and b.candidates[0].source.physical_page == ref.page_num
                ]
                reading = map_region(item["collection"], item["manifest"], ref, peers)
                record["rendered"] = reading
                if fxf._glyph_match(reading, proof["normalization"]):
                    record.update(status="verified", reason=None)
            except (PdfReadError, pdfium.PdfiumError):
                record.update(status="unresolved", reason="cf4_native_layout_unresolved")
    if retained is not None and set(retained) != {
        canonical_hash(r["manifest"]) for r in regions.values()
    }:
        raise ValueError("CF4_REPLAY_REGION_MISMATCH")
    body = dict(
        schema="cf4_region_attestation_v1",
        policy=policy(),
        tenant_id=tenant_id,
        run_id=run_id,
        source_sha256=graph.source_sha256,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        graph_sha256=canonical_hash(asdict(graph)),
        records=records,
        region_reads=list(regions.values()),
    )
    return body | dict(artifact_sha256=canonical_hash(body))
