"""PF1 read-only profiling of saved stages, usage reservations and call receipts."""

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
OUT = LAB / "perf/PF1"


def profile(base, arm, company):
    state = base / "states" / arm / company
    meta = json.loads((state / "pilot.json").read_text())
    executions = [json.loads(p.read_text()) for p in base.glob(f"{arm}-{company}*execution.json")]
    calls_path = base / f"{arm}-{company}-calls.jsonl"
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    stages, api, timing = {}, [], {}
    for line in (base / f"{arm}-{company}-run.log").read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        stages.update(row.get("pipeline_outcome", {}).get("stage_seconds", {}))
        if row.get("kind") == "log" and row.get("event") == "operation_completed":
            end = datetime.fromisoformat(row["timestamp"]).timestamp()
            span = row["latency_ms"] / 1000
            timing[row["stage"].lower()] = [end - span, end]
        if row.get("kind") == "log" and row.get("event") == "api_request":
            api.append(row["latency_ms"] / 1000)
    with sqlite3.connect((state / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        usage = db.execute(
            "select request_id,attempt,reservation,state,ledger from usage_attempts "
            "where tenant_id=? and run_id=?",
            (meta["tenant_id"], meta["run_id"]),
        ).fetchall()
        jobs = [
            json.loads(v)
            for (v,) in db.execute(
                "select value from job_records where kind='job' and tenant_id=? and run_id=?",
                (meta["tenant_id"], meta["run_id"]),
            )
        ]
        artifacts = [
            json.loads(v)
            for (v,) in db.execute(
                "select value from job_records where kind='artifact' and tenant_id=? and run_id=?",
                (meta["tenant_id"], meta["run_id"]),
            )
        ]
    intervals, phases, request_rows = [], Counter(), []
    for rid, attempt, reservation, state_name, ledger in usage:
        reservation = json.loads(reservation)
        settled = json.loads(ledger) if ledger else {}
        latency = settled.get("usage", {}).get("latency_ms", 0) / 1000
        begin = reservation["created_at"]
        phase = "unknown"
        for part in ("preliminary", "relation", "elements"):
            if (state / "tagging-receipts" / meta["run_id"] / part / rid).is_dir():
                phase = part
                break
        phases[phase] += latency
        if latency:
            intervals.append((begin, begin + latency))
        request_rows.append(
            dict(
                request_id=rid,
                attempt=attempt,
                stage=phase,
                latency_seconds=latency,
                reservation_epoch=begin,
                state=state_name,
                error=settled.get("usage", {}).get("error_code"),
            )
        )
    usage_by_id = {r["request_id"]: r for r in request_rows}
    chains = []
    for artifact in artifacts:
        if "tagging_settings" not in artifact:
            continue
        for item in artifact["claims"]:
            ids = [
                r["request_id"]
                for phase in ("preliminary_records", "relation_records")
                for r in item.get(phase, [])
            ]
            ids += [r["request"]["request_id"] for r in item.get("tag_runs", [])]
            times = [usage_by_id[r] for r in ids if r in usage_by_id]
            if times:
                first = min(r["reservation_epoch"] for r in times)
                last = max(r["reservation_epoch"] + r["latency_seconds"] for r in times)
                chains.append(
                    dict(
                        claim_id=item["claim_id"],
                        request_ids=ids,
                        provider_sum_seconds=sum(r["latency_seconds"] for r in times),
                        elapsed_seconds_approx=last - first,
                    )
                )
    endpoints = sorted([(t, delta) for a, b in intervals for t, delta in [(a, 1), (b, -1)]])
    active, peak, occupied, serial, prior = 0, 0, 0.0, 0.0, None
    for now, delta in endpoints:
        if prior is not None:
            occupied += (now - prior) if active else 0
            serial += (now - prior) if active == 1 else 0
        active += delta
        peak = max(active, peak)
        prior = now
    attempts = Counter()
    extraction = 0.0
    for p in (state / "extraction-receipts").glob("*/raw_response.json"):
        raw = json.loads(p.read_text())
        for attempt in raw.get("attempts", []):
            extraction += attempt.get("latency_ms", 0) / 1000
            attempts[str(attempt.get("http_status", "unrecorded"))] += 1
    for p in (state / "tagging-receipts").rglob("response.json"):
        raw = json.loads(p.read_text())
        for attempt in raw.get("attempts", []):
            attempts[str(attempt.get("http_status", "unrecorded"))] += 1
    wall = sum(e["wall_seconds"] for e in executions)
    archived_attempts = []
    if base.name == "RH5" and arm == "candidate" and company == "sk":
        aggregate = json.loads((base / "results.json").read_text())["new_runs"][arm][company]
        wall = aggregate["wall_seconds"]
        archived_attempts = aggregate["attempts"]
    source = sum(
        s["wall_seconds"] for e in executions for s in e.get("source_verification_spans", [])
    )
    tag = stages.get("tag", 0)
    answer = dict(
        dataset=base.name,
        arm=arm,
        company=company,
        state=str(state),
        wall_seconds=wall,
        archived_attempts=archived_attempts,
        stage_seconds=stages,
        api_read_seconds=sum(api),
        unallocated_wall_seconds=wall - sum(stages.values()),
        call_wrapper_sum_seconds=sum(c["wall_seconds"] for c in calls),
        extraction_provider_sum_seconds=extraction,
        tag_provider_sum_seconds=sum(phases.values()),
        tag_phases_seconds=dict(phases),
        source_verification_seconds=source,
        extraction_prefetch_wall_seconds=sum(
            e.get("extract_model_windows_seconds", 0) for e in executions
        ),
        tag_occupied_seconds_approx=occupied,
        tag_single_call_seconds_approx=serial,
        tag_no_provider_seconds_approx=max(0, tag - occupied),
        tag_average_inflight=sum(phases.values()) / tag if tag else None,
        tag_capacity_utilization=sum(phases.values()) / (8 * tag) if tag else None,
        recorded_peak=max(e.get("peak_inflight", 0) for e in executions),
        reconstructed_tag_peak_approx=peak,
        retries=sum(a > 1 for _, a, *_ in usage),
        wrapper_errors=dict(Counter(c.get("error") for c in calls if c.get("error"))),
        attempt_http_statuses=dict(attempts),
        job_attempts=[
            dict(
                stage=j["message"]["stage"],
                attempt=j["attempt"],
                status=j["status"],
                error=j.get("error_code"),
            )
            for j in jobs
        ],
        longest_stage=max(stages, key=stages.get) if stages else None,
        longest_call_seconds=max(c["wall_seconds"] for c in calls),
        request_rows=request_rows,
        longest_tag_claim_chain=max(chains, key=lambda c: c["elapsed_seconds_approx"])
        if chains
        else None,
    )
    return answer


def main():
    rows = [
        profile(LAB / path, arm, company)
        for path in ("sprint6/E2E8", "decision/RH5")
        for arm in ("control", "candidate")
        for company in ("sk", "hyundai", "posco", "samsung", "naver", "kia")
    ]
    output = dict(
        schema="pf1-profile-v1",
        rows=rows,
        limits=[
            "Reservation timestamps are integer seconds: occupancy is approximate.",
            "calls.jsonl has durations but no start/end: exact extraction overlap unavailable.",
            "Review duration is observed API reads, not a separately timed worker stage.",
            "RH5 SK recovery timings are summed across preserved attempts; final state differs.",
            "No account rate-limit headers captured; HTTP concurrency unchanged.",
        ],
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "profile.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for row in rows:
        print(
            row["dataset"],
            row["arm"],
            row["company"],
            round(row["wall_seconds"], 1),
            row["stage_seconds"],
            round(row["tag_capacity_utilization"] or 0, 3),
        )


if __name__ == "__main__":
    main()
