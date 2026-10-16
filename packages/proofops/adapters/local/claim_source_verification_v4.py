"""Opt-in source attestation with a render-type-conditioned pixel gate.

Native text is admitted only from the authenticated original bytes, through
exact parser codepoint offsets, exact non-space character alignment and visible
PDF glyph geometry. Ambiguous or image-backed spans fall back to the frozen v3
pixel reader. Parser refs and older receipts are never rewritten.
"""

import ctypes
import io
import math
from contextlib import closing
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pdfminer.pdftypes import resolve1

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import claim_source_verification_v3 as v3
from proofops.application.evidence import span_citations
from proofops.application.evidence.citations import verify_source_ref
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "claim-source-v4"
POLICY_SCHEMA = "claim_source_render_conditioned_policy_v1"
SCHEMA = "claim_source_attestation_v4"
_VISIBLE_TEXT_MODES = frozenset((0, 1, 2))
_TEXT_OBJECT = getattr(raw, "FPDF_PAGEOBJ_TEXT", 1)


def claim_source_policy():
    from proofops.application.evidence import citations

    return dict(
        schema=POLICY_SCHEMA,
        profile=PROFILE,
        base=v3.claim_source_policy(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        citation_sha256=sha256(Path(citations.__file__).read_bytes()).hexdigest(),
        span_citation_sha256=sha256(Path(span_citations.__file__).read_bytes()).hexdigest(),
        pdfium_version=version("pypdfium2"),
        pdfplumber_version=version("pdfplumber"),
    )


def _intersects(left, right):
    return left[2] > right[0] and left[0] < right[2] and left[3] > right[1] and left[1] < right[3]


def _exact_source_ref(graph, block, ref, tenant_id):
    if (
        block.kind != "paragraph"
        or block.quality not in {"verified", "unverified"}
        or block.winner is None
        or not 0 <= block.winner < len(block.candidates)
    ):
        return False
    candidate = block.candidates[block.winner]
    source = candidate.source
    raw_text = source.raw_text
    if (
        candidate.bbox != ref.bbox
        or source.physical_page != ref.page_num
        or source.printed_page_label != ref.printed_page_label
        or source.document_version_id != graph.document_version_id
        or source.parse_manifest_id != graph.parse_manifest_id
        or sha256(raw_text.encode("utf-8")).hexdigest() != ref.raw_text_sha256
        or not 0 <= ref.char_start < ref.char_end <= len(raw_text)
        or raw_text[ref.char_start : ref.char_end] != ref.quote
        or ref.char_end - ref.char_start != len(ref.quote)
    ):
        return False
    checked = replace(
        graph,
        blocks=tuple(
            replace(item, quality="verified") if item.source_id == block.source_id else item
            for item in graph.blocks
        ),
    )
    return verify_source_ref(ref, checked, tenant_id=tenant_id).verification_state == "verified"


def _page_geometry_supported(document, native, block, ref):
    candidate = block.candidates[block.winner]
    box, geometry = candidate.bbox, candidate.geometry
    if not 1 <= ref.page_num <= len(document.pages) or ref.page_num > len(native):
        return None, "geometry_unsupported"
    page = document.pages[ref.page_num - 1]
    if (
        box is None
        or candidate.has_invalid_geometry
        or page.rotation
        or geometry.rotation
        or tuple(page.mediabox[:2]) != (0, 0)
        or tuple(page.cropbox) != tuple(page.mediabox)
        or tuple(geometry.crop_box[:2]) != (0, 0)
        or abs(page.width - geometry.width_pt) > 0.001
        or abs(page.height - geometry.height_pt) > 0.001
    ):
        return None, "geometry_unsupported"
    form = resolve1(document.doc.catalog.get("AcroForm"))
    if "OCProperties" in document.doc.catalog or (
        isinstance(form, dict) and any(k in form for k in ("XFA", "NeedsRendering"))
    ):
        return None, "interactive_visibility_requires_review"
    return page, None


def _reversible_offset_map(ref, normalization):
    """Build a lossless source-codepoint -> native-text/glyph map.

    Non-space characters must agree literally. Whitespace can differ only when
    a line break is present and the adjacent glyphs are on distinct rows.
    """
    quote = ref.quote
    if not quote:
        return None
    native_text = normalization.get("native_text")
    canonical_quote = normalization.get("canonical_quote")
    parser_offsets = normalization.get("canonical_to_parser")
    native_offsets = normalization.get("native_nonspace_offsets")
    canonical_offsets = normalization.get("canonical_nonspace_offsets")
    glyphs = normalization.get("glyphs")
    if not all(
        isinstance(value, str | list)
        for value in (
            native_text,
            canonical_quote,
            parser_offsets,
            native_offsets,
            canonical_offsets,
            glyphs,
        )
    ):
        return None
    parser_positions = [i for i, char in enumerate(quote) if not char.isspace()]
    if not parser_positions or not (
        len(parser_positions)
        == len(parser_offsets)
        == len(native_offsets)
        == len(canonical_offsets)
        == len(glyphs)
    ):
        return None
    characters = []
    for index, (parser_at, native_at, canonical_at, glyph) in enumerate(
        zip(parser_offsets, native_offsets, canonical_offsets, glyphs, strict=True)
    ):
        if (
            parser_at != parser_positions[index]
            or type(native_at) is not int
            or type(canonical_at) is not int
            or not 0 <= native_at < len(native_text)
            or not 0 <= canonical_at < len(canonical_quote)
        ):
            return None
        char = quote[parser_at]
        if (
            char.isspace()
            or native_text[native_at] != char
            or canonical_quote[canonical_at] != char
            or glyph.get("char") != char
            or type(glyph.get("index")) is not int
        ):
            return None
        characters.append(
            dict(
                source_offset=ref.char_start + parser_at,
                codepoint=char,
                native_text_offset=native_at,
                canonical_quote_offset=canonical_at,
                pdfium_char_index=glyph["index"],
            )
        )

    boundaries = []
    for index in range(len(parser_positions) - 1):
        left_at, right_at = parser_positions[index : index + 2]
        left_native, right_native = native_offsets[index : index + 2]
        source_gap = quote[left_at + 1 : right_at]
        native_gap = native_text[left_native + 1 : right_native]
        left_box, right_box = glyphs[index]["bbox"], glyphs[index + 1]["bbox"]
        separated_rows = min(left_box[3], right_box[3]) <= max(left_box[1], right_box[1])
        if source_gap != native_gap and not (
            any(char in source_gap + native_gap for char in "\r\n") and separated_rows
        ):
            return None
        boundaries.append(
            dict(
                source_start=ref.char_start + left_at + 1,
                source_end=ref.char_start + right_at,
                source_whitespace=source_gap,
                native_start=left_native + 1,
                native_end=right_native,
                native_whitespace=native_gap,
                before_pdfium_char_index=glyphs[index]["index"],
                after_pdfium_char_index=glyphs[index + 1]["index"],
            )
        )
    edge_boundaries = []
    first, last = parser_positions[0], parser_positions[-1]
    if first:
        leading = quote[:first]
        if not leading.isspace():
            return None
        edge_boundaries.append(
            dict(
                kind="leading_whitespace",
                source_start=ref.char_start,
                source_end=ref.char_start + first,
                source_whitespace=leading,
                native_text_boundary=native_offsets[0],
                before_pdfium_char_index=None,
                after_pdfium_char_index=glyphs[0]["index"],
            )
        )
    if last + 1 < len(quote):
        trailing = quote[last + 1 :]
        if not trailing.isspace():
            return None
        edge_boundaries.append(
            dict(
                kind="trailing_whitespace",
                source_start=ref.char_start + last + 1,
                source_end=ref.char_end,
                source_whitespace=trailing,
                native_text_boundary=native_offsets[-1] + 1,
                before_pdfium_char_index=glyphs[-1]["index"],
                after_pdfium_char_index=None,
            )
        )
    return dict(
        source_start=ref.char_start,
        source_end=ref.char_end,
        source_quote_sha256=sha256(quote.encode("utf-8")).hexdigest(),
        characters=characters,
        boundaries=boundaries,
        edge_boundaries=edge_boundaries,
        reversible=True,
    )


def _render_type_proof(native_page, glyphs):
    textpage = native_page.get_textpage()
    try:
        try:
            # Form bounds, transforms, group opacity and inherited clips cannot
            # be proved by flattening child objects. Only page-owned text can
            # use this shortcut; overlapping forms require the pixel reader.
            objects = list(native_page.get_objects(max_depth=1, textpage=textpage))
            owners = [
                ctypes.cast(
                    raw.FPDFText_GetTextObject(textpage, glyph["index"]), ctypes.c_void_p
                ).value
                for glyph in glyphs
            ]
        except Exception:
            return dict(status="pixel_required", reason="page_object_inventory_unavailable")
        if not all(owners):
            return dict(status="pixel_required", reason="quote_glyph_owner_unavailable")
        if len(objects) > 10000:
            return dict(status="pixel_required", reason="page_object_inventory_too_large")
        page_height = native_page.get_height()
        if any(
            not (0 <= g["bbox"][0] < g["bbox"][2] <= native_page.get_width())
            or not (0 <= g["bbox"][1] < g["bbox"][3] <= page_height)
            for g in glyphs
        ):
            return dict(status="pixel_required", reason="quote_glyph_outside_visible_page")
        visible_matches = [False] * len(glyphs)
        checked_objects = []
        for obj in objects:
            try:
                bounds = obj.get_bounds()
            except Exception:
                return dict(status="pixel_required", reason="page_object_geometry_unavailable")
            if (
                bounds is None
                or len(bounds) != 4
                or any(not math.isfinite(value) for value in bounds)
                or bounds[0] >= bounds[2]
                or bounds[1] >= bounds[3]
            ):
                # PDFium reports some zero-area text objects for spacing/control
                # glyphs. They paint no pixels and cannot cover an attested glyph.
                if (
                    obj.type == _TEXT_OBJECT
                    and bounds is not None
                    and len(bounds) == 4
                    and all(math.isfinite(value) for value in bounds)
                    and bounds[0] == bounds[2]
                    and bounds[1] == bounds[3]
                ):
                    continue
                return dict(status="pixel_required", reason="page_object_geometry_unavailable")
            matched = []
            for index, glyph in enumerate(glyphs):
                left, top, right, bottom = glyph["bbox"]
                glyph_box = (left, page_height - bottom, right, page_height - top)
                if _intersects(bounds, glyph_box):
                    matched.append(index)
            if not matched:
                continue
            if obj.type != _TEXT_OBJECT:
                return dict(
                    status="pixel_required",
                    reason="non_text_object_overlaps_quote",
                    object_type=int(obj.type),
                )
            object_id = ctypes.cast(obj.raw, ctypes.c_void_p).value
            if any(owners[index] != object_id for index in matched):
                return dict(status="pixel_required", reason="other_text_object_overlaps_quote")
            try:
                clip = raw.FPDFPageObj_GetClipPath(obj.raw)
                if not clip:
                    return dict(status="pixel_required", reason="text_clip_inventory_unavailable")
                # In pinned PDFium a valid object's clip returns -1 only when
                # HasRef() is false (no active clip). Zero paths can still mean
                # a TEXT clip; W/W* paths can contain holes or be empty. None
                # of these is proved by an enclosing bounding rectangle.
                if raw.FPDFClipPath_CountPaths(clip) != -1:
                    return dict(status="pixel_required", reason="active_clip_requires_pixels")
                if raw.FPDFPageObj_HasTransparency(obj.raw):
                    return dict(status="pixel_required", reason="text_transparency_requires_pixels")
                mode = raw.FPDFTextObj_GetTextRenderMode(obj.raw)
                object_text = obj.extract()
            except Exception:
                return dict(status="pixel_required", reason="text_object_visibility_unavailable")
            if mode not in _VISIBLE_TEXT_MODES:
                return dict(status="pixel_required", reason="text_object_not_painted")
            if not isinstance(object_text, str):
                return dict(status="pixel_required", reason="text_object_text_unavailable")
            colors = {}
            for name, getter in (
                ("fill", raw.FPDFPageObj_GetFillColor),
                ("stroke", raw.FPDFPageObj_GetStrokeColor),
            ):
                channels = [ctypes.c_uint() for _ in range(4)]
                try:
                    available = getter(obj.raw, *(ctypes.byref(channel) for channel in channels))
                except Exception:
                    available = False
                colors[name] = tuple(channel.value for channel in channels) if available else None
            active_colors = (
                (colors["fill"],)
                if mode == 0
                else (colors["stroke"],)
                if mode == 1
                else (colors["fill"], colors["stroke"])
            )
            if any(
                color is None or color[3] != 255 or max(color[:3]) > 232 for color in active_colors
            ):
                return dict(status="pixel_required", reason="text_paint_visibility_ambiguous")
            for index in matched:
                visible_matches[index] = True
            checked_objects.append(
                dict(
                    type=int(obj.type),
                    render_mode=int(mode),
                    fill_color=colors["fill"],
                    stroke_color=colors["stroke"],
                    text_sha256=sha256(object_text.encode("utf-8")).hexdigest(),
                    clipping="none",
                    opaque=True,
                )
            )
        if not all(visible_matches):
            return dict(
                status="pixel_required", reason="quote_glyph_not_bound_to_visible_text_object"
            )
        return dict(
            status="native_text",
            reason=None,
            visible_glyphs=len(visible_matches),
            visible_text_objects=len(checked_objects),
            object_receipts=checked_objects,
        )
    finally:
        textpage.close()


def _native_record(document, native, graph, block, ref, tenant_id, page_cache):
    if not _exact_source_ref(graph, block, ref, tenant_id):
        return dict(status="unresolved", reason="source_ref_mismatch")
    page, reason = _page_geometry_supported(document, native, block, ref)
    if reason:
        return dict(status="unresolved", reason=reason)
    if ref.page_num not in page_cache:
        page_cache[ref.page_num] = v3._native_page(native, ref.page_num)
    entries = page_cache[ref.page_num]
    if not entries:
        return dict(status="unresolved", reason="glyph_geometry_unresolved")
    candidate = block.candidates[block.winner]
    box = candidate.bbox
    with (
        closing(native[ref.page_num - 1]) as native_page,
        closing(native_page.get_textpage()) as textpage,
    ):
        native_text = textpage.get_text_bounded(
            box[0], page.height - box[3], box[2], page.height - box[1]
        )
    alignment = v3._canonical(ref.quote, native_text)
    if alignment is None:
        return dict(status="unresolved", reason="native_quote_or_sensitive_spacing_mismatch")
    # v3 intentionally requires a changed alpha-space to remain on one row.
    # v4 permits only a literal line-break discrepancy across adjacent rows;
    # _reversible_offset_map below proves that boundary against exact glyphs.
    glyphs = v3._quote_glyphs(entries, alignment["canonical_quote"], box, [])
    if not glyphs:
        return dict(status="unresolved", reason="clipped_ambiguous_or_cross_row_quote")
    if v3._annotation_blocker(page, [glyph["bbox"] for glyph in glyphs]):
        return dict(status="unresolved", reason="interactive_visibility_requires_review")
    normalization = dict(
        parser_quote=ref.quote,
        native_text=native_text,
        **alignment,
        glyphs=glyphs,
        physical_page=ref.page_num,
        bbox=list(box),
        source_sha256=graph.source_sha256,
    )
    offset_map = _reversible_offset_map(ref, normalization)
    if offset_map is None:
        return dict(status="unresolved", reason="reversible_offset_map_unresolved")
    with closing(native[ref.page_num - 1]) as native_page:
        render_type = _render_type_proof(native_page, glyphs)
    if render_type["status"] != "native_text":
        return dict(
            status="pixel_required",
            reason="pixel_confirmation_required",
            normalization=normalization,
            native_offset_map=offset_map,
            render_type_proof=render_type,
        )
    return dict(
        status="verified",
        reason=None,
        canonical_quote=alignment["canonical_quote"],
        normalization=normalization,
        native_offset_map=offset_map,
        render_type_proof=render_type,
    )


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    refs = tuple(refs)
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or len(source) > 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("CLAIM_SOURCE_MISMATCH")
    blocks = {block.source_id: block for block in graph.blocks}
    records, page_cache = [], {}
    pixel_refs = []
    with pdfplumber.open(io.BytesIO(source)) as document, pdfium.PdfDocument(source) as native:
        for ref in refs:
            record = dict(ref=asdict(ref), status="unresolved", reason="source_invalid")
            records.append(record)
            block = blocks.get(ref.source_id)
            if block is None:
                continue
            native_record = _native_record(
                document, native, graph, block, ref, tenant_id, page_cache
            )
            if native_record["status"] == "pixel_required":
                record.update(native_record)
                pixel_refs.append((len(records) - 1, ref))
            else:
                record.update(native_record)
    if pixel_refs:
        pixel_receipt = v3.attest_claim_spans(
            graph, source, tuple(ref for _, ref in pixel_refs), tenant_id=tenant_id
        )
        for (record_index, _), pixel_record in zip(
            pixel_refs, pixel_receipt["records"], strict=True
        ):
            record = records[record_index]
            render_type_proof = record.get("render_type_proof")
            native_offset_map = record.get("native_offset_map")
            record.clear()
            record.update(pixel_record)
            record["pixel_fallback"] = pixel_record
            if render_type_proof is not None:
                record["render_type_proof"] = render_type_proof
            if native_offset_map is not None:
                record["native_offset_map"] = native_offset_map
            if pixel_record["status"] != "verified":
                record["status"] = "unresolved"
                record["reason"] = pixel_record.get("reason") or "pixel_confirmation_unresolved"
    receipt = dict(
        schema=SCHEMA,
        policy=claim_source_policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        records=records,
        pixel_receipt_sha256=(pixel_receipt["artifact_sha256"] if pixel_refs else None),
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    return receipt


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    expected = attest_claim_spans(
        graph, source, strict.discovery_refs(discovery), tenant_id=tenant_id
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("CLAIM_SOURCE_V4_RECEIPT_MISMATCH")
    refs = tuple(
        replace(SourceRef(**record["ref"]), verification_state="verified")
        for record in expected["records"]
        if record["status"] == "verified"
    )
    existing = tuple(getattr(graph, "verified_spans", ()) or ())
    scoped = span_citations.span_verified_graph(graph, existing + refs, expected["artifact_sha256"])
    claims = []
    for claim in discovery.claims:
        checked = tuple(
            span_citations.verify_source_ref(ref, scoped, tenant_id=tenant_id)
            for ref in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=checked)
            if claim.source_quality == "unverified"
            and checked
            and all(ref.verification_state == "verified" for ref in checked)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped


def _lineage_values(receipt, record):
    ref = record.get("ref", {}) if isinstance(record, dict) else {}
    normalization = record.get("normalization", {}) if isinstance(record, dict) else {}
    glyphs = normalization.get("glyphs")
    return {
        "tenant_id": receipt.get("tenant_id"),
        "document_version_id": receipt.get("document_version_id"),
        "parse_manifest_id": receipt.get("parse_manifest_id"),
        "source_sha256": receipt.get("source_sha256"),
        "physical_page": ref.get("page_num"),
        "printed_page_label": ref.get("printed_page_label"),
        "raw_text_sha256": ref.get("raw_text_sha256"),
        "offsets": [ref.get("char_start"), ref.get("char_end")],
        "bbox": list(ref["bbox"]) if ref.get("bbox") is not None else None,
        "quote_sha256": sha256(ref["quote"].encode("utf-8")).hexdigest()
        if isinstance(ref.get("quote"), str)
        else None,
        "glyph_geometry_sha256": canonical_hash(
            [{key: glyph.get(key) for key in ("index", "char", "bbox")} for glyph in glyphs]
        )
        if isinstance(glyphs, list)
        else None,
    }


def compare_source_lineage(left_receipt, left_record, right_receipt, right_record):
    """Compare exact receipt lineage for diagnosis; this function never admits evidence."""
    left = _lineage_values(left_receipt, left_record)
    right = _lineage_values(right_receipt, right_record)
    required = (
        "tenant_id",
        "document_version_id",
        "parse_manifest_id",
        "source_sha256",
        "physical_page",
        "printed_page_label",
        "raw_text_sha256",
        "offsets",
        "bbox",
        "quote_sha256",
    )
    fields = {
        name: dict(left=left[name], right=right[name], equal=left[name] == right[name])
        for name in left
    }
    mismatches = [
        name
        for name in required
        if left[name] is None or right[name] is None or left[name] != right[name]
    ]
    if left["glyph_geometry_sha256"] is not None and right["glyph_geometry_sha256"] is not None:
        if left["glyph_geometry_sha256"] != right["glyph_geometry_sha256"]:
            mismatches.append("glyph_geometry_sha256")
    return dict(
        status="identical" if not mismatches else "held",
        diagnostic_only=True,
        fields=fields,
        mismatches=mismatches,
    )
