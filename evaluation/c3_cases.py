"""Source-backed adverse extraction fixtures and bounded corpus screening, not gold accuracy."""

import json
import re
import sqlite3
from copy import deepcopy

from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.tagging.fact_assembly_c3 import POLICY_HASH, assemble, safety_reasons
from proofops.domain.provenance import canonical_hash

from evaluation.c3_activation import OUT, ROOT, case, write

LAB = ROOT / "outputs/agent-results/R108-redesign/lab"


def negatives():
    data = case()
    source = next(
        b.normalized_text
        for b in data["graph"].blocks
        if "LG화학의 환경경영시스템" in b.normalized_text
    )
    sentences = re.findall(r"[^.]+\.", source)
    conform = next(s.strip() for s in sentences if "부합" in s)
    unacquired = next(s.strip() for s in sentences if "미취득" in s)
    policy = next(s.strip() for s in sentences if "환경 관련 정책" in s)
    actual = json.loads((OUT / "lg-active-assembly.json").read_text())
    variants = [
        ("iso-conform", "nonpossession", conform, "M3", conform),
        ("iso-in-progress-unacquired", "nonpossession", unacquired, "M3", unacquired),
        ("adjacent-policy", "other_activity_entity_product", policy, "M3", policy),
        ("other-product", "other_activity_entity_product", source, "activity", "재활용 제품"),
        (
            "partial-to-all",
            "partial_scope_expansion",
            actual["statement_boundary"][0]["quote"],
            "boundary",
            "글로벌 전 생산 사업장",
        ),
        (
            "report-year-to-validity",
            "report_or_issue_date_as_validity",
            "2025",
            "period_kind",
            "explicit_current",
        ),
        ("body-scope-conflict", "body_certification_scope_conflict", unacquired, "conflict", None),
    ]
    results = []
    for name, group, quote, axis, value in variants:
        votes = deepcopy(actual["raw_receipts"])
        for v in votes:
            raw = v["raw"]
            if axis == "M3":
                raw["elements"]["M3"]["evidence"] = dict(source_index=0, quote=value)
            elif axis == "conflict":
                raw["elements"]["M3"] = dict(state="conflict", evidence=None)
            elif axis == "period_kind":
                raw["period_kind"] = value
            else:
                raw["dimensions"][axis] = dict(source_index=0, quote=value)
            # This is explicitly a mutated extraction fixture, not another model vote.
            v.update(
                provider="c3-source-adversarial-fixture",
                simulated=True,
                raw_sha256=canonical_hash(raw),
            )
            v.pop("vote_sha256")
            v["vote_sha256"] = canonical_hash(v)
        receipt = assemble(
            votes, **{k: data[k] for k in ("context", "graph", "packet", "rulepack")}
        ).to_dict()
        assert not receipt["candidate_auto_confirmed"] and not receipt["public_auto_confirmed"]
        results.append(
            dict(
                case_id=name,
                group=group,
                company="lg",
                physical_page=36,
                source_sha256=data["graph"].source_sha256,
                quote=quote,
                evaluation=(
                    "source-backed_adversarial_extraction_fixture; "
                    "not_live_negative_model_or_gold"
                ),
                proposed_interpretation=value,
                candidate_auto_confirmed=False,
                public_auto_confirmed=False,
                blockers=receipt["unresolved"],
                receipt_sha256=receipt["receipt_sha256"],
            )
        )
    # The report identifies absent natural withdrawal examples rather than inventing one.
    write(
        "negative-measurements.json",
        dict(
            groups=5,
            cases=results,
            false_confirmation_count=0,
            natural_withdrawal_source="not_found_in_selected_corpus",
            withdrawal_counterfactual_guard="tests/unit/test_c3_source_guards.py",
        ),
    )
    return results


