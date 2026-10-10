"""Opt-in SV1: literal PDF-native quotes plus quote-local annotation visibility.

Parser refs/offsets remain immutable. ``canonical_quote`` is the attested native
quote; ``normalization`` maps it back to the parser quote and exact PDF glyphs.
No paragraph promotion, OCR character folding, paid reader, or prior revision edit.
"""

import io
import math
import re
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
from proofops.adapters.local import glyph_alignment_verification as baseline
from proofops.adapters.local.source_verification import _rendered_text
from proofops.application.evidence import span_citations
from proofops.application.evidence.citations import verify_source_ref
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "claim-source-v3"
# Existing run envelope; exact profile + complete policy select this reader.
POLICY_SCHEMA = "claim_span_typography_policy_v1"
SCHEMA = "claim_source_attestation_v3"
_ELIGIBLE = {"rendered_quote_unresolved", "interactive_visibility_requires_review", "text_mismatch"}
# Only alphabetic spacing can change. Protect unit tokens too, including suffixes.
_UNITS = re.compile(
    r"(?i)(?:tCO2e|CO2e|CO2|kWh|MWh|GWh|Wh|MW|GW|kW|kg|mg|tonnes|tons|ton|ha|km|m3|m2|ppm|ppb|퍼센트|킬로그램|킬로와트|톤|원|억|년|t|g|L|m)(?![A-Za-z])"
)


# A quantity protects its following unit token even if that unit is not listed.
# This deliberately errs toward review for a number followed by ordinary prose.
_QUANTITY = re.compile(r"[+−-]?\d+(?:[,.]\d+)*\s*[^\W\d_][\w/²³µμ°]*")


def claim_source_policy():
    return dict(
        schema=POLICY_SCHEMA,
        profile=PROFILE,
        base=baseline.claim_source_policy(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        pdfium_version=version("pypdfium2"),
        pdfplumber_version=version("pdfplumber"),
    )


def _plain(text):
    # Deliberately no NFC, ligature, punctuation or OCR character substitutions.
    return " ".join(text.split())


def _compact_map(text):
    positions = [i for i, c in enumerate(text) if not c.isspace()]
    return "".join(text[i] for i in positions), positions


def _canonical(parser_quote, native_text):
    parser, native = _plain(parser_quote), _plain(native_text)
    compact, pmap = _compact_map(parser)
    whole, nmap = _compact_map(native)
    start = whole.find(compact)
    if not compact or start < 0 or whole.find(compact, start + 1) >= 0:
        return None
    quote = native[nmap[start] : nmap[start + len(compact) - 1] + 1]
    if not strict._unique_quote(native, quote):
        return None
    _, qmap = _compact_map(quote)
    changed = []
    sensitive = [
        (m.start(), m.end()) for pattern in (_UNITS, _QUANTITY) for m in pattern.finditer(quote)
    ]
    for i in range(1, len(compact)):
        pspace = parser[pmap[i - 1] + 1 : pmap[i]]
        nspace = quote[qmap[i - 1] + 1 : qmap[i]]
        if pspace == nspace:
            continue
        if (
            not compact[i - 1].isalpha()
            or not compact[i].isalpha()
            or any(a <= qmap[i - 1] < b or a <= qmap[i] < b for a, b in sensitive)
        ):
            return None
        changed.append(i)
    return dict(
        canonical_quote=quote,
        changed_boundaries=changed,
        canonical_to_parser=_compact_map(parser_quote)[1],
        native_nonspace_offsets=_compact_map(native_text)[1][start : start + len(compact)],
        canonical_nonspace_offsets=qmap,
    )


def _intersects(a, b):
    return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]


def _annotation_blocker(page, boxes):
    for annotation in page.annots or []:
        data = annotation.get("data", {})
        kind = getattr(resolve1(data.get("Subtype")), "name", None)
        # A Link without AP paints no appearance. Widgets are guarded even
        # without AP: viewer-generated field appearances can conceal text.
        if kind == "Link" and "AP" not in data:
            continue
        if kind != "Widget" and "AP" not in data:
            continue
        bounds = [annotation.get(k) for k in ("x0", "top", "x1", "bottom")]
        if (
            any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2]
            or bounds[1] >= bounds[3]
        ):
            return True
        if any(_intersects(bounds, box) for box in boxes):
            return True
    return False


def _native_page(native, page_number):
    with closing(native[page_number - 1]) as page, closing(page.get_textpage()) as textpage:
        count = textpage.count_chars()
        if not 0 < count <= 20000:
            return None
        entries = []
        for i in range(count):
            char = chr(raw.FPDFText_GetUnicode(textpage, i))
            if char.isspace() or char == "\0":
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=False)
            entries.append(
                dict(
                    index=i,
                    char=char,
                    bbox=[left, page.get_height() - top, right, page.get_height() - bottom],
                )
            )
        return entries


def _quote_glyphs(entries, quote, box, changed):
    compact = "".join(quote.split())
    text = "".join(e["char"] for e in entries)
    matches, start = [], 0
    while compact and (start := text.find(compact, start)) >= 0:
        glyphs = entries[start : start + len(compact)]
        if all(
            all(math.isfinite(v) for v in e["bbox"])
            and box[0] - 0.001 <= e["bbox"][0] < e["bbox"][2] <= box[2] + 0.001
            and box[1] - 0.001 <= e["bbox"][1] < e["bbox"][3] <= box[3] + 0.001
            for e in glyphs
        ):
            matches.append(glyphs)
        start += 1
    if len(matches) != 1:
        return None
    glyphs = matches[0]
    for i in changed:
        a, b = glyphs[i - 1]["bbox"], glyphs[i]["bbox"]
        # A changed space may not splice different physical rows or reverse text.
        if b[0] < a[0] or min(a[3], b[3]) <= max(a[1], b[1]):
            return None
    return glyphs


