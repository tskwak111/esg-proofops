"""Evaluate saved results against a frozen independent reference, never model input.

These are explicit field checks, not whole-document semantic accuracy or approval.
"""

import argparse
import html
import json
import re
from pathlib import Path

from evaluation.local_analysis_pipeline import SOURCE_HASH


def number(text):
    return re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))


def evaluate(result, reference):
    if result["runtime"]["source_sha256"] != reference["source_sha256"]:
        raise ValueError("REFERENCE_SOURCE_MISMATCH")
    rows = []
    for case in reference["cases"]:
        expected_numbers = number(case["value"])
        # Matching only identifies candidates for review; it is not semantic acceptance.
        candidates = [
            c
            for c in result["claims"]
            if c["page"] == case["page"] and all(v in number(c["quote"]) for v in expected_numbers)
        ]
        related = []
        if not candidates and len(expected_numbers) > 1:
            groups = {}
            for claim in result["claims"]:
                if claim["page"] == case["page"]:
                    groups.setdefault(claim["parser_source"]["key"], []).append(claim)
            for group in groups.values():
                matches = [
                    c
                    for c in group
                    if c["normalized"].get("value", {}).get("value") in expected_numbers
                ]
                if set(expected_numbers) <= {c["normalized"]["value"]["value"] for c in matches}:
                    candidates = matches
                    related = matches
                    break
        if case["unit"] in ("%", "GWh", "kWh"):
            candidates = [c for c in candidates if case["unit"] in c["quote"]]
        preferred = [
            c
            for c in candidates
            if c["normalized"].get("value", {}).get("value") in expected_numbers
        ]
        candidate = (preferred or candidates or [None])[0]
        if candidate is None:
            rows.append(dict(id=case["id"], expected=case, status="not_extracted", checks={}))
            continue
        fields = candidate["normalized"]
        actual_year = fields.get("year", {}).get("value")
        checks = dict(
            exact_native_quote=candidate["source_verified"],
            independent_parsers=candidate["crosscheck"]["status"] == "consensus",
            track=candidate["track"] == case["track"],
            year=actual_year == (str(case["year"]) if case["year"] is not None else None),
            primary_value=fields.get("value", {}).get("value") in expected_numbers,
            entity_present=fields.get("entity", {}).get("value") is not None,
            no_unapproved_final_grade=candidate["decision"]["evidence_grade"] is None,
        )
        rows.append(
            dict(
                id=case["id"],
                expected=case,
                status="candidate_matched",
                checks=checks,
                actual=dict(
                    quote=candidate["quote"],
                    normalized=fields,
                    crosscheck=candidate["crosscheck"],
                    dart=candidate["dart"],
                    related_atomic_claims=[
                        dict(quote=c["quote"], normalized=c["normalized"]) for c in related
                    ],
                ),
            )
        )
    return dict(
        source_sha256=SOURCE_HASH,
        authority=reference["authority"],
        scope="15 purposeful cases; numeric matching locates candidates only. "
        "entity_present is not entity correctness; footnotes/denominators require manual review.",
        extracted_matches=sum(r["status"] == "candidate_matched" for r in rows),
        cases=rows,
        stages=result["stages"],
        dart=result["dart"],
        vision=result["vision"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    result = result.get("body", result)
    reference = json.loads(Path(".local/naver-baseline/reference.json").read_text(encoding="utf-8"))
    report = evaluate(result, reference)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = []
    for row in report["cases"]:
        cells = [
            row["id"],
            row["expected"]["claim"],
            row["status"],
            json.dumps(row["checks"], ensure_ascii=False),
            json.dumps(
                {k: v.get("value") for k, v in row.get("actual", {}).get("normalized", {}).items()},
                ensure_ascii=False,
            ),
            row["expected"]["note"],
        ]
        rows.append("<tr>" + "".join("<td>" + html.escape(c) + "</td>" for c in cells) + "</tr>")
    page = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>NAVER 단계별 비교</title>
    <style>body{font:15px system-ui;max-width:1500px;margin:30px auto;padding:20px;color:#18362a}
    table{border-collapse:collapse;width:100%}
    td,th{border:1px solid #cbd9cf;padding:12px;text-align:left;vertical-align:top}
    td{max-width:400px;overflow-wrap:anywhere}th{background:#e9f3eb}</style>
    <h1>NAVER 2024 · 독립 기준과 시스템 결과 비교</h1>
    <p>이 기준은 분석자가 원문을 읽고 만든 15개 항목입니다.
    전문가 승인 정답셋이나 전체 보고서 정확도가 아닙니다.
    숫자 일치는 비교 대상을 찾는 용도이며, 사업장·분모·각주까지 맞다는 뜻은 아닙니다.
    false 항목과 누락을 그대로 표시합니다.</p>
    <table><thead><tr><th>항목</th><th>원문 기준</th><th>추출</th>
    <th>개별 검사</th><th>시스템 정규화</th><th>주의점</th></tr></thead><tbody>"""
    (args.out / "comparison.html").write_text(
        page + "".join(rows) + "</tbody></table></html>", encoding="utf-8"
    )
    print(
        json.dumps(
            dict(
                matches=report["extracted_matches"],
                total=len(report["cases"]),
                checks={
                    key: sum(r["checks"].get(key, False) for r in report["cases"])
                    for key in report["cases"][0]["checks"]
                },
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
