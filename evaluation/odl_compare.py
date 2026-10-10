"""Compare fixed source quote anchors without approving semantic attribution."""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

from evaluation.odl_pilot import raw_nodes, write_json


def normalize(text):
    return "".join(unicodedata.normalize("NFC", text).split())


def anchor_matches(nodes, anchors):
    rows = []
    for case in anchors["cases"]:
        matches = []
        for quote in case["quotes"]:
            found = [
                node
                for node in nodes
                if node["page"] == case["page"] and normalize(quote) in normalize(node["text"])
            ]
            matches.append(
                {
                    "quote": quote,
                    "text_found": bool(found),
                    "located": any(node["bbox"] is not None for node in found),
                    "hits": [
                        {"node_id": node["id"], "bbox": node["bbox"], "text": node["text"]}
                        for node in found
                    ],
                }
            )
        rows.append(
            {
                "id": case["id"],
                "page": case["page"],
                "quotes": matches,
                "all_text_found": all(match["text_found"] for match in matches),
                "all_located": all(match["located"] for match in matches),
                "semantic_binding": "not_evaluated",
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anchors",
        type=Path,
        default=Path(__file__).parent / "fixtures/naver_2024_quote_anchors.json",
    )
    parser.add_argument("--experiment", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    anchors = json.loads(args.anchors.read_text(encoding="utf-8"))
    comparisons = []
    for directory in args.experiment:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        if report["source_sha256"] != anchors["source_sha256"] or report["status"] != "succeeded":
            raise ValueError("successful experiment for the same source required")
        raw = directory / "raw/source.json"
        if raw.exists():
            nodes = raw_nodes(json.loads(raw.read_text(encoding="utf-8")))
        else:
            nodes = json.loads((directory / "nodes.json").read_text(encoding="utf-8"))
        selected = {
            **anchors,
            "cases": [case for case in anchors["cases"] if case["page"] in report["pages"]],
        }
        rows = anchor_matches(nodes, selected)
        comparisons.append(
            {
                "experiment": str(directory),
                "version": report["version"],
                "mode": report["mode"],
                "cases_evaluated": len(rows),
                "text_found_cases": sum(row["all_text_found"] for row in rows),
                "located_cases": sum(row["all_located"] for row in rows),
                "rows": rows,
            }
        )
    result = {
        "schema": "odl-quote-comparison-v1",
        "source_sha256": anchors["source_sha256"],
        "authority": anchors["authority"],
        "semantic_accuracy": None,
        "note": (
            "Quote presence and parser boxes only; year/entity/unit/context binding "
            "and claim verification remain separate."
        ),
        "comparisons": comparisons,
    }
    if args.output.exists():
        parser.error("output already exists")
    write_json(args.output, result)
    print(
        json.dumps(
            [{key: value for key, value in item.items() if key != "rows"} for item in comparisons],
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
