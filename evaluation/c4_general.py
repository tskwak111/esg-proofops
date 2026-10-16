"""C4 bounded actual-API evaluation and automatic arbitrary-report local entry point."""

import argparse
import json
import sqlite3
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from proofops.adapters.local.c4_processing import prepare_candidate, process_report
from proofops.application.ingest.graph_fusion import (
    QualityIssue,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.tagging.fact_assembly_c4 import POLICY_HASH, discover, safety_reasons

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
OUT = LAB / "fix/C4"


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text() != content:
        raise ValueError("C4_IMMUTABLE_EVALUATION_CONFLICT:" + name)
    if not path.exists():
        path.write_text(content)


def graph_for(company):
    data = json.loads((LAB / f"fix/C2/{company}-pilot-graph.json").read_text())
    graph = fuse_candidates(
        candidates_from_snapshot(data["candidates"]), tenant_id=data["tenant_id"]
    )
    return replace(graph, issues=tuple(QualityIssue(**i) for i in data["issues"]))


def origin(company):
    row = next(
        r
        for r in json.loads((LAB / "fix/E02/source-inventory.json").read_text())
        if r["company"] == company
    )
    return Path(row["path"]).read_bytes()


def rulepack(company):
    from proofops.domain.rulepacks import RulePackSnapshot

    cohort = "B-lg-16w-8rps" if company == "lg" else "C-kakao-16w-8rps"
    path = LAB / f"perf/I9/{cohort}/publication-final/state.sqlite3"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots LIMIT 1").fetchone()[0])
    return RulePackSnapshot(**snapshot["rulepack"])


def corpus_screen():
    from proofops.domain.provenance import canonical_hash

    previous = json.loads((LAB / "fix/C3/cases.json").read_text())
    measurements = []
    for measurement in previous["measurements"]:
        path = Path(measurement["source_artifact"])
        if path.suffix == ".sqlite3":
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                records = [
                    json.loads(r[0])
                    for r in db.execute("SELECT value FROM job_records WHERE kind='artifact'")
                ]
            claims = next(d["discovery"]["claims"] for d in records if "discovery" in d)
        else:
            value = json.loads(path.read_text())
            claims = (
                value["discovery"]["claims"]
                if "discovery" in value
                else value.get("result", value)["claims"]
            )
        blocks = []
        for claim in claims:
            refs = claim.get("source_refs", [])
            # Saved claim screening only: do not attest invented graph blocks.
            blocks.append(
                SimpleNamespace(
                    kind="paragraph",
                    winner=0,
                    normalized_text=claim["quote"],
                    source_id=claim["claim_id"],
                    page_num=claim.get("original_page_num")
                    or (refs[0]["page_num"] if refs else None),
                )
            )
        nominations = discover(SimpleNamespace(blocks=blocks))
        measurements.append(
            dict(
                company=measurement["company"],
                claims_screened=len(claims),
                saved_claim_nominations=nominations,
                baseline_confirmed=sum(bool(c.get("confirmed_grade")) for c in claims),
                saved_input_sha256=sha256(path.read_bytes()).hexdigest(),
                saved_input_semantic_sha256=canonical_hash(claims),
                simulated=measurement["simulated"],
                source_artifact=str(path),
            )
        )
    return measurements


def prepare():
    rows = []
    for company in ("lg", "kakao"):
        graph, source, pack = graph_for(company), origin(company), rulepack(company)
        for candidate in discover(graph):
            data = prepare_candidate(
                graph, source, candidate, pack, run_id=str(uuid5(NAMESPACE_URL, "C4-" + company))
            )
            row = dict(
                company=company,
                candidate=candidate,
                status=data["status"],
                source_receipt=data["source_receipt"],
                blockers=data.get("blockers", []),
            )
            if data["status"] == "ready":
                row["packet"] = data["packet"].to_dict()
            rows.append(row)
            print(company, data["status"], candidate["physical_page"], flush=True)
    write("preparation.json", rows)
    write("corpus-screen.json", corpus_screen())


def live_transport():
    from proofops.adapters.local.decisions import load_key
    from proofops.adapters.local.openai import OpenAIProbe

    from evaluation.c2_pilot import verify_provider_receipt
    from scripts.finals_demo import FinalsBudget

    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openrouter", "upstage")}
    ledgers.update(
        {
            "historical-openai": ROOT / ".local/openai/budget.sqlite3",
            "C2-openai": LAB / "fix/C2/api-budget.sqlite3",
            "C3-openai": LAB / "fix/C3/api-budget.sqlite3",
            "openai": OUT / "api-budget.sqlite3",
        }
    )
    probe = OpenAIProbe(load_key("openai", ROOT), ledgers["openai"])
    fence = FinalsBudget(
        LAB / "sprint3/E2E/r108-spend.json",
        ledgers,
        OUT / "paid-calls.jsonl",
        task="C4",
        limit_usd="0.50",
    )  # stricter than authorized USD .80
    guarded = fence.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal("0.02"))

    def transport(request):
        from proofops.application.analysis_profile import MODEL_RESPONSE_POLICY
        from proofops.domain.provenance import canonical_hash

        prior = OUT / (request["id"] + "-response.json")
        if prior.exists():
            original_request = json.loads((OUT / (request["id"] + "-request.json")).read_text())
            if original_request != request:
                raise ValueError("C4_STORED_REQUEST_MISMATCH")
            response = json.loads(prior.read_text())
            verify_provider_receipt(response, OUT / "api-budget.sqlite3")
            return response | dict(provider="openai", simulated=False)

        snapshot = request["snapshot"]
        policy = snapshot["analysis_profile_policy"] | dict(
            model_response_policy=MODEL_RESPONSE_POLICY
        )
        snapshot = snapshot | dict(
            analysis_profile_policy=policy, analysis_profile_policy_sha256=canonical_hash(policy)
        )
        probe.configure_response_policy(snapshot, role="elements")
        with probe.response_context(role="elements", replica=request["replica"]):
            response = guarded(
                probe,
                request["system"],
                request["user_json"],
                request_id=request["id"],
                max_tokens=request["max_tokens"],
                json_mode=True,
                schema_json=request["schema_json"],
            )
        verify_provider_receipt(response, OUT / "api-budget.sqlite3")
        write(request["id"] + "-request.json", request)
        write(request["id"] + "-response.json", response)
        print(
            json.dumps(
                dict(
                    id=request["id"],
                    schema_valid=response["schema_valid"],
                    cost_usd=response["cost_with_vat_reserve_usd"],
                )
            ),
            flush=True,
        )
        return response | dict(provider="openai", simulated=False)

    return transport, fence


