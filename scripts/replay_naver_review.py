"""Replay the exact reviewed cases with saved real data, without API calls."""

import html
import json
from collections import Counter
from pathlib import Path

from evaluation.local_analysis_pipeline import MANIFEST_HASH, SOURCE_HASH
from evaluation.local_review import REVIEW_SHA256, apply_review, review_chart
from evaluation.local_review_dart import compare_reviewed

ROOT = Path(__file__).resolve().parents[1]


def main():
    original = ROOT / ".local/copy-pipeline-verified/response.json"
    result = json.loads(original.read_text("utf-8"))["body"]
    for c in result["claims"]:
        assert apply_review(c, SOURCE_HASH, MANIFEST_HASH)
        c["dart"] = compare_reviewed(c, result["dart"])
    review_chart(result["vision"], SOURCE_HASH)
    result["dart"]["final_status"] = "reviewed_claim_results"
    result["dart"]["notice"] = (
        "기존에 수집한 실제 OFS 재무제표 + 공식 DART 표지 원문으로 재평가. "
        "이번 재평가에서 API 재무제표를 새로 수집한 것은 아님."
    )
    result["stages"] = []
    summary = dict(
        reviewed_claims=len(result["claims"]),
        accepted_facts=sum(
            sum(e["state"] == "present" for e in c["elements"]) for c in result["claims"]
        ),
        ranges=sum(bool(c["decision"]["grade_range"]) for c in result["claims"]),
        final_grades=sum(bool(c["decision"]["evidence_grade"]) for c in result["claims"]),
        dart_checks={
            item: dict(
                Counter(
                    ch["status"]
                    for c in result["claims"]
                    for ch in c["dart"]["checks"]
                    if ch["item"] == item
                )
            )
            for item in ("C1", "C2", "C3", "C4")
        },
        review_sha256=REVIEW_SHA256,
    )
    out = ROOT / ".local/final-review"
    (out / "result-current.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), "utf-8"
    )
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    rows = []
    labels = {
        "matched": "기간 일치",
        "not_applicable": "비적용",
        "review_required": "추가 근거 필요",
    }
    for c in result["claims"]:
        grade = c["decision"]["grade_range"]
        grade_text = (
            f"{grade['floor']}~{grade['ceiling']} (가능 범위)" if grade else "단위 이상 · 보류"
        )
        cells = [str(c["page"]), c["quote"], grade_text]
        cells += [labels.get(ch["status"], ch["status"]) for ch in c["dart"]["checks"]]
        rows.append("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in cells) + "</tr>")
    content = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>NAVER 원문 검토·정책 승인 결과</title>
<style>body{font:16px/1.7 system-ui;max-width:1280px;margin:40px auto;padding:20px;color:#173329}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid #cdddce;padding:12px;text-align:left}
th{background:#edf5ef}small{color:#53645a}a{color:#17593d}</style>
<h1>NAVER 원문 검토·정책 승인 결과</h1>
<p>복사본 전용 · 프로젝트 기준의 AI 위임 검토 · 전문가 정답/법적 승인 아님.</p>
<p>32개 주장 검토, 명시 근거 75개 확인. 31개 E1~E3 가능 범위, LNG 단위 이상 1개 보류.
최종 등급을 확정하려면 비교기준·목표의 기준연도/값 등 미확인 요소를 추가 확인해야 합니다.</p>
<p>201쪽 610/927의 행 분류를 원문으로 확인했습니다. 213쪽 사업별 감축량 합계로
11,155·11,433·30,925를 확인하고, 적용 방법론·보증 범위를 연결했습니다.
78%와 65%의 분모를 분리하고 PUE의 무차원 단위를 반영했습니다.</p>
<p>DART: 아래 기간 일치 3건은 213쪽과 공식 사업보고서 표지를 비교한 결과입니다.
비적용은 일치나 통과를 뜻하지 않습니다.
C3 투자금액·C4 분류 매출 비중은 해당 주장이 없어 실행하지 않았습니다.</p>
<p><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250318000645">DART 사업보고서 원문</a>
 · <a href="review-v4.json">승인·원문 검토 기록</a>
 · <a href="result-current.json">시스템 재평가 결과</a></p>
<p>남은 사항: 법인·시설 범위의 재무 연결, 미확인 기간, 비교기준과 목표 요소, LNG m² 단위,
51.6↔51 표시 정밀도. 전체 127개 표를 승인한 결과는 아닙니다.</p>
<table><thead><tr><th>쪽</th><th>주장</th><th>근거 등급</th><th>C1 범위</th><th>C2 기간</th>
<th>C3 투자금액</th><th>C4 매출 분류</th></tr></thead><tbody>"""
    (out / "report.html").write_text(content + "".join(rows) + "</tbody></table></html>", "utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
