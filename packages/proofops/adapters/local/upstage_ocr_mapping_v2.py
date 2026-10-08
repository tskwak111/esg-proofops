"""Text-independent word ownership and geometric reading order for page OCR.

The six-pixel floor follows the existing Apple crop margin and O1 image review.
Height scaling is bounded, so large headings cannot borrow neighboring text.
No expected/native text, confidence score or evaluation identity enters mapping.
"""

from __future__ import annotations

import math
from statistics import median

from proofops.adapters.local.upstage_ocr_page import TOL, _bounds, _number, _overlap
from proofops.domain.provenance import canonical_hash

MAPPING_POLICY = dict(
    algorithm="centroid-polygon-ownership-geometric-lines-v2",
    margin_min_pt=2.0,  # six pixels at the pinned 216dpi
    margin_height_ratio=0.2,
    margin_max_pt=4.0,
    min_polygon_overlap=0.8,
    max_edge_tilt_degrees=5.0,
    edge_quantization_pt=1 / 3,  # one provider pixel at 216dpi, also for tiny bullets
    max_word_overlap_ratio=0.2,
    min_line_overlap_ratio=0.5,
    max_inline_gap_height_ratio=3.0,
    tolerance_pt=TOL,
)


def mapping_sha256():
    return canonical_hash(MAPPING_POLICY)


def _area(poly):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def _clipped_area(poly, box):
    """Convex polygon/axis-aligned rectangle intersection, in PDF points."""
    clipped = poly
    for axis, edge, direction in ((0, box[0], 1), (0, box[2], -1), (1, box[1], 1), (1, box[3], -1)):
        output = []
        for a, b in zip(clipped, clipped[1:] + clipped[:1]):
            ain = direction * (a[axis] - edge) >= 0
            bin = direction * (b[axis] - edge) >= 0
            if ain != bin:
                t = (edge - a[axis]) / (b[axis] - a[axis])
                point = [a[i] + t * (b[i] - a[i]) for i in (0, 1)]
                point[axis] = edge
                output.append(point)
            if bin:
                output.append(b)
        clipped = output
        if not clipped:
            return 0.0
    return _area(clipped)


def _centroid(poly):
    cross = [a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])]
    return [
        sum((a[i] + b[i]) * c for a, b, c in zip(poly, poly[1:] + poly[:1], cross))
        / (3 * sum(cross))
        for i in (0, 1)
    ]


def _eligible(poly, bounds, box):
    height = bounds[3] - bounds[1]
    margin = min(
        MAPPING_POLICY["margin_max_pt"],
        max(MAPPING_POLICY["margin_min_pt"], height * MAPPING_POLICY["margin_height_ratio"]),
    )
    expanded = [box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin]
    center = _centroid(poly)
    return (
        expanded[0] <= center[0] <= expanded[2]
        and expanded[1] <= center[1] <= expanded[3]
        and _clipped_area(poly, expanded) / _area(poly) >= MAPPING_POLICY["min_polygon_overlap"]
    )


def _tilted(poly):
    limit = math.tan(math.radians(MAPPING_POLICY["max_edge_tilt_degrees"]))
    for a, b, axis in ((0, 1, 0), (3, 2, 0), (0, 3, 1), (1, 2, 1)):
        along = poly[b][axis] - poly[a][axis]
        across = abs(poly[b][1 - axis] - poly[a][1 - axis])
        if along <= 0 or across > limit * along + MAPPING_POLICY["edge_quantization_pt"]:
            return True
    return False


def map_words(response, manifest, box, *, competing_boxes=()):
    chosen = []

    def hold(reason):
        return dict(status="unresolved", reason=reason, word_ids=[w["id"] for w in chosen])

    def valid_box(b):
        return len(b) == 4 and all(_number(x) for x in b) and b[0] < b[2] and b[1] < b[3]

    if not valid_box(box):
        return hold("ocr_invalid_box")
    peers = {tuple(b) for b in competing_boxes if tuple(b) != tuple(box)}
    if any(not valid_box(b) for b in peers):
        return hold("ocr_invalid_box")
    for w in response["words"]:
        poly = [
            [
                p[0] * manifest["width_pt"] / response["width"],
                p[1] * manifest["height_pt"] / response["height"],
            ]
            for p in w["polygon"]
        ]
        bounds = _bounds(poly)
        if not _eligible(poly, bounds, box):
            if _overlap(bounds, box) and not any(_eligible(poly, bounds, b) for b in peers):
                return hold("ocr_boundary_ambiguous")
            continue
        if any(_eligible(poly, bounds, b) for b in peers):
            return hold("ocr_block_overlap_ambiguous")
        if not w["text"]:
            return hold("ocr_unrecognized_word")
        if _tilted(poly):
            return hold("ocr_word_rotation_ambiguous")
        for other in chosen:
            overlap = _clipped_area(poly, other["bbox"])
            if (
                overlap / min(_area(poly), _area(other["pdf_polygon"]))
                > MAPPING_POLICY["max_word_overlap_ratio"]
            ):
                return hold("ocr_word_overlap_ambiguous")
        chosen.append(dict(**w, bbox=bounds, pdf_polygon=poly))
    if not chosen:
        return hold("ocr_no_words")
    lines = []
    for w in sorted(chosen, key=lambda w: (w["bbox"][1], w["bbox"][0], w["id"])):
        box_w = w["bbox"]
        matching = [
            line
            for line in lines
            if all(
                min(v["bbox"][3], box_w[3]) - max(v["bbox"][1], box_w[1])
                >= MAPPING_POLICY["min_line_overlap_ratio"]
                * min(v["bbox"][3] - v["bbox"][1], box_w[3] - box_w[1])
                for v in line
            )
        ]
        if len(matching) > 1:
            return hold("ocr_order_ambiguous")
        if matching:
            matching[0].append(w)
        else:
            lines.append([w])
    ordered = []
    height = median(w["bbox"][3] - w["bbox"][1] for w in chosen)
    for line in sorted(lines, key=lambda line: min(w["bbox"][1] for w in line)):
        line.sort(key=lambda w: (w["bbox"][0], w["id"]))
        if any(
            b["bbox"][0] - a["bbox"][2] > MAPPING_POLICY["max_inline_gap_height_ratio"] * height
            for a, b in zip(line, line[1:])
        ):
            return hold("ocr_column_order_ambiguous")
        ordered.extend(line)
    return dict(
        status="read",
        text=" ".join(w["text"] for w in ordered),
        word_ids=[w["id"] for w in ordered],
        words=ordered,
        coordinate_transform=dict(
            x=manifest["width_pt"] / response["width"], y=manifest["height_pt"] / response["height"]
        ),
    )
