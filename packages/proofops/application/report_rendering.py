"""JSON, CSV and HTML serialization of immutable report projections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from csv import writer
from html import escape
from io import StringIO

from proofops.domain.rulepacks import canonical_json


def render_report(model: Mapping[str, object], output_format: str) -> bytes:
    """Render fixed report data with stdlib-only output escaping."""
    from proofops.application import reporting

    _element_label = reporting._element_label
    _element_states = reporting._ELEMENT_STATES

    if not isinstance(model, Mapping) or model.get("schema") != "report_model_v1":
        raise ValueError("report_model_v1 is required")
    from proofops.application.element_evidence_encoding import ELEMENT_EVIDENCE_V1

    if model.get("element_evidence_encoding") not in (None, ELEMENT_EVIDENCE_V1):
        raise ValueError("unsupported element evidence encoding")
    if output_format == "json":
        # Keep the canonical legacy key order, then append the optional MC key.
        # Old snapshots render byte-for-byte as before; no hash encoding changes.
        ordered = json.loads(canonical_json(model))
        for claim in ordered.get("claims", []):
            if "element_evidence" in claim:
                claim["element_evidence"] = claim.pop("element_evidence")
        return json.dumps(
            ordered, ensure_ascii=True, separators=(",", ":"), allow_nan=False
        ).encode()
    claims = model.get("claims")
    if not isinstance(claims, list) or any(not isinstance(item, Mapping) for item in claims):
        raise ValueError("report claims are required")
    if output_format == "csv":
        fields: tuple[str, ...] = (
            "claim_id",
            "decision_status",
            "evidence_grade",
            "label",
            "review_status",
            "tag_revision",
            "decision_revision",
            "missing_elements",
            "unresolved_elements",
            "suggestion",
            "review_action",
            "source_pages",
            "source_quotes",
            "source_refs",
            "basis_refs",
            "assurance",
            "safe_harbor",
            "model_sha256",
            "prompt_sha256",
            "replicate_hashes",
            "rule_pack_sha256",
            "claim_quote",
            "classification_review",
            "tag_elements",
            "grade_range",
        )
        if any("sc1_confirmation" in claim for claim in claims):
            fields += ("sc1_confirmation", "sc1_elements", "sc1_hold_reason", "sc1_scope_receipt")
        if any("element_evidence" in claim for claim in claims):
            fields += ("element_evidence",)
        if "element_evidence_encoding" in model:
            fields += ("element_evidence_encoding", "element_evidence_manifest")
        stream = StringIO(newline="")
        rows = writer(stream)
        rows.writerow(fields)
        for claim in claims:
            sources = claim["source_refs"]
            values = {
                **claim,
                "source_pages": [source["page_num"] for source in sources],
                "source_quotes": "\n".join(source["quote"] for source in sources),
            }
            for field in ("element_evidence_encoding", "element_evidence_manifest"):
                if field in model:
                    values[field] = model[field]
            rows.writerow(reporting._csv_safe(values.get(field)) for field in fields)
        return stream.getvalue().encode()
    if output_format == "html":
        items = []
        for claim in claims:
            sources = (
                "".join(
                    f"<li>p.{source['page_num']}"
                    f" [{', '.join(str(value) for value in source['bbox'])}]"
                    f": {escape(source['quote'])}</li>"
                    if source["bbox"] is not None
                    else f"<li>p.{source['page_num']}: {escape(source['quote'])}</li>"
                    for source in claim["source_refs"]
                )
                or "<li>원문 근거 위치 미실행</li>"
            )
            grade_label = (
                f"{claim['evidence_grade']} / {claim['label']}"
                if claim["evidence_grade"] is not None
                else "미판정"
            )
            scoped = claim.get("sc1_confirmation")
            if scoped:
                scope = scoped["confirmation_scope"]
                grade_label += (
                    " · "
                    + str(scoped["evidence_grade"])
                    + " 분석 범위 기준 확정"
                    + " · 선택 물리 쪽 "
                    + str(scope["selected_pages"])
                    + " / 전체 "
                    + str(scope["document_total_pages"])
                    + "쪽"
                )
            grade_range = claim.get("grade_range")
            range_html = (
                f"<p>가능 등급 범위: {escape(grade_range['floor'])} ~ "
                f"{escape(grade_range['ceiling'])} (확정 등급 아님) · "
                "확인하면 범위가 좁혀지는 요소: "
                f"{escape(', '.join(map(_element_label, grade_range['open_elements'])))}</p>"
                if grade_range
                else ""
            )
            audit_details = escape(canonical_json(claim))
            empty_result = "미평가" if claim["decision_status"] == "not_run" else "없음"
            action = claim.get("review_action")
            if action:
                action_html = (
                    '<div class="review-action"><p>다음 검토 작업:</p><ul>'
                    + "".join(f"<li>{escape(check)}</li>" for check in action["checks"])
                    + "</ul></div>"
                )
            else:
                action_html = "<p>자동 생성된 후속 검토 안내 없음</p>"
            quote = claim.get("claim_quote") or "이전 스냅샷에 주장 문장이 저장되지 않았습니다"
            tag_elements = claim.get("tag_elements")
            if tag_elements is None:
                tag_html = "<p>태그 요소 미포함(이전 스냅샷)</p>"
            elif not tag_elements:
                tag_html = "<p>태그된 요소 없음(미태깅)</p>"
            else:
                present_parts = []
                candidate_parts = []
                other_parts = []
                for element in tag_elements:
                    value = element.get("normalized_value")
                    value_text = escape(value) if isinstance(value, str) else "기록 없음"
                    evidence_refs = element.get("evidence_refs", [])
                    quotes = (
                        "".join(
                            f"<li>p.{ref['page_num']}: {escape(ref['quote'])}</li>"
                            for ref in evidence_refs
                        )
                        or "<li>인용 없음</li>"
                    )
                    item_html = (
                        f"<li>{escape(_element_label(element['element_id']))}: "
                        f"{escape(_element_states.get(element['state'], element['state']))}"
                        f" ({escape(element['state'])}) · 값: {value_text}"
                        f"<ul>{quotes}</ul></li>"
                    )
                    if element["state"] == "present":
                        present_parts.append(item_html)
                    elif element["state"] in ("unknown", "conflict") and evidence_refs:
                        candidate_parts.append(item_html)
                    else:
                        other_parts.append(item_html)

                tag_html = ""
                if present_parts:
                    tag_html += (
                        "<h3>추출된 항목 (present)</h3><ul>" + "".join(present_parts) + "</ul>"
                    )
                if candidate_parts:
                    tag_html += (
                        "<h3>미해결 태그 요소 검토 후보</h3><ul>"
                        + "".join(candidate_parts)
                        + "</ul>"
                    )
                if other_parts:
                    tag_html += "<h3>기타 태그 요소</h3><ul>" + "".join(other_parts) + "</ul>"
            classification = claim.get("classification_review")
            evidence_html = ""
            if "element_evidence" in claim:
                status_labels = {
                    "confirmed": "✅ 확인됨",
                    "not_found_in_report": "⚠️ 보고서에서 찾지 못함",
                    "undetermined": "❔ 판단 불가",
                }
                evidence_parts = []
                for element in claim["element_evidence"]:
                    search = element["search"]
                    cov = search["coverage"]
                    subreason = element.get("undetermined_reason")
                    image_pages = cov.get(
                        "image_pages",
                        search.get(
                            "unresolved_image_pages", cov.get("image_dominant_unreadable_pages", [])
                        ),
                    )
                    image_count = len(image_pages)
                    label = status_labels[element["evidence_status"]]
                    if element["evidence_status"] == "undetermined":
                        label = {
                            "candidate_needs_review": "🔎 후보 있음·확인 필요",
                            "no_text_candidate": (
                                "⚠️ 텍스트로는 못 찾음" f"(이미지 쪽 {image_count}개 미확인)"
                            ),
                            "linkage_unclear": "❔ 연결 불명확",
                        }.get(subreason, label)
                    previews = "".join(
                        f"<li>{c['page_num']}쪽: {escape(c['quote'])}"
                        f" · {escape(c.get('rejection_reason') or '미검증 후보')}</li>"
                        for c in search.get("native_candidates", [])
                    )
                    shared_links = ""
                    if "element_evidence_encoding" in model:
                        references = search["__shared_search__"]["refs"]
                        shared_links = (
                            "<p>공통 검색 기록: "
                            + " · ".join(
                                f'<a href="manifest.json">{escape(field)} '
                                f"{escape(reference)}</a>"
                                for field, reference in references.items()
                            )
                            + " (인용·의미 연결 검증 상태는 원래 기록을 따릅니다)</p>"
                        )
                    evidence_parts.append(
                        "<li><strong>"
                        + escape(_element_label(element["element_id"]))
                        + " · "
                        + label
                        + "</strong>"
                        + "<p>검색한 쪽: "
                        + escape(canonical_json(cov["searched_pages"]))
                        + " · 텍스트 판독불가 쪽: "
                        + escape(canonical_json(cov["unreadable_pages"]))
                        + " · 이미지 내용 미확인 쪽: "
                        + escape(canonical_json(image_pages))
                        + f" ({image_count}개)"
                        + (
                            " · 전체 내용 판독 미완결 쪽: "
                            + escape(canonical_json(cov["unreviewed_content_pages"]))
                            if "unreviewed_content_pages" in cov
                            else ""
                        )
                        + " · 미검색 쪽: "
                        + escape(canonical_json(cov["missing_pages"]))
                        + "</p><p>검색어·동의어: "
                        + escape(", ".join(search["terms"]))
                        + "</p><p>"
                        + escape(search.get("scope_note", ""))
                        + "</p>"
                        + shared_links
                        + "<details><summary>미검증 native 후보</summary><ul>"
                        + previews
                        + "</ul></details>"
                        + "<details><summary>원문 근거·검색 기록</summary><pre>"
                        + escape(canonical_json(element))
                        + "</pre></details></li>"
                    )
                evidence_html = "<h3>부족 근거 카드</h3><ul>" + "".join(evidence_parts) + "</ul>"
            classification_html = ""
            if classification:
                origin = (
                    "AI 위임 분류(사람 검토 아님)"
                    if classification["origin"] == "ai_delegated_classification"
                    else "사람 분류 검토"
                )
                classification_html = (
                    f"<p>선행분류 기록: {origin} · {escape(classification['track'])} · "
                    f"revision {classification['revision']} (등급 승인 아님)</p>"
                )
            missing = ", ".join(map(_element_label, claim["missing_elements"])) or empty_result
            unresolved = (
                ", ".join(map(_element_label, claim["unresolved_elements"])) or empty_result
            )
            items.append(
                "<section>"
                f"<h2>검토 대상 주장</h2><p>{escape(quote)}</p>"
                f"<p>주장 ID: {escape(claim['claim_id'])}</p>{classification_html}"
                f"<p>판정: {escape(grade_label)} ({escape(claim['decision_status'])})</p>"
                f"{range_html}"
                f"<p>검토: {escape(claim['review_status'])} · "
                f"tag revision {claim['tag_revision']} · decision revision "
                f"{claim['decision_revision']}</p>"
                f"<p>결손: {escape(missing)} · "
                f"미해결: {escape(unresolved)} · "
                f"gaps: {escape(', '.join(claim['gap_ids']) or empty_result)}</p>"
                f"<p>{escape(claim.get('suggestion') or '확정된 수정 제안 없음')}</p>"
                f"{action_html}"
                f"<h3>원문 근거</h3><ul>{sources}</ul>"
                f"{tag_html}{evidence_html}"
                f"<details><summary>감사 세부정보</summary><pre>{audit_details}</pre></details>"
                "</section>"
            )
        status = "검토용 부분 리포트" if model.get("partial") else "완료 리포트"
        coverage_details = escape(canonical_json(model["coverage"]))
        return (
            '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>body{max-width:960px;margin:32px auto;padding:0 20px;'
            'font:16px/1.6 system-ui,sans-serif;color:#1e293b;background:#f8fafc}'
            'section{margin:20px 0;padding:20px;border:1px solid #cbd5e1;'
            'border-radius:6px;background:white;break-inside:avoid}'
            'h2{font-size:1.05rem}h2,li,pre{overflow-wrap:anywhere}'
            'pre{white-space:pre-wrap;font-size:.85rem}'
            'summary{cursor:pointer;padding:8px 0}li+li{margin-top:8px}'
            '.review-action{border-left:3px solid #0369a1;padding-left:16px}'
            '@media print{body{margin:0;background:white}section{border-radius:0}}'
            '</style>'
            f"<title>감사 리포트</title></head><body><h1>감사 리포트</h1><p>{status}</p>"
            f"<p>미완료 {model['unfinished_count']}건 · "
            f"미확인 조항 {model['unverified_clause_count']}건</p>"
            f"<details><summary>처리 범위</summary><pre>{coverage_details}</pre></details>"
            + "".join(items)
            + (
                '<section id="shared-element-search"><h2>공통 검색 기록</h2>'
                '<p><a href="manifest.json">검색 목록과 인용문 원문 표</a>: '
                "주장별 참조는 manifest의 element_evidence_lists와 "
                "element_evidence_quotes에서 복원할 수 있습니다. 문자 위치는 "
                "검색 원문의 좌표이며 PDF 바이트 위치가 아닙니다.</p></section>"
                if "element_evidence_encoding" in model
                else ""
            )
            + "</body></html>"
        ).encode()
    raise ValueError("output_format must be json, csv, or html")
