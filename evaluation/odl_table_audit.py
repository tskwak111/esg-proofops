"""Detect lost backend cell geometry and ambiguous table occupancy; never repair by guess."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

from evaluation.odl_compare import normalize
from evaluation.odl_pilot import write_json


def text_of(node):
    if "content" in node:
        return node["content"]
    return "\n".join(text_of(child) for child in node.get("kids", []))


def valid_box(box):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(type(x) in (int, float) and math.isfinite(x) for x in box)
        and box[0] < box[2]
        and box[1] < box[3]
    )


def bottom_left(box, height):
    if not isinstance(box, dict):
        return None
    values = [box.get(key) for key in ("l", "t", "r", "b")]
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        return None
    left, top, right, bottom = values
    candidate = None
    if box.get("coord_origin") == "TOPLEFT":
        candidate = [left, height - bottom, right, height - top]
    elif box.get("coord_origin") == "BOTTOMLEFT":
        candidate = [left, bottom, right, top]
    return candidate if valid_box(candidate) else None


def audit(raw, backend):
    tables = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "table":
                tables.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(raw)
    results = []
    for table in tables:
        page = table["page number"]
        height = backend["pages"][str(page)]["size"]["height"]
        matches = []
        for original in backend.get("tables", []):
            prov = original.get("prov", [])
            if len(prov) != 1 or prov[0]["page_no"] != page:
                continue
            box = bottom_left(prov[0]["bbox"], height)
            if box and all(
                abs(a - b) <= 1 for a, b in zip(box, table["bounding box"], strict=True)
            ):
                matches.append(original)
        if len(matches) != 1:
            results.append(
                {
                    "table_id": table.get("id"),
                    "page": page,
                    "status": "blocked",
                    "reason": "backend_table_not_unique",
                }
            )
            continue
        source_cells = matches[0]["data"]["table_cells"]
        occupied = defaultdict(list)
        cells = []
        for row in table["rows"]:
            for cell in row["cells"]:
                r, c = cell["row number"], cell["column number"]
                for ri in range(r, r + cell.get("row span", 1)):
                    for ci in range(c, c + cell.get("column span", 1)):
                        occupied[(ri, ci)].append((r, c))
                text = text_of(cell)
                source = [
                    item
                    for item in source_cells
                    if item["start_row_offset_idx"] == r - 1
                    and item["start_col_offset_idx"] == c - 1
                    and normalize(item["text"]) == normalize(text)
                ]
                original_box = (
                    bottom_left(source[0].get("bbox"), height) if len(source) == 1 else None
                )
                output_box = cell.get("bounding box")
                if not valid_box(output_box):
                    output_box = None
                changed = (
                    original_box is not None
                    and output_box is not None
                    and any(abs(a - b) > 1 for a, b in zip(original_box, output_box, strict=True))
                )
                cells.append(
                    {
                        "row": r,
                        "column": c,
                        "text": text,
                        "odl_bbox_bottom_left": output_box,
                        "backend_bbox_bottom_left": original_box,
                        "backend_geometry_preserved": (
                            original_box is not None and output_box is not None and not changed
                        ),
                        "control_characters": sorted(
                            {ord(ch) for ch in text if ord(ch) < 32 and ch not in "\t\r\n"}
                        ),
                    }
                )
        overlaps = [
            {"row": slot[0], "column": slot[1], "owners": owners}
            for slot, owners in occupied.items()
            if len(owners) > 1
        ]
        results.append(
            {
                "table_id": table.get("id"),
                "page": page,
                "cells": cells,
                "overlapping_slots": overlaps,
                "cells_without_preserved_backend_geometry": sum(
                    not cell["backend_geometry_preserved"] for cell in cells
                ),
                "status": "requires_source_verification",
                "semantic_binding": "not_approved",
            }
        )
    return {
        "schema": "odl-table-audit-v1",
        "tables": results,
        "note": "No model boxes, merged headers, or text were silently corrected or approved.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment", type=Path, required=True, help="Hybrid supervisor directory"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads((args.experiment / "backend-receipt.json").read_bytes())
    raw_backend = (args.experiment / "docling-document.json").read_bytes()
    report = json.loads((args.experiment / "client/report.json").read_bytes())
    if (
        receipt["status"] != "success"
        or report["status"] != "succeeded"
        or receipt["source_sha256"] != report["source_sha256"]
        or sha256(raw_backend).hexdigest() != receipt["document_sha256"]
    ):
        parser.error("verified backend success required")
    if args.output.exists():
        parser.error("output already exists")
    result = audit(
        json.loads((args.experiment / "client/raw/source.json").read_bytes()),
        json.loads(raw_backend),
    )
    result["source_sha256"] = receipt["source_sha256"]
    write_json(args.output, result)
    print(
        json.dumps(
            [
                {key: value for key, value in table.items() if key != "cells"}
                for table in result["tables"]
            ],
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
