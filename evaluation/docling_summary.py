"""Summarize saved parser comparisons without granting semantic approval."""

import argparse
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path


def summarize(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_bytes())
    artifacts = {}
    for name in ("audit.json", "candidates.json", "routing.json"):
        raw = (manifest_path.parent / name).read_bytes()
        if sha256(raw).hexdigest() != manifest["artifacts"][name]:
            raise ValueError("Parser artifact integrity mismatch: " + name)
        artifacts[name] = json.loads(raw)
    audit = artifacts["audit.json"]
    states = {row["key"]: row["reason"] for row in audit}
    local = [b for b in artifacts["candidates.json"] if b["parser_family"] == "docling"]
    tables = []
    for batch in local:
        cells = defaultdict(list)
        for block in batch["blocks"]:
            if block["table_native_id"]:
                cells[block["table_native_id"]].append(block)
        for block in batch["blocks"]:
            if block["kind"] != "table":
                continue
            source = block["source"]
            key = source["parser_run_id"] + "/" + source["source_native_id"]
            counts = Counter(
                states[cell["source"]["parser_run_id"] + "/" + cell["source"]["source_native_id"]]
                for cell in cells[source["source_native_id"]]
            )
            tables.append(
                dict(
                    page=source["physical_page"],
                    table_id=source["source_native_id"],
                    reason=states[key],
                    cells=dict(counts),
                    requires_review=any(r not in {"consensus", "not_numeric"} for r in counts)
                    or states[key] not in {"consensus", "not_numeric"},
                )
            )
    return dict(
        source_sha256=manifest["source_sha256"],
        manifest_sha256=sha256(manifest_path.read_bytes()).hexdigest(),
        selected_pages=manifest["selected_physical_pages"],
        upstage=manifest["upstage_parse"],
        routing=artifacts["routing.json"],
        candidate_reason_counts=dict(Counter(row["reason"] for row in audit)),
        docling_tables=len(tables),
        tables_requiring_review=sum(t["requires_review"] for t in tables),
        tables=tables,
        semantic_accuracy=None,
        expert_approved=False,
        note="Candidate counts include superseded standard output; agreement is not fact approval.",
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--manifest", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    report = summarize(args.manifest)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "tables"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