def sqlite_artifacts(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return [
            json.loads(r[0])
            for r in db.execute("SELECT value FROM job_records WHERE kind='artifact'")
        ]


def main():
    negatives_result = negatives()
    assert not any(r["candidate_auto_confirmed"] for r in negatives_result)
    corpus, nominations = [], []
    for name, slug in (("lg", "B-lg-16w-8rps"), ("kakao", "C-kakao-16w-8rps")):
        folder = LAB / "perf/I9" / slug / "publication-final"
        extraction = json.loads((folder / "extract-checkpoint.json").read_text())
        claims = extraction["discovery"]["claims"]
        maps = list(folder.rglob("local-page-map.json"))
        mapping = json.loads(maps[0].read_text())
        write(f"{name}-original-page-map.json", mapping)
        corpus.append((name, claims, False, str(folder / "extract-checkpoint.json")))
        # Scan ALL selected parser pages, including evidence-only pages that have no claims.
        graph_path = next(iter_parser_artifacts(folder, "graph.json"))
        graph = read_parser_json(graph_path)
        blocks = graph.get("blocks", [])
        iso = [b for b in blocks if re.search(r"ISO\s*14001", b.get("normalized_text", ""), re.I)]
        write(
            f"{name}-all-page-screen.json",
            dict(
                parser_graph_sha256=canonical_hash(graph),
                selected_pages=sorted({b["page_num"] for b in blocks}),
                blocks_screened=len(blocks),
                iso_blocks=iso,
                method=(
                    "discovery only; block/parent text is never promoted to verified claim evidence"
                ),
            ),
        )
    for name in ("naver", "kia"):
        path = LAB / f"perf/PB5/{name}-result.json"
        value = json.loads(path.read_text())
        if "result" in value:
            value = value["result"]
        corpus.append((name, value["claims"], False, str(path)))
    path = LAB / "fix/H3/kt/state/state.sqlite3"
    extraction = next(d for d in sqlite_artifacts(path) if "discovery" in d)
    corpus.append(("H3-kt", extraction["discovery"]["claims"], True, str(path)))
    measurements = []
    for name, claims, simulated, origin in corpus:
        screened = []
        for claim in claims:
            quote = claim["quote"]
            if not (re.search(r"ISO\s*14001", quote, re.I) or "환경경영시스템" in quote):
                continue
            refs = claim.get("source_refs", [])
            original_pages = None
            if name in ("lg", "kakao"):
                from evaluation.c3_activation import c2_pilot

                native = json.loads((c2_pilot.E02 / f"{name}-native-discovery.json").read_text())
                literal = re.sub(r"\s+", "", quote)
                original_pages = [
                    int(p) for p, text in native.items() if literal in re.sub(r"\s+", "", text)
                ]
            raw = dict(
                elements={
                    "M3": dict(evidence=dict(quote=quote)),
                    "M2": dict(evidence=dict(quote=quote)),
                }
            )
            blockers = safety_reasons(quote, raw)
            if claim.get("source_quality") != "verified":
                blockers.append("CLAIM_SOURCE_UNVERIFIED")
            if simulated:
                blockers.append("SIMULATED_PUBLICATION_FORBIDDEN")
            # New C3 evidence requires re-tagging; old packets/votes stay frozen.
            blockers.append("C3_FROZEN_PACKET_INDEPENDENT_3_REPLICAS_REQUIRED")
            row = dict(
                company=name,
                claim_id=claim["claim_id"],
                quote=quote,
                physical_page=(
                    original_pages[0]
                    if original_pages and len(original_pages) == 1
                    else claim.get("original_page_num")
                    if original_pages is None
                    else None
                ),
                original_candidate_pages=original_pages,
                original_locator="native literal discovery; not source attestation"
                if original_pages is not None
                else "saved source",
                source_refs=refs,
                source_quality=claim.get("source_quality"),
                elements=claim.get("elements", []),
                source_artifact=origin,
                candidate_auto_confirmed=False,
                public_auto_confirmed=False,
                blockers=sorted(set(blockers)),
                status="discovery_nomination",
            )
            screened.append(row)
            nominations.append(row)
        measurements.append(
            dict(
                company=name,
                claims_screened=len(claims),
                iso_ems_nominations=len(screened),
                independently_assembled_candidates=0,
                public_auto_confirmed=0,
                simulated=simulated,
                source_artifact=origin,
            )
        )
    approved = json.loads((OUT / "lg-active-assembly.json").read_text())
    positive = dict(
        company="lg",
        claim_id=approved["identity"]["claim_id"],
        physical_page=36,
        source_sha256=approved["identity"]["original_sha256"],
        quote=approved["statement_boundary"][0]["quote"],
        source_refs=approved["statement_boundary"],
        elements=approved["derived_results"][0]["result"]["elements"],
        evidence=approved["derived_results"],
        receipt_sha256=approved["receipt_sha256"],
        candidate_auto_confirmed=True,
        public_auto_confirmed=True,
        status="R8_reviewed_active_candidate",
        basis="new actual API 3 replicas; same packet; source-guarded dimensions; pure Python E3",
    )
    write(
        "cases.json",
        dict(
            profile_policy_sha256=POLICY_HASH,
            negative_false_confirmation_count=0,
            generalization_stopped=False,
            active_candidates=[positive],
            discovery_nominations=nominations,
            measurements=measurements,
            negatives=negatives_result,
            generalization_limit=(
                "new atomic candidates beyond R8 remain discovery/retag_required; "
                "no invented missing facts or old vote reuse"
            ),
            independent_human_gold_validation="not_run",
        ),
    )
    print(
        json.dumps(
            dict(
                active_candidates=1,
                public_auto_confirmed=1,
                negative_false_confirmation_count=0,
                measurements=measurements,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