def api():
    transport, fence = live_transport()
    results = []
    for company in ("lg", "kakao"):
        results.append(
            dict(
                company=company,
                processing=process_report(
                    graph_for(company),
                    origin(company),
                    rulepack(company),
                    run_id=str(uuid5(NAMESPACE_URL, "C4-" + company)),
                    output=OUT / "publication" / company,
                    transport=transport,
                ),
            )
        )
    write("processing.json", results)
    with fence.transaction() as (_, entry):
        entry["status"] = "completed"
        write("task-budget.json", dict(entry))
    screen = json.loads((OUT / "corpus-screen.json").read_text())
    nominations = json.loads((LAB / "fix/C3/cases.json").read_text())["discovery_nominations"]
    for n in nominations:
        matches = [
            r
            for result in results
            if result["company"] == n["company"]
            for r in result["processing"]["rows"]
            if "".join(n["quote"].split()) in "".join(r["candidate"]["quote"].split())
        ]
        n["c4_matches"] = [
            dict(
                claim_id=r.get("claim_id"),
                public_auto_confirmed=r["public_auto_confirmed"],
                status=r["status"],
                blockers=r["blockers"],
            )
            for r in matches
        ]
        if not matches:
            n["c4_blockers"] = safety_reasons(n["quote"]) or [
                "NO_COMPLETE_DIRECT_SYSTEM_SCOPE_NOMINATION"
            ]
    cases = dict(
        policy_sha256=POLICY_HASH,
        automatic_processing=results,
        nine_C3_sentences=nominations,
        report_measurements=screen,
        negative_false_confirmation_count=None,
        independent_astra_review="pending",
        independent_gold_validation="not_run",
    )
    write("cases-initial.json", cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "api", "report"])
    for option in ("graph", "source", "rulepack", "output", "run-id"):
        parser.add_argument("--" + option)
    args = parser.parse_args()
    if args.stage == "report":
        if not all(getattr(args, k) for k in ("graph", "source", "rulepack", "output", "run_id")):
            parser.error("report requires --graph --source --rulepack --output --run-id")
        from proofops.domain.rulepacks import RulePackSnapshot

        data = json.loads(Path(args.graph).read_text())
        graph = fuse_candidates(
            candidates_from_snapshot(data["candidates"]), tenant_id=data["tenant_id"]
        )
        graph = replace(graph, issues=tuple(QualityIssue(**i) for i in data["issues"]))
        pack = RulePackSnapshot(**json.loads(Path(args.rulepack).read_text()))
        if pack.status != "active" or not pack.approved_by or not pack.approved_at:
            raise ValueError("C4_EXISTING_ACTIVE_RULEPACK_REQUIRED")
        transport, _ = live_transport()
        value = process_report(
            graph,
            Path(args.source).read_bytes(),
            pack,
            run_id=args.run_id,
            output=Path(args.output),
            transport=transport,
        )
        target = Path(args.output) / "processing.json"
        with target.open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        print(
            json.dumps(
                {
                    k: value[k]
                    for k in ("nomination_count", "confirmed_count", "extra_calls", "seconds")
                }
            )
        )
    else:
        (prepare if args.stage == "prepare" else api)()


if __name__ == "__main__":
    main()
