"""Zero-cost MC search comparison; never imports gold facts into product evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from proofops.adapters.local.missing_evidence import document_search
from proofops.application.evidence.missing import SEARCH_PROFILE_HASH, search_elements


def evaluate(gold: Path, output: Path, baseline: Path | None = None):
    output.mkdir(parents=True, exist_ok=True)
    draft = json.loads((gold / "evidence-search-draft.json").read_text())
    sources = json.loads((gold / "sources.json").read_text())
    hidden = {
        t["claim_id"]
        for t in json.loads((gold / "team-bundle/review-tasks.json").read_text())["tasks"]
        if t["ai_draft_hidden"]
    }
    assert len(draft["claims"]) == 45
    assert not hidden & {c["claim_id"] for c in draft["claims"]}
    documents = {}
    for company in sorted({c["company_id"] for c in draft["claims"]}):
        source = sources[company]
        document = document_search(
            Path(source["pdf_path"]).read_bytes(),
            identity=dict(
                company_id=company, source_sha256=source["sha256"], page_count=source["page_count"]
            ),
        )
        documents[company] = document
        (output / f"{company}-document-search.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )
    comparisons, recoveries, results = [], [], {}
    for claim in draft["claims"]:
        document = documents[claim["company_id"]]
        # No product tag/citation/binding receipts exist for these draft-only ids.
        # Cold search must not accept provisional AI annotations as present.
        rows = search_elements(
            track=claim["track"],
            claim_quote=claim["atomic_proposition"],
            document=document,
            elements=[],
            confirmed_refs={},
            candidate_refs={},
        )
        results[claim["claim_id"]] = rows
        expected_elements = {e["element_id"]: e for e in claim["elements"]}
        for row in rows:
            expected = expected_elements[row["element_id"]]
            state = expected["applied_state"]
            expected_status = "confirmed" if state == "present" else "undetermined"
            comparisons.append(
                dict(
                    claim_id=claim["claim_id"],
                    element_id=row["element_id"],
                    ai_draft_status=expected_status,
                    product_status=row["evidence_status"],
                    matches=expected_status == row["evidence_status"],
                )
            )
            refs = list(expected["evidence_refs"])
            refs.extend(r for c in expected["candidates"] for r in c["evidence_refs"])
            refs.extend(expected.get("supporting_partial_refs", []))
            unique = {(r["physical_page"], r["quote"]): r for r in refs}
            hit_pages = {h["page_num"] for h in row["search"]["hits"]}
            matching_candidates = [
                c for c in row["search"]["native_candidates"] if c["linkage"] == "matched"
            ]
            for (page, quote), ref in unique.items():
                pattern = r"\s*".join(re.escape(ch) for ch in quote if not ch.isspace())
                text = document["page_texts"].get(str(page), "")
                native_match = re.search(pattern, text, re.I)
                found = bool(native_match)
                in_preview = any(
                    c["page_num"] == page and re.search(pattern, c["quote"], re.I)
                    for c in matching_candidates
                )
                location_overlap = native_match is not None and any(
                    c["page_num"] == page
                    and c["char_start"] < native_match.end()
                    and native_match.start() < c["char_end"]
                    for c in matching_candidates
                )
                recoveries.append(
                    dict(
                        claim_id=claim["claim_id"],
                        element_id=row["element_id"],
                        page_num=page,
                        quote=quote,
                        quote_found=found,
                        element_page_routed=page in hit_pages,
                        recovered=found and page in hit_pages,
                        candidate_a_full_quote=bool(in_preview),
                        candidate_a_location_overlap=bool(location_overlap),
                    )
                )
    summary = dict(
        dataset="provisional_ai_draft_not_human_accuracy",
        profile_sha256=SEARCH_PROFILE_HASH,
        claims=len(results),
        companies=dict(Counter(c["company_id"] for c in draft["claims"])),
        pages=sum(d["coverage"]["page_count"] for d in documents.values()),
        element_comparisons=len(comparisons),
        three_state_matches=sum(c["matches"] for c in comparisons),
        three_state_match_rate=sum(c["matches"] for c in comparisons) / len(comparisons),
        ai_evidence_refs=len(recoveries),
        recovered_refs=sum(r["recovered"] for r in recoveries),
        evidence_recovery_rate=sum(r["recovered"] for r in recoveries) / len(recoveries),
        literal_quote_recovery=sum(r["quote_found"] for r in recoveries),
        false_promotions=sum(
            r["evidence_status"] == "confirmed" for rows in results.values() for r in rows
        ),
        unauthorized_unknown_to_absent=sum(
            r["engine_state"] != "unknown" for rows in results.values() for r in rows
        ),
        product_statuses=dict(
            Counter(r["evidence_status"] for rows in results.values() for r in rows)
        ),
        undetermined_subreasons=dict(
            Counter(r["undetermined_reason"] for rows in results.values() for r in rows)
        ),
        candidate_a_full_quote_refs=sum(r["candidate_a_full_quote"] for r in recoveries),
        candidate_a_full_quote_rate=sum(r["candidate_a_full_quote"] for r in recoveries)
        / len(recoveries),
        candidate_a_location_overlap_refs=sum(
            r["candidate_a_location_overlap"] for r in recoveries
        ),
        readability={
            company: dict(
                readable_text_pages=len(d["coverage"]["readable_pages"]),
                unresolved_pages=d["coverage"]["unreadable_pages"],
                image_dominant_pages=d["coverage"]["image_dominant_unreadable_pages"],
                prior_unresolved_pages=(
                    json.loads((baseline / f"{company}-document-search.json").read_text())[
                        "coverage"
                    ]["unreadable_pages"]
                    if baseline
                    else None
                ),
            )
            for company, d in documents.items()
        },
        limit="Cold search has no product-validated tags. AI provisional present is not admitted."
        " Recall measures exact native quote plus element page routing, not semantic binding.",
        paid_api_calls=0,
        pdf_external_uploads=0,
    )
    for name, data in (
        (
            "comparison.json",
            dict(summary=summary, comparisons=comparisons, evidence_recovery=recoveries),
        ),
        ("element-search-results.json", dict(profile_sha256=SEARCH_PROFILE_HASH, results=results)),
    ):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    evaluate(args.gold, args.output, args.baseline)
