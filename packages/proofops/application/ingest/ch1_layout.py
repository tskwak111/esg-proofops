"""Bounded printed-label proposals. Geometry associates candidates, not facts.

Layout/series hints may come from a vision extractor or a reviewed selection.
Numbers always come from OCR words. A missing data label is never interpolated.
"""

import math
import re

NUMBER = re.compile(r"[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|％)?")
YEAR = re.compile(r"(?:19|20)\d{2}(?:년)?")


def _field(word):
    return dict(quote=word["text"], word_ids=[word["id"]])


def _inside(word, box):
    b = word["bbox"]
    return box[0] <= b[0] < b[2] <= box[2] and box[1] <= b[1] < b[3] <= box[3]


def _resolve(field, words):
    if not isinstance(field, dict):
        return []
    ids = field.get("word_ids")
    if ids is not None:
        found = [next((w for w in words if w["id"] == i), None) for i in ids]
        return found if all(found) and " ".join(w["text"] for w in found) == field["quote"] else []
    matches = [w for w in words if w["text"] == field.get("quote")]
    return matches if len(matches) == 1 else []


def propose(layout, words, page_size):
    """Recover numeric labels in one local chart/table, with unresolved ties.

    No bbox is required: exact OCR anchors can bound the region instead. Ambiguous
    anchors return no observations, rather than expanding to the entire page.
    """
    kind, alignment = layout.get("kind"), layout.get("alignment")
    if kind not in {"bar", "line", "pie", "image_table"} or alignment not in {
        "columns",
        "rows",
        "single",
    }:
        raise ValueError("CH1_LAYOUT_INVALID")
    box = layout.get("bbox")
    if box is None:
        anchors = layout.get("anchors", [])
        matched = [_resolve(anchor, words) for anchor in anchors]
        if len(anchors) < 2 or not all(matched):
            return dict(
                id=layout["id"],
                page=layout["page"],
                kind=kind,
                bbox=None,
                observations=[],
                reason="region_anchors_unresolved",
            )
        selected = [w for match in matched for w in match]
        box = [
            min(w["bbox"][0] for w in selected),
            min(w["bbox"][1] for w in selected),
            max(w["bbox"][2] for w in selected),
            max(w["bbox"][3] for w in selected),
        ]
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in box)
        or not 0 <= box[0] < box[2] <= page_size[0]
        or not 0 <= box[1] < box[3] <= page_size[1]
    ):
        raise ValueError("CH1_REGION_GEOMETRY_INVALID")
    local = [w for w in words if _inside(w, box)]
    years = [w for w in local if YEAR.fullmatch(w["text"])]
    series = layout.get("series", [])
    if not isinstance(series, list) or not 1 <= len(series) <= 16:
        raise ValueError("CH1_SERIES_INVALID")
    excluded = set(layout.get("axis_word_ids", []))
    for s in series:
        for role in ("label", "unit"):
            excluded.update(w["id"] for w in _resolve(s.get(role), local))
    points = []
    for word in local:
        text = word["text"]
        if not NUMBER.fullmatch(text) or YEAR.fullmatch(text) or word["id"] in excluded:
            continue
        percent = text.endswith(("%", "％"))
        compatible = [s for s in series if s.get("format") == ("percent" if percent else "number")]
        # Distinct same-unit series require a semantic/colour reader. Do not
        # choose a legend by order or by nearest colour-looking position.
        series_hint = compatible[0] if len(compatible) == 1 else {}
        year = None
        if alignment != "single":
            axis = 0 if alignment == "columns" else 1
            b = word["bbox"]
            center = (b[axis] + b[axis + 2]) / 2
            matching = [y for y in years if y["bbox"][axis] <= center <= y["bbox"][axis + 2]]
            if len(matching) == 1:
                year = _field(matching[0])
        else:
            year = layout.get("year")
        if percent:
            unit = _field(word) | dict(span=[len(text) - 1, len(text)])
        else:
            unit = series_hint.get("unit")
        # A grid may have multiple rows in the same series; use a literal row
        # label only when exactly one supplied label shares that value's row.
        label = series_hint.get("label")
        labels = layout.get("row_labels", [])
        if labels:
            matching_labels = []
            for candidate in labels:
                located = _resolve(candidate, local)
                if located and all(
                    min(w["bbox"][3], word["bbox"][3]) - max(w["bbox"][1], word["bbox"][1])
                    >= 0.5 * min(w["bbox"][3] - w["bbox"][1], word["bbox"][3] - word["bbox"][1])
                    for w in located
                ):
                    matching_labels.append(candidate)
            label = matching_labels[0] if len(matching_labels) == 1 else None
        points.append(
            dict(
                id=f"word-{word['id']}",
                basis="printed",
                value=_field(word),
                unit=unit,
                year=year,
                series=label,
            )
        )
    return dict(
        id=layout["id"],
        page=layout["page"],
        kind=kind,
        bbox=box,
        observations=points,
        coordinate_origin="OCR-anchor-union" if layout.get("bbox") is None else "region-proposal",
    )
