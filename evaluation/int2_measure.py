"""Read-only INT2 observations; never execute provider calls or rewrite snapshots."""

import json
import sqlite3
from collections import Counter
from hashlib import sha256
from pathlib import Path

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT2"


def checkpoints(state):
    with sqlite3.connect(state.joinpath("state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("select payload from run_snapshots").fetchone()[0])
        records = [
            json.loads(v)
            for (v,) in db.execute(
                "select value from job_records where kind='artifact' "
                "and record_id like '%/checkpoint'"
            )
        ]
    return snapshot, {r["schema"]: r for r in records}


def measure(company):
    label = (
        "kepco-recovery"
        if company == "kepco" and (OUT / "kepco-recovery-live.json").exists()
        else company
    )
    state = OUT / "states" / label
    snapshot, data = checkpoints(state)
    parse = data["local_parser_checkpoint_v4"]
    extract = data["local_extract_checkpoint_v2"]
    tag = data["local_tag_checkpoint_v1"]
    live = json.loads((OUT / (label + "-live.json")).read_text())
    argv = json.loads((OUT / (label + "-argv.json")).read_text())
    baseline = json.loads(
        (
            ROOT / ("outputs/agent-results/R108-redesign/lab/parse/MP1/" + company + "-argv.json")
        ).read_text()
    )
    for flag in ["--pdf", "--pages", "--claim-pages"]:
        assert argv[argv.index(flag) + 1] == baseline[baseline.index(flag) + 1]
    assert (
        sha256(Path(argv[argv.index("--pdf") + 1]).read_bytes()).hexdigest()
        == parse["source_sha256"]
    )
    assert snapshot["evidence_source_policy"] == parse["evidence_source_attestation"]["policy"]
    folder = (
        state
        / "parser-prepared"
        / parse["tenant_id"]
        / parse["document_version_id"]
        / parse["parse_manifest_id"]
    )
    assert sha256((folder / "manifest.json").read_bytes()).hexdigest() == parse["manifest_sha256"]
    for name, digest in parse["artifacts"].items():
        assert sha256((folder / name).read_bytes()).hexdigest() == digest
    graph = json.loads((folder / "graph.json").read_text())
    local_pages = {
        p["physical_page"]
        for p in parse["page_parser_provenance"]
        if p["route"] == "opendataloader"
    }
    odl = {b["source_id"] for b in graph["blocks"] if b["page_num"] in local_pages}
    rows = tag["claims"]
    assert all(c["decision"] is None and c["review_inputs"] is None for c in rows)
    display = Counter(c["provisional_grade"]["display_type"] for c in rows)
    numeric = Counter(
        c["provisional_grade"]["evidence_grade"]
        for c in rows
        if c["provisional_grade"].get("evidence_grade")
    )
    ranges = Counter()
    widths = Counter()
    selected = set()
    packet_claims = set()
    guarded = set()
    guarded_claims = set()
    admitted = set()
    for c in rows:
        grade = c["provisional_grade"]
        if grade.get("grade_range"):
            r = grade["grade_range"]
            ranges[r["floor"] + "~" + r["ceiling"]] += 1
            widths[int(r["ceiling"][1:]) - int(r["floor"][1:])] += 1
        packet = c.get("frozen_packet") or {}
        for candidate in packet.get("evidence_candidates", []):
            for ref in candidate["source_refs"]:
                if ref["source_id"] in odl:
                    selected.add(
                        (
                            c["claim_id"],
                            ref["source_id"],
                            ref.get("char_start"),
                            ref.get("char_end"),
                        )
                    )
                    packet_claims.add(c["claim_id"])
        for run in c.get("tag_runs", []):
            for element in (run.get("guarded") or {}).get("elements", []):
                if element["state"] != "present":
                    continue
                for ref in element["evidence_refs"]:
                    if ref["source_id"] in odl:
                        guarded.add(
                            (
                                c["claim_id"],
                                element["element_id"],
                                ref["source_id"],
                                ref.get("char_start"),
                                ref.get("char_end"),
                            )
                        )
                        guarded_claims.add(c["claim_id"])
        for element in grade.get("elements", []):
            if isinstance(element, dict) and element.get("state") == "present":
                for ref in element.get("evidence_refs", []):
                    if ref["source_id"] in odl:
                        admitted.add((c["claim_id"], element["element_id"], ref["source_id"]))
    summary = None
    for line in (OUT / (label + "-live.log")).read_text().splitlines():
        if line.startswith("{"):
            value = json.loads(line)
            if "pipeline_outcome" in value:
                summary = value
    assert summary and summary["claims_http_status"] == 200
    previous = next(
        x
        for x in json.loads(
            (
                ROOT / "outputs/agent-results/R108-redesign/lab/parse/MP1/measurements.json"
            ).read_text()
        )
        if x["company"] == company
    )
    source_required = sum(c["source_status"]["status"] != "verified" for c in rows)
    ev1 = parse["evidence_source_attestation"]
    return dict(
        company=company,
        leg=label,
        **{k: live[k] for k in ["seconds", "exit_code", "report_usd"]},
        total_seconds_including_recovery=live.get("total_seconds_including_recovery"),
        mp1_seconds=previous["seconds"],
        delta_seconds=live["seconds"] - previous["seconds"],
        stage_seconds=summary["pipeline_outcome"]["stage_seconds"],
        mp1_stage_seconds=previous["stage_seconds"],
        claims=len(rows),
        claims_extracted=len(extract["discovery"]["claims"]),
        api_http_status=summary["claims_http_status"],
        grade_display=dict(display),
        numeric_grades=dict(numeric),
        range_distribution=dict(ranges),
        range_width_distribution=dict(widths),
        full_E0_E3_ratio=ranges["E0~E3"] / len(rows) if rows else None,
        full_E0_E3_among_ranges=ranges["E0~E3"] / display["range"] if display["range"] else None,
        original_confirmation_required=source_required,
        original_confirmation_required_ratio=source_required / len(rows) if rows else None,
        odl_verified_spans=sum(r["status"] == "verified" for r in ev1["records"]),
        odl_packet_occurrences=len(selected),
        odl_packet_claims=len(packet_claims),
        odl_guarded_present_citations=len(guarded),
        odl_guarded_present_claims=len(guarded_claims),
        odl_provisional_present_elements=len(admitted),
        statuses=dict(Counter(c["status"] for c in rows)),
        terminal_reasons=dict(Counter(c.get("reason") for c in rows)),
        coverage=tag["coverage"],
        source_sha256=parse["source_sha256"],
        analysis_policy_sha256=snapshot["analysis_profile_policy_sha256"],
    )


def main():
    assert (OUT / "kepco-recovery-live.json").exists(), "wait for the collected-job recovery"
    data = [measure(company) for company in ["samsung", "kepco"]]
    assert all(r["exit_code"] == 0 and r["claims"] > 0 for r in data)
    (OUT / "measurements.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
