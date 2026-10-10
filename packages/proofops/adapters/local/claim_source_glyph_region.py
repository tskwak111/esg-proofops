"""HF1 quote-local verification regions; immutable parser refs remain unchanged."""

import math
from contextlib import closing
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from proofops.adapters.local import claim_source_verification_v3 as sv1
from proofops.adapters.local.evidence_source_verification_v1 import _prose_layout
from proofops.domain.provenance import canonical_hash

VERIFICATION_OWNER = ContextVar("hf1_verification_owner", default=None)


def policy():
    return dict(
        profile="claim-glyph-region-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        source="unique-literal-glyph-sequence",
        expansion="top-intersecting-glyphs-only",
        guards="literal-quantity-row-column-annotation-pixels",
    )


def glyph_region(entries, quote, original, changed):
    """No tolerance widening: every glyph must already intersect its parser region."""
    text = "".join(e["char"] for e in entries)
    compact = "".join(quote.split())
    matches, start = [], 0
    while compact and (start := text.find(compact, start)) >= 0:
        glyphs = entries[start : start + len(compact)]
        if all(
            all(math.isfinite(v) for v in g["bbox"])
            and g["bbox"][0] < g["bbox"][2]
            and g["bbox"][1] < g["bbox"][3]
            and original[0] - 0.001 <= g["bbox"][0]
            and g["bbox"][2] <= original[2] + 0.001
            and g["bbox"][3] <= original[3] + 0.001
            and sv1._intersects(g["bbox"], original)
            for g in glyphs
        ):
            matches.append(glyphs)
        start += 1
    if len(matches) != 1:
        return None
    glyphs = matches[0]
    height = max(g["bbox"][3] - g["bbox"][1] for g in glyphs)
    for a, b in zip(glyphs, glyphs[1:]):
        x, y = a["bbox"], b["bbox"]
        if min(x[3], y[3]) > max(x[1], y[1]):
            if y[0] < x[0] - 0.001 or y[0] - x[2] > 2 * height:
                return None
        elif y[1] < x[1] or y[1] - x[3] > 2 * height:
            return None
    region = [
        min(original[0], *(g["bbox"][0] for g in glyphs)),
        min(original[1], *(g["bbox"][1] for g in glyphs)),
        max(original[2], *(g["bbox"][2] for g in glyphs)),
        max(original[3], *(g["bbox"][3] for g in glyphs)),
    ]
    if not sv1._quote_glyphs(entries, quote, region, changed):
        return None
    selected = {g["index"] for g in glyphs}
    if any(
        e["index"] not in selected
        and sv1._intersects(e["bbox"], region)
        and not sv1._intersects(e["bbox"], original)
        for e in entries
    ):
        return None
    return region, glyphs


def recover(document, native, block, ref, page_cache, render_cache, source_sha256, *, literal):
    original = literal._recover(
        document, native, block, ref, page_cache, render_cache, source_sha256
    )
    if original.get("reason") != "clipped_ambiguous_or_cross_row_quote":
        return original
    candidate = block.candidates[block.winner]
    box = candidate.bbox
    page = document.pages[ref.page_num - 1]
    with closing(native[ref.page_num - 1]) as np, closing(np.get_textpage()) as tp:
        text = tp.get_text_bounded(box[0], page.height - box[3], box[2], page.height - box[1])
    alignment = literal._canonical(ref.quote, text)
    if alignment is None:
        return original
    found = glyph_region(
        page_cache[ref.page_num], alignment["canonical_quote"], box, alignment["changed_boundaries"]
    )
    if found is None:
        return original
    region, glyphs = found
    if not (0 <= region[0] < region[2] <= page.width and 0 <= region[1] < region[3] <= page.height):
        return original
    reason = _prose_layout(page, region, glyphs)
    if reason:
        return dict(status="unresolved", reason=reason, native_text=text)
    # An ephemeral reader view, never a new graph candidate or a mutated SourceRef.
    view = SimpleNamespace(
        winner=0,
        candidates=(
            SimpleNamespace(bbox=region, geometry=candidate.geometry, has_invalid_geometry=False),
        ),
    )
    token = VERIFICATION_OWNER.set(tuple(box))
    try:
        result = literal._recover(
            document, native, view, ref, page_cache, render_cache, source_sha256
        )
    finally:
        VERIFICATION_OWNER.reset(token)
    if "normalization" in result:
        result["normalization"].update(
            original_bbox=list(box), verification_region_policy_sha256=canonical_hash(policy())
        )
    return result
