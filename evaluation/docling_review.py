"""Render local parser diagnostics as a searchable offline review table."""

import argparse
import json
from collections import Counter
from html import escape
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.manifest.parent
    audit = json.loads((root / "audit.json").read_bytes())
    states = {r["key"]: r["reason"] for r in audit}
    labels = dict(
        consensus="합의",
        parse_conflict="행·열·문맥 불일치",
        numeric_not_in_native_region="해당 원문 영역에 숫자 없음",
        chart_requires_vision_review="차트 이미지 검토 필요",
        superseded_by_enhanced="enhanced로 대체",
        not_numeric="수치 대조 대상 아님",
        invalid_text_control_character="원문 제어문자 확인 필요",
        table_grid_overlap="셀 병합 범위 겹침",
        crosscheck_missing="독립 결과 없음",
    )
    rows = []
    for batch in json.loads((root / "candidates.json").read_bytes()):
        for block in batch["blocks"]:
            s = block["source"]
            status = states[s["parser_run_id"] + "/" + s["source_native_id"]]
            cells = [
                s["physical_page"],
                batch["parser_name"],
                block["kind"],
                labels.get(status, status),
                f"{block['row_number']} / {block['column_number']}",
                s["raw_text"],
                s["native_bbox"],
            ]
            rows.append(
                "<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in cells) + "</tr>"
            )
    counts = Counter(r["reason"] for r in audit)
    summary = " · ".join(f"{labels.get(k,k)} {v}" for k, v in counts.items())
    page = """<!doctype html><meta charset="utf-8"><title>파서 대조 검토</title>
<style>body{font:15px system-ui;margin:24px;color:#17212f}input{padding:10px;width:80%}
table{border-collapse:collapse;width:100%;margin-top:20px}
td,th{border:1px solid #ccd4df;padding:8px;text-align:left;vertical-align:top}
th{position:sticky;top:0;background:#edf4ff}td:nth-child(6){white-space:pre-wrap;min-width:300px}
tr:nth-child(even){background:#f6f8fb}</style><h1>Docling · Upstage 대조 검토</h1>
<p>행 번호와 열 번호는 0부터 시작합니다. 합의는 파서 결과의 일치이며 사실·정책 승인과 다릅니다.</p>
<p>COUNT</p><label>페이지·문구·상태 검색 <input id="q" placeholder="예: 30,925 또는 합의"></label>
<table><thead><tr><th>쪽</th><th>파서</th><th>종류</th><th>결과</th><th>행 / 열</th>
<th>추출 원문</th><th>PDF 좌표</th></tr></thead><tbody>ROWS</tbody></table>
<script>document.getElementById('q').addEventListener('input',e=>{
const q=e.target.value.toLowerCase();document.querySelectorAll('tbody tr')
.forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});</script>"""
    args.output.write_text(
        page.replace("COUNT", escape(summary)).replace("ROWS", "".join(rows)), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
