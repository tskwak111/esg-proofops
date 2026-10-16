"""USD0 original-PDF parser reproduction and read-only H5 failure diagnosis."""

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact


def diagnose(folder):
    """Match each unsent extraction to saved transport/accounting records."""
    with sqlite3.connect(
        (folder / "openai.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        sent = {r[0] for r in db.execute("SELECT request_id FROM probe_calls")}
        attempts = {
            r[0]: (r[1], r[2])
            for r in db.execute("SELECT request_id,state,diagnostic FROM probe_transport_attempts")
        }
    result = {}
    for slug in ("hdec", "kumho", "report-ba74e5d960", "report-e4de859868"):
        state = folder / "final" / slug / "state"
        failures = [json.loads(f.read_text()) for f in state.rglob("failure.json")]
        result[slug] = dict(
            extraction_errors=dict(Counter(f["error"] for f in failures)),
            failure_request_ids=[f["request_id"] for f in failures],
            failure_requests_with_paid_reservation=sum(f["request_id"] in sent for f in failures),
            failure_requests_with_transport_attempt=sum(
                f["request_id"] in attempts for f in failures
            ),
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--h5", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--slug", action="append")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    reports = json.loads((args.h5 / "manifest.json").read_text())["reports"]
    result = dict(
        new_paid_calls=0,
        new_cost_usd="0",
        reports=[],
        diagnosis=diagnose(args.h5),
        server_live_models="not_run_USD0",
        worker_12GiB_measurement="not_run_local_only",
    )
    for report in reports:
        if args.slug and report["slug"] not in args.slug:
            continue
        content = Path(report["pdf"]).read_bytes()
        assert sha256(content).hexdigest() == report["source_sha256"]
        source = SourceArtifact(
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
            report["source_sha256"],
            "original-h5",
            content,
            upload_security_limits=dict(
                max_bytes=100 * 1024 * 1024,
                max_pages=1000,
                timeout_seconds=120,
                policy_profile="display-v2",
            ),
        )
        profile = ParserProfile(
            str(uuid4()),
            physical_pages=tuple(report["selection"]["pages"]),
            java_executable="/opt/homebrew/opt/openjdk@21/bin/java",
            timeout_seconds=300,
            memory_bytes=768 * 1024 * 1024,
            max_output_bytes=128 * 1024 * 1024,
            table_structure_repair="odl_header_v2",
            local_resource_policy="selected-pdf-h6-v1",
            failure_policy="partial-v3",
        )
        directory = args.out / report["slug"]
        directory.mkdir(exist_ok=True)
        started = monotonic()
        item = dict(
            slug=report["slug"],
            company=report["company"],
            source_sha256=source.sha256,
            selected_pages=list(profile.physical_pages),
            source_proof="required_on_original; repaired-subsets-candidate-only",
            parser_memory_bytes=profile.memory_bytes,
        )
        try:
            adapter = OpenDataLoaderParser(directory)
            graph = adapter.parse(source, profile, tenant_id=source.tenant_id)
            manifest = (
                directory
                / source.tenant_id
                / source.document_version_id
                / profile.parse_manifest_id
            )
            local = json.loads((manifest / "h6-local.json").read_text())
            item.update(
                status="parsed",
                parsed_pages=sorted(
                    p for b in local["batches"] if b["status"] == "parsed" for p in b["pages"]
                ),
                unreadable_pages=[b for b in local["batches"] if b["status"] == "unreadable"],
                blocks=len(graph.blocks),
                replay_equal=adapter.load_verified(source, profile, tenant_id=source.tenant_id)
                == graph,
                manifest=str(manifest),
                profile=asdict(profile),
            )
        except Exception as error:
            item.update(
                status="failed",
                error_code=str(error) if isinstance(error, ValueError) else type(error).__name__,
            )
        item["seconds"] = monotonic() - started
        result["reports"].append(item)
        (args.out / "local-reproduction.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        print(json.dumps(item, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
