"""Exact native cell grounding in an Upstage-declared grid; no numeric repair."""

from proofops.adapters.parsing.gemini_vision import _ground, compact
from proofops.application.ingest.pb1_tables import NUMERIC, UNIT


def ground_cells(cells, words, box, *, chars=()):
    if box is None:
        return [None] * len(cells)
    native = [
        w
        for w in words
        if box[0] - 2 <= w["x0"]
        and w["x1"] <= box[2] + 2
        and box[1] - 2 <= w["top"]
        and w["bottom"] <= box[3] + 2
    ]
    found = [_ground(c["text"], native, box)[0] for c in cells]
    # Only already literal-matched peer geometry supplies row/column constraints.
    for _ in range(2):
        for i, cell in enumerate(cells):
            if found[i] is not None or not cell["text"].strip():
                continue
            rows = [
                b
                for c, b in zip(cells, found, strict=True)
                if b is not None
                and c["row"] == cell["row"]
                and c["row_span"] == cell["row_span"] == 1
            ]
            cols = [
                b
                for c, b in zip(cells, found, strict=True)
                if b is not None
                and c["column"] == cell["column"]
                and c["column_span"] == cell["column_span"] == 1
            ]
            if not rows:
                continue
            left = [
                (c, b)
                for c, b in zip(cells, found, strict=True)
                if b is not None and c["column"] + c["column_span"] <= cell["column"]
            ]
            right = [
                (c, b)
                for c, b in zip(cells, found, strict=True)
                if b is not None and c["column"] >= cell["column"] + cell["column_span"]
            ]
            if not left or not right:
                continue
            lc = max(c["column"] + c["column_span"] for c, b in left)
            rc = min(c["column"] for c, b in right)
            left = [(c, b) for c, b in left if c["column"] + c["column_span"] == lc]
            right = [(c, b) for c, b in right if c["column"] == rc]
            # Header glyph widths are not cell boundaries. Use neighbour column
            # centres; exact literal matching below still decides admission.
            left_box = min(left, key=lambda pair: pair[0]["row"])[1]
            right_box = min(right, key=lambda pair: pair[0]["row"])[1]
            centre = (
                sum((b[0] + b[2]) / 2 for b in cols) / len(cols)
                if cols
                else (left_box[2] + right_box[0]) / 2
            )
            x0 = ((left_box[0] + left_box[2]) / 2 + centre) / 2
            x1 = (centre + (right_box[0] + right_box[2]) / 2) / 2
            y0, y1 = min(b[1] for b in rows), max(b[3] for b in rows)
            bounded = [
                w
                for w in native
                if y0 - 2 <= w["top"]
                and w["bottom"] <= y1 + 2
                and x0 - 2 <= w["x0"]
                and w["x1"] <= x1 + 2
            ]
            found[i] = _ground(cell["text"], bounded, box)[0]
            if found[i] is None and UNIT.search(cell["text"]):
                glyphs = [
                    c
                    for c in chars
                    if x0 - 1 <= c["x0"]
                    and c["x1"] <= x1 + 1
                    and y0 - 2 <= c["top"]
                    and c["bottom"] <= y1 + 2
                ]
                literal = "".join(c["text"] for c in sorted(glyphs, key=lambda c: c["x0"]))
                if glyphs and compact(literal) == compact(cell["text"]):
                    found[i] = (
                        min(c["x0"] for c in glyphs),
                        min(c["top"] for c in glyphs),
                        max(c["x1"] for c in glyphs),
                        max(c["bottom"] for c in glyphs),
                    )
    for i, (cell, bounds) in enumerate(zip(cells, found, strict=True)):
        if bounds is None or not NUMERIC.fullmatch(cell["text"].strip()):
            continue
        digits = [
            c
            for c in chars
            if c["text"].isdigit()
            and bounds[0] - 0.1 <= c["x0"]
            and c["x1"] <= bounds[2] + 0.1
            and c["bottom"] > bounds[1]
            and c["top"] < bounds[3]
        ]
        if digits:
            size = max(c["size"] for c in digits)
            baseline = max(c["bottom"] for c in digits if c["size"] == size)
            if any(c["size"] < size - 0.01 and c["bottom"] < baseline - 0.01 for c in digits):
                found[i] = None  # raised footnote digit stays context, never a quantity digit
    return found
