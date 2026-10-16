"""Audit K7's frozen live outputs against I6; no providers, no source promotion."""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_K7_POLICY, FINALS_K7_V1_POLICY
from proofops.domain.provenance import canonical_hash

from evaluation.h1_holdout import load_a_scorer
from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import fixture

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
OUT = LAB / "fix/K7"


def read(path):
    return json.loads(path.read_text())


def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def present(item):
    return {
        e["element_id"]
        for e in (item.get("provisional_grade") or {}).get("elements", [])
        if e["state"] == "present"
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("v1", "v2"), default="v2")
    args = parser.parse_args()
    native_dir = "native" if args.phase == "v1" else "native-v2"
    policy = FINALS_K7_V1_POLICY if args.phase == "v1" else FINALS_K7_POLICY
    scorer, native_audit = load_a_scorer()
    results, losses, failures, sources, cases, wires = {}, [], [], [], [], []
    for company in ("naver", "kia", "sk", "posco", "hyundai"):
        state = OUT / native_dir / ("B" if company in ("naver", "kia") else company)
        state /= company if company in ("naver", "kia") else "product-hyundai"
        old = LAB / "perf/I6" / ("B" if company in ("naver", "kia") else "B-" + company)
        old /= company if company in ("naver", "kia") else "product-hyundai"
        graph, raw_source, discovery, snapshot, _ = fixture(state)
        old_graph, old_source, _, _, _ = fixture(old)
        assert raw_source == old_source and graph.source_sha256 == old_graph.source_sha256
        assert snapshot["analysis_profile_policy"] == policy
        extraction, tag = checkpoint(state, "extract"), checkpoint(state, "tag")
        old_extraction, old_tag = checkpoint(old, "extract"), checkpoint(old, "tag")
        claims = {c["claim_id"]: c for c in extraction["discovery"]["claims"]}
        prior = {c["claim_id"]: c for c in old_extraction["discovery"]["claims"]}

        def key(quote):
            return "".join(quote.split())

        current = {key(claims[i["claim_id"]]["quote"]): i for i in tag["claims"]}
        for item in old_tag["claims"]:
            quote = prior[item["claim_id"]]["quote"]
            new = current.get(key(quote))
            lost = present(item) - present(new or {})
            if new is None or lost:
                losses.append(
                    dict(
                        company=company,
                        quote=quote,
                        lost_present=sorted(lost),
                        missing_claim=new is None,
                    )
                )
        verified = {
            i["claim_id"]
            for i in tag["claims"]
            if i.get("source_status", {}).get("status") == "verified"
        }
        predictions = [
            dict(
                id=c.claim_id,
                page=c.source_refs[0].page_num,
                quote=c.quote,
                source_verified=c.claim_id in verified,
                raw=asdict(c),
            )
            for c in discovery.claims
        ]
        audited = native_audit(
            predictions, graph, next((state / "objects/original").rglob("*.pdf"))
        )
        false = [
            a
            for a in audited
            if a["declared_verified"] and (a["native_audit_mismatch"] or a["uncheckable"])
        ]
        sources.append(
            dict(
                company=company,
                claims=len(predictions),
                verified=len(verified),
                false_verified=len(false),
            )
        )
        for item in tag["claims"]:
            claim = claims[item["claim_id"]]
            for run in item["tag_runs"]:
                response = json.loads(run.get("provider_response_json") or "null")
                errors = run["errors"]
                if run["status"] in (
                    "model_failed",
                    "invalid_request",
                    "invalid_response",
                    "invalid_cache",
                    "budget_exhausted",
                    "citation_unresolved",
                ) or (isinstance(response, dict) and response.get("schema_valid") is False):
                    failures.append(
                        dict(
                            company=company,
                            quote=claim["quote"],
                            status=run["status"],
                            errors=errors,
                            diagnostic=run.get("diagnostic_detail"),
                        )
                    )
            cases.append(
                dict(
                    company=company,
                    quote=claim["quote"],
                    source_status=item.get("source_status"),
                    present=sorted(present(item)),
                    tag_statuses=[r["status"] for r in item["tag_runs"]],
                    elements=(item.get("provisional_grade") or {}).get("elements", []),
                )
            )
        for path in state.rglob("request.json"):
            request = read(path)
            if "wire_user_json" not in request:
                continue
            wire = json.loads(request["wire_user_json"])
            data = wire.get("untrusted_document_data", {})
            if "interpretation_budget" not in data:
                continue
            # Pure serialization only; never construct a funded probe or dispatch.
            probe = object.__new__(OpenAIProbe)
            probe.response_policy = {} if "model_response_policy" in policy else None
            body = probe.request_body(
                request["wire_system"],
                request["wire_user_json"],
                request_id=path.parent.name,
                max_tokens=request["request"]["max_tokens"],
                json_mode=True,
            )
            size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
            assert size <= 16384
            assert "source_id" not in json.dumps(data.get("sentence_context"))
            wires.append(
                dict(
                    company=company,
                    request_id=path.parent.name,
                    bytes=size,
                    budget=data["interpretation_budget"],
                )
            )
        results[company] = dict(claims=len(tag["claims"]), completion=tag.get("completion"))
    write(
        "B-summary-v1.json" if args.phase == "v1" else "B-summary.json",
        dict(
            companies=results,
            cases=cases,
            regressions=losses,
            failures=failures,
            source_audit=sources,
            wire_requests=wires,
            policy_sha256=canonical_hash(policy),
            accepted=not losses and not failures and not any(s["false_verified"] for s in sources),
        ),
    )
    gold = read(LAB / "fix/G1/DL4-gold.json")["golds"]
    old, new = [], []
    for company in ("naver", "kia"):
        old += [
            p | dict(company=company) for p in read(LAB / f"perf/I6/A-linux/{company}-after.json")
        ]
        new += [p | dict(company=company) for p in read(OUT / f"A-linux/{company}-after.json")]
    dl4 = dict(before=scorer.evaluate(gold, old), after=scorer.evaluate(gold, new))
    write("dl4-scores.json", dl4)
    holdout = read(OUT / "holdout-final/holdout-scores.json")
    assert all(
        holdout["scores"]["after"][k] >= holdout["scores"]["before"][k]
        for k in ("precision", "recall")
    )
    assert all(dl4["after"][k] >= dl4["before"][k] for k in ("precision", "recall"))
    assert not Counter((p["page"], p["quote"]) for p in old) - Counter(
        (p["page"], p["quote"]) for p in new
    )
    print(
        json.dumps(
            dict(
                companies=results,
                present_losses=len(losses),
                failures=len(failures),
                false_verified=sum(s["false_verified"] for s in sources),
                wire_max_bytes=max(w["bytes"] for w in wires),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
