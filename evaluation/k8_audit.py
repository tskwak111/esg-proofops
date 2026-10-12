"""Read-only audit of bounded K8 receipts, source evidence and requested gates."""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import (
    FINALS_K7_POLICY,
    FINALS_K8_POLICY,
    FINALS_K8_V2_POLICY,
    FINALS_K8_V3_POLICY,
)
from proofops.domain.provenance import canonical_hash

from evaluation.h1_holdout import load_a_scorer
from evaluation.k8_live import LAB
from evaluation.pa3_replay import checkpoint
from evaluation.pa9_source_gate import fixture

OUT = LAB / "fix/K8"


def read(path):
    return json.loads(path.read_text())


def present(item):
    return {
        e["element_id"]
        for e in (item.get("provisional_grade") or {}).get("elements", [])
        if e["state"] == "present"
    }


def key(quote):
    return "".join(quote.split())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("v1", "v2", "final"), default="final")
    args = parser.parse_args()
    policy = (
        FINALS_K8_POLICY
        if args.phase == "v1"
        else (FINALS_K8_V2_POLICY if args.phase == "v2" else FINALS_K8_V3_POLICY)
    )
    native = "native" if args.phase == "v1" else "native-v2"
    scorer, native_audit = load_a_scorer()
    results, cases, losses, failures, audits, wires = {}, [], [], [], [], []
    for company in ("hyundai", "posco", "sk", "naver", "kia"):
        suffix = (
            Path("B") / company
            if company in ("naver", "kia")
            else Path(company) / "product-hyundai"
        )
        selected_policy = policy
        selected_native = native
        if args.phase == "final":
            selected_policy = (
                FINALS_K8_V3_POLICY if company in ("naver", "kia") else FINALS_K8_V2_POLICY
            )
            selected_native = "native-v5" if company in ("naver", "kia") else "native-v2"
        state = OUT / selected_native / suffix
        old = LAB / "fix/K7/native-v2" / suffix
        graph, source, discovery, snapshot, _ = fixture(state)
        old_graph, old_source, _, old_snapshot, _ = fixture(old)
        assert source == old_source and graph.source_sha256 == old_graph.source_sha256
        assert snapshot["analysis_profile_policy"] == selected_policy
        assert old_snapshot["analysis_profile_policy"] == FINALS_K7_POLICY
        extraction, tag = checkpoint(state, "extract"), checkpoint(state, "tag")
        old_extraction, old_tag = checkpoint(old, "extract"), checkpoint(old, "tag")
        claims = {c["claim_id"]: c for c in extraction["discovery"]["claims"]}
        prior = {c["claim_id"]: c for c in old_extraction["discovery"]["claims"]}
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
        audits.append(
            dict(
                company=company,
                claims=len(predictions),
                verified=len(verified),
                false_verified=len(false),
            )
        )
        for item in tag["claims"]:
            for run in item["tag_runs"]:
                response = json.loads(run.get("provider_response_json") or "null")
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
                            quote=claims[item["claim_id"]]["quote"],
                            status=run["status"],
                            errors=run["errors"],
                        )
                    )
            cases.append(
                dict(
                    company=company,
                    quote=claims[item["claim_id"]]["quote"],
                    source_status=item.get("source_status"),
                    present=sorted(present(item)),
                    sentence_context=item.get("sentence_context"),
                    elements=(item.get("provisional_grade") or {}).get("elements", []),
                )
            )
        preliminary_ids = {
            record["request_id"]
            for item in tag["claims"]
            for record in item.get("preliminary_records", [])
            if "request_id" in record
        }
        for response_path in state.rglob("response.json"):
            if response_path.parent.name not in preliminary_ids:
                continue
            response = read(response_path)
            receipt = json.loads(response.get("provider_response_json") or "null")
            if isinstance(receipt, dict) and receipt.get("schema_valid") is False:
                failures.append(
                    dict(
                        company=company,
                        stage="preliminary",
                        request_id=response_path.parent.name,
                        schema_valid=False,
                        error=receipt.get("validation_error"),
                        attempts=len(receipt.get("attempts", [])),
                    )
                )
        for path in state.rglob("request.json"):
            request = read(path)
            if "wire_user_json" not in request:
                continue
            probe = object.__new__(OpenAIProbe)
            probe.response_policy = {}
            body = probe.request_body(
                request["wire_system"],
                request["wire_user_json"],
                request_id=path.parent.name,
                max_tokens=request["request"]["max_tokens"],
                json_mode=True,
            )
            size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
            assert size <= 16384
            data = json.loads(request["wire_user_json"]).get("untrusted_document_data", {})
            wires.append(
                dict(
                    company=company,
                    request_id=path.parent.name,
                    bytes=size,
                    budget=data.get("interpretation_budget"),
                )
            )
        results[company] = dict(
            claims=len(tag["claims"]),
            completion=tag.get("completion"),
            source_sha256=graph.source_sha256,
            measured_policy_sha256=canonical_hash(selected_policy),
        )

    def element(company, match, elem):
        selected = [c for c in cases if c["company"] == company and match in c["quote"]]
        assert len(selected) == 1, (company, match, len(selected))
        return next(e for e in selected[0]["elements"] if e["element_id"] == elem)

    focal = dict(
        board_m1=element("hyundai", "이사회는", "M1"),
        committee_m1=element("hyundai", "C-level", "M1"),
        ccs_m4=element("posco", "CCS 사업화 추진반을", "M4"),
        ccs_m2=element("posco", "CCS 사업화 추진반을", "M2"),
    )
    sk = [
        c
        for c in cases
        if c["company"] == "sk"
        and "지속할 계획" in c["quote"]
        and "대체가스 개발 및 양산 적용" in c["quote"]
    ]
    solar = [
        c
        for c in cases
        if c["company"] == "posco"
        and "포항" in key((c.get("sentence_context") or {}).get("text", c["quote"]))
    ]
    gates = dict(
        three_elements=all(
            focal[k]["state"] == "present" for k in ("board_m1", "committee_m1", "ccs_m4")
        ),
        sk_extraction=len(sk) == 1,
        posco_m2=focal["ccs_m2"]["state"] == "unknown",
        no_unproven_solar_g4=bool(solar) and not any("G4" in c["present"] for c in solar),
        naver_kia_no_regression=not any(loss["company"] in ("naver", "kia") for loss in losses),
        failure_free=not failures,
        source_free=not any(a["false_verified"] for a in audits),
    )
    gold = read(LAB / "fix/G1/DL4-gold.json")["golds"]
    before, after = [], []
    for company in ("naver", "kia"):
        before.extend(
            p | dict(company=company) for p in read(LAB / f"fix/K7/A-linux/{company}-after.json")
        )
        after.extend(p | dict(company=company) for p in read(OUT / f"A-linux/{company}-after.json"))
    dl4 = dict(before=scorer.evaluate(gold, before), after=scorer.evaluate(gold, after))
    holdout = read(OUT / "holdout/holdout-scores.json")
    gates["dl4_non_decrease"] = all(
        dl4["after"][k] >= dl4["before"][k] for k in ("precision", "recall")
    )
    gates["holdout_non_decrease"] = all(
        holdout["scores"]["after"][k] >= holdout["scores"]["before"][k]
        for k in ("precision", "recall")
    )
    assert not Counter((p["page"], p["quote"]) for p in before) - Counter(
        (p["page"], p["quote"]) for p in after
    )
    report = dict(
        companies=results,
        focal=focal,
        sk_plan=sk,
        solar=solar,
        regressions=losses,
        failures=failures,
        source_audit=audits,
        wire_requests=wires,
        wire_max_bytes=max(w["bytes"] for w in wires),
        cases=cases,
        dl4=dl4,
        holdout=holdout["scores"],
        gates=gates,
        accepted=all(gates.values()),
        full_replacement_accepted=all(gates.values()) and not losses,
        measurement_scope="V2 focal pages; V3 controls; extra guidance on literal insulation only",
        policy_sha256=canonical_hash(policy),
        scope="bounded canary and frozen-selection replay; no whole-report accuracy claim",
    )
    (OUT / ("B-summary-v1.json" if args.phase == "v1" else "B-summary.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            dict(gates=gates, max_bytes=report["wire_max_bytes"], companies=results),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
