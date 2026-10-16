"""Audit task evidence once: physical caps, identical replay, source and USD fences."""

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.spend_guard import SpendGuard
from proofops.adapters.parsing.opendataloader import candidates_from_snapshot
from proofops.adapters.parsing.parser_artifacts import read_parser_json
from proofops.application.analysis_profile import FINALS_S5_POLICY
from proofops.application.ingest.graph_fusion import QualityIssue, fuse_candidates
from proofops.domain.provenance import canonical_hash

from evaluation.h1_holdout import load_a_scorer
from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import discovery_from_record


def starts_per_second(starts):
    starts = sorted(starts)
    first = maximum = 0
    for index, current in enumerate(starts):
        while current - starts[first] >= 1:
            first += 1
        maximum = max(maximum, index - first + 1)
    return maximum


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output

    def read(path):
        return read_parser_json(path)

    comparison = read(out / "comparison.json")
    replay = {}
    for label, case in comparison["cases"].items():
        corrected = label.replace("8w-4rps-v2", "8w-4rps-v3")
        if corrected != label and (out / corrected / "measurement.json").is_file():
            label = corrected
            case = read(out / label / "measurement.json")
        events = read(out / label / "measurement.json")["events"]
        calls = [event for event in events if event["function"] == "llm"]
        scheduler = case["scheduler"]
        rps = starts_per_second([call["start"] for call in calls])
        assert rps <= scheduler["requests_per_second"]
        assert scheduler["peak"] <= case["workers"]
        assert len(calls) == scheduler["physical_attempts"] == case["replay_calls"]
        assert case["original_checkpoint_identical"]
        assert not scheduler["rate_limits"] and not scheduler["circuit_open"]
        replay[label] = dict(
            seconds=case["seconds"],
            stage_seconds=case["stage_seconds"],
            max_starts_per_second=rps,
            peak=scheduler["peak"],
            physical_attempts=len(calls),
            result_sha256=case["result_sha256"],
        )
    _, native_audit = load_a_scorer()
    live = {}
    for workers, rps in ((8, 4), (12, 6)):
        label = f"live-{workers}w-{rps}rps"
        state = out / label / "lgchem"
        summary = read(out / (label + "-summary.json"))
        measurement = read(state / "measurement.json")
        assert summary["status"] == "completed"
        with sqlite3.connect((state / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
        assert snapshot["analysis_profile_policy"] == FINALS_S5_POLICY
        with sqlite3.connect((state / "live-luna.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            receipts = [
                json.loads(row[0])
                for row in db.execute("SELECT receipt FROM probe_calls WHERE receipt IS NOT NULL")
            ]
            unsettled = db.execute(
                "SELECT count(*) FROM probe_calls WHERE receipt IS NULL"
            ).fetchone()[0]
        attempts = [
            a
            for receipt in receipts
            for a in receipt.get("provider_scheduler", {}).get("attempts", [])
        ]
        maximum = starts_per_second([a["transport_started_monotonic"] for a in attempts])
        assert maximum <= rps
        assert all(a["error_code"] is None for a in attempts)
        assert not unsettled
        assert len(attempts) == summary["admission"]["physical_attempts"]
        tag = checkpoint(state, "tag")
        claims = discovery_from_record(checkpoint(state, "extract")["discovery"]).claims
        prepared = next((state / "parser-prepared").rglob("manifest.json")).parent
        manifest = read(prepared / "manifest.json")
        graph = fuse_candidates(
            candidates_from_snapshot(read(prepared / "candidates.json")),
            tenant_id=snapshot["tenant_id"],
            fusion_version=manifest["fusion_version"],
            mixed_parser=True,
        )
        assert graph.to_dict() == read(prepared / "graph.json")
        graph = replace(
            graph,
            issues=tuple(
                QualityIssue(**(q | dict(source_ids=tuple(q["source_ids"]))))
                for q in read(prepared / "quality.json")
            ),
        )
        source = (
            state
            / "objects/original"
            / snapshot["tenant_id"]
            / (snapshot["document"]["version_id"] + ".pdf")
        )
        assert sha256(source.read_bytes()).hexdigest() == snapshot["document"]["sha256"]
        verified = {
            item["claim_id"]
            for item in tag["claims"]
            if item.get("source_status", {}).get("status") == "verified"
        }
        audit = native_audit(
            [
                dict(
                    id=c.claim_id,
                    page=c.source_refs[0].page_num,
                    quote=c.quote,
                    source_verified=c.claim_id in verified,
                    raw=asdict(c),
                )
                for c in claims
            ],
            graph,
            source,
        )
        false = [
            item
            for item in audit
            if item["declared_verified"] and (item["native_audit_mismatch"] or item["uncheckable"])
        ]
        assert not false
        live[label] = dict(
            seconds=summary["seconds"],
            stage_seconds=measurement["stage_seconds"],
            claims=len(claims),
            verified=len(verified),
            false_verified_native_audit=len(false),
            physical_attempts=len(attempts),
            max_starts_per_second=maximum,
            peak=summary["admission"]["peak"],
            unsettled=unsettled,
            error_counts=dict(Counter(a["error_code"] for a in attempts if a["error_code"])),
            provider=measurement["provider"],
            runtime=summary["resource_runtime"],
        )
    assert read(out / "resources/measurement.json")["source_receipt_identical"]
    guard = SpendGuard(
        out / "spend.sqlite3", event_id="S5-USD0.4", daily_limit=".4", event_limit=".4"
    )
    spend = guard.summary()
    assert not spend["reserved"] and not spend["uncertain"]
    assert Decimal(spend["exposure_usd"]) <= Decimal(".4")
    data = dict(
        replay=replay,
        live=live,
        spend=spend,
        policy_sha256=canonical_hash(FINALS_S5_POLICY),
        audit_scope="literal native quotes and locations; not model semantic accuracy",
        adoption="no_go until full LG+Kakao and c8g/source-semantic gates pass",
    )
    if (out / "live-semantic-comparison.json").is_file():
        data["live_semantic_comparison"] = read(out / "live-semantic-comparison.json")
    (out / "verification.json").write_text(json.dumps(data, indent=2))
    print(json.dumps(data), flush=True)


if __name__ == "__main__":
    main()