def _recover(document, native, block, ref, page_cache, render_cache, source_sha256):
    candidate = block.candidates[block.winner]
    box, geometry = candidate.bbox, candidate.geometry
    if not 1 <= ref.page_num <= len(document.pages):
        return dict(status="unresolved", reason="geometry_unsupported")
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
        return dict(status="unresolved", reason="geometry_unsupported")
    form = resolve1(document.doc.catalog.get("AcroForm"))
    if "OCProperties" in document.doc.catalog or (
        isinstance(form, dict) and any(k in form for k in ("XFA", "NeedsRendering"))
    ):
        return dict(status="unresolved", reason="interactive_visibility_requires_review")
    if ref.page_num not in page_cache:
        page_cache[ref.page_num] = _native_page(native, ref.page_num)
    entries = page_cache[ref.page_num]
    if not entries:
        return dict(status="unresolved", reason="glyph_geometry_unresolved")
    with closing(native[ref.page_num - 1]) as np, closing(np.get_textpage()) as tp:
        text = tp.get_text_bounded(box[0], page.height - box[3], box[2], page.height - box[1])
    alignment = _canonical(ref.quote, text)
    if alignment is None:
        return dict(
            status="unresolved",
            reason="native_quote_or_sensitive_spacing_mismatch",
            native_text=text,
        )
    quote = alignment["canonical_quote"]
    glyphs = _quote_glyphs(entries, quote, box, alignment["changed_boundaries"])
    if not glyphs:
        return dict(
            status="unresolved", reason="clipped_ambiguous_or_cross_row_quote", native_text=text
        )
    if _annotation_blocker(page, [e["bbox"] for e in glyphs]):
        return dict(
            status="unresolved", reason="interactive_visibility_requires_review", native_text=text
        )
    key = (ref.page_num, tuple(box))
    if key not in render_cache:
        render_cache[key] = [_rendered_text(page, box), _rendered_text(page, box, padding_px=6)]
    attempts = render_cache[key]
    matching = [
        r
        for r in attempts
        if r.get("status") == "read" and strict._unique_quote(_plain(r.get("text", "")), quote)
    ]
    proof = dict(
        parser_quote=ref.quote,
        native_text=text,
        **alignment,
        glyphs=glyphs,
        physical_page=ref.page_num,
        bbox=list(box),
        source_sha256=source_sha256,
        rendered_attempts=attempts,
    )
    if not matching:
        return dict(status="unresolved", reason="rendered_quote_unresolved", normalization=proof)
    proof["rendered_read_sha256"] = canonical_hash(matching[0])
    return dict(status="verified", reason=None, canonical_quote=quote, normalization=proof)


def _extend_receipt(receipt, graph, source, refs, *, tenant_id):
    """Internal saved-replay hook; caller must authenticate the baseline artifact.

    Production only passes a baseline freshly recomputed by attest_claim_spans.
    Every newly admitted ref is independently checked against graph + PDF + pixels.
    """
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or len(source) > 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("CLAIM_SOURCE_MISMATCH")
    blocks = {b.source_id: b for b in graph.blocks}
    records, page_cache, render_cache = [], {}, {}
    with pdfplumber.open(io.BytesIO(source)) as document, pdfium.PdfDocument(source) as native:
        for old, ref in zip(receipt["records"], refs, strict=True):
            if canonical_hash(old["ref"]) != canonical_hash(asdict(ref)):
                raise ValueError("CLAIM_SOURCE_REF_MISMATCH")
            record = dict(old)
            records.append(record)
            if old["status"] == "verified":
                page = document.pages[ref.page_num - 1]
                if ref.page_num not in page_cache:
                    page_cache[ref.page_num] = _native_page(native, ref.page_num)
                glyphs = _quote_glyphs(page_cache[ref.page_num] or [], ref.quote, ref.bbox, [])
                boxes = [g["bbox"] for g in glyphs] if glyphs else [ref.bbox]
                if _annotation_blocker(page, boxes):
                    record.update(
                        status="unresolved", reason="interactive_visibility_requires_review"
                    )
                continue
            if old["reason"] not in _ELIGIBLE:
                continue
            block = blocks.get(ref.source_id)
            if (
                block is None
                or block.kind != "paragraph"
                or block.quality not in {"verified", "unverified"}
                or block.winner is None
            ):
                continue
            checked = replace(
                graph,
                blocks=tuple(
                    replace(b, quality="verified") if b == block else b for b in graph.blocks
                ),
            )
            if (
                verify_source_ref(ref, checked, tenant_id=tenant_id).verification_state
                != "verified"
            ):
                continue
            result = _recover(
                document, native, block, ref, page_cache, render_cache, graph.source_sha256
            )
            record.update(result)
    result = dict(
        schema=SCHEMA,
        policy=claim_source_policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        baseline_receipt=receipt,
        records=records,
        readings=receipt["readings"],
    )
    result["artifact_sha256"] = canonical_hash(result)
    return result


def attest_claim_spans(graph, source, refs, *, tenant_id):
    refs = tuple(refs)
    receipt = baseline.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
    return _extend_receipt(receipt, graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    expected = attest_claim_spans(
        graph, source, strict.discovery_refs(discovery), tenant_id=tenant_id
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("CLAIM_SOURCE_V3_RECEIPT_MISMATCH")
    refs = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
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
