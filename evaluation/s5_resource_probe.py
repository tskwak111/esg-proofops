"""Compare unchanged v13 source attestation with OCR2/OCR4 execution wrappers."""

import argparse
import json
import os
import shutil
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.adapters.local.pa7_raster_cache import attest, clear
from proofops.adapters.local.worker_resources import apply_resources, close_ocr_pool
from proofops.adapters.parsing.opendataloader import candidates_from_snapshot
from proofops.adapters.parsing.parser_artifacts import read_parser_json
from proofops.application.ingest.graph_fusion import QualityIssue, fuse_candidates
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import discovery_from_record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.source / "pilot.json").read_text())
    with sqlite3.connect((args.source / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    prepared = next((args.source / "parser-prepared").rglob("manifest.json")).parent
    saved = json.loads((prepared / "manifest.json").read_text())
    graph = fuse_candidates(
        candidates_from_snapshot(read_parser_json(prepared / "candidates.json")),
        tenant_id=snapshot["tenant_id"],
        fusion_version=saved["fusion_version"],
        mixed_parser=True,
    )
    assert graph.to_dict() == read_parser_json(prepared / "graph.json")
    graph = replace(
        graph,
        issues=tuple(
            QualityIssue(**(q | dict(source_ids=tuple(q["source_ids"]))))
            for q in json.loads((prepared / "quality.json").read_text())
        ),
    )
    source = (
        args.source
        / "objects/original"
        / snapshot["tenant_id"]
        / (snapshot["document"]["version_id"] + ".pdf")
    ).read_bytes()
    blocks = {b.source_id: b for b in graph.blocks}
    claims = discovery_from_record(checkpoint(args.source, "extract")["discovery"]).claims
    claim = next(c for c in claims if blocks[c.source_refs[0].source_id].kind == "paragraph")
    refs = claim.source_refs
    shutil.copy2(args.source / "upstage.sqlite3", args.output / "ocr.sqlite3")
    reader = page_ocr_profile("upstage-ocr-page-v13")
    results = []
    with reader_scope(ReplayOCRStore(args.output / "ocr.sqlite3")):
        start = time.monotonic()
        baseline = reader.attest_claim_spans(
            graph, source, refs, tenant_id=snapshot["tenant_id"], run_id=manifest["run_id"]
        )
        results.append(
            dict(
                arm="unchanged-v13",
                seconds=time.monotonic() - start,
                receipt_sha256=canonical_hash(baseline),
            )
        )
        for processes in (2, 4):
            close_ocr_pool()
            os.environ["PROOFOPS_OCR_PROCESSES"] = str(processes)
            runtime = apply_resources()
            clear()
            start = time.monotonic()
            result = attest(
                reader,
                graph,
                source,
                refs,
                tenant_id=snapshot["tenant_id"],
                run_id=manifest["run_id"],
            )
            assert result == baseline, "S5_RESOURCE_SOURCE_RECEIPT_CHANGED"
            results.append(
                dict(
                    arm=f"ocr{processes}",
                    seconds=time.monotonic() - start,
                    receipt_sha256=canonical_hash(result),
                    runtime=runtime,
                )
            )
        close_ocr_pool()
    data = dict(
        cases=results,
        source_receipt_identical=True,
        claim_id=claim.claim_id,
        records=[dict(status=r["status"], reason=r.get("reason")) for r in baseline["records"]],
        paid_usd="0",
        live_provider_calls=0,
    )
    (args.output / "measurement.json").write_text(json.dumps(data, indent=2))
    print(json.dumps(data), flush=True)


if __name__ == "__main__":
    main()
