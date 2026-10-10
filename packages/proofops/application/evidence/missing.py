"""Read-only three-state evidence search. A search never supplies engine facts."""

from __future__ import annotations

import re
from collections.abc import Mapping

from proofops.application.evidence.element_queries import (
    ANCHOR_STOP_WORDS,
    CANDIDATE_POLICY,
    ELEMENT_TERMS,
    READABILITY_POLICY,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import MAPPINGS

LEGACY_SEARCH_PROFILE = "missing-evidence-whole-document-v2"
LEGACY_SEARCH_PROFILE_HASH = canonical_hash(
    {
        "profile": LEGACY_SEARCH_PROFILE,
        "terms": ELEMENT_TERMS,
        "algorithm": "literal-or-bm25-all-priority-v2",
        "readability": READABILITY_POLICY,
        "candidate_routing": CANDIDATE_POLICY,
        "anchor_stop_words": sorted(ANCHOR_STOP_WORDS),
    }
)
SEARCH_PROFILE = "missing-evidence-whole-document-v3"
WHOLE_DOCUMENT_POLICY = {
    "native_text_is_whole_page_review": False,
    "whole_page_review_required": True,
    "unresolved_images": "all-image-pages",
}
SEARCH_PROFILE_HASH = canonical_hash(
    {
        "profile": SEARCH_PROFILE,
        "native_search_policy_sha256": LEGACY_SEARCH_PROFILE_HASH,
        "whole_document_review": WHOLE_DOCUMENT_POLICY,
    }
)


def literal_hits(pages: Mapping[int, str], terms: list[str]) -> list[dict]:
    """Retain every whitespace-insensitive occurrence; original offsets, no top-k."""
    hits = []
    for term in terms:
        pattern = re.compile(r"\s*".join(re.escape(c) for c in term if not c.isspace()), re.I)
        for page, text in pages.items():
            for match in pattern.finditer(text):
                hits.append(
                    dict(
                        page_num=page,
                        term=term,
                        char_start=match.start(),
                        char_end=match.end(),
                        quote=match.group(),
                    )
                )
    return sorted(hits, key=lambda h: (h["page_num"], h["char_start"], h["term"]))


def _compact(text: str) -> str:
    return "".join(text.casefold().split())


def claim_anchors(quote: str) -> dict[str, list[str]]:
    """Literal routing clues only: absence of a role never invents a value."""
    periods = sorted(set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", quote)))
    scopes = sorted(
        set(
            re.findall(
                r"Scope\s*[123](?:\s*[·/&]\s*[123])*|국내|해외|전사|연결|별도|"
                r"[가-힣A-Za-z0-9-]+(?:사업장|공장|법인|센터)",
                quote,
                re.I,
            )
        )
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*|[가-힣]{2,}", quote)
    metrics = set()
    for token in tokens:
        token = re.sub(
            r"(?:에서는|으로|에서|까지|부터|에게|에는|은|는|을|를|의|에|와|과)$", "", token
        )
        if (
            len(token) >= 2
            and token not in ANCHOR_STOP_WORDS
            and token.casefold() != "scope"
            and not re.fullmatch(r"tCO2(?:eq|e)?|MWh|GWh|MW|kWh|kg|tons|tonnes", token, re.I)
            and not token.endswith(("합니다", "있습니다", "했습니다", "하고", "하여", "하며"))
            and token not in scopes
            and not token.isdigit()
        ):
            metrics.add(token)
    distinctive = sorted(
        token
        for token in metrics
        if re.search(r"[A-Za-z]", token)
        or len(token) >= CANDIDATE_POLICY["distinctive_korean_min_chars"]
    )
    return dict(
        metric=sorted(metrics), metric_distinctive=distinctive, period=periods, boundary=scopes
    )


def native_candidate_windows(
    pages: Mapping[int, str], hits: list[dict], quote: str
) -> tuple[list[dict], dict]:
    """Same-window anchors route review candidates, never a semantic join.

    Synonym-only hits are background text, not claim candidates. A shared metric
    with absent/conflicting explicit period/boundary is kept as rejected linkage.
    A shared numeric unit without a metric is retained as a metric mismatch.
    """
    anchors = claim_anchors(quote)
    units = re.findall(r"\b(?:tCO2(?:eq|e)?|MWh|GWh|MW|kWh|kg|tonnes|tons)\b|%", quote, re.I)
    required = min(CANDIDATE_POLICY["required_metric_anchors_max"], len(anchors["metric"]))
    candidates = {}
    for hit in hits:
        text = pages[hit["page_num"]]
        size = CANDIDATE_POLICY["preview_chars"]
        start = max(0, hit["char_start"] - size // 2)
        end = min(len(text), start + size)
        start = max(0, end - size)
        preview = text[start:end]
        compact = _compact(preview)
        matched = {
            axis: [term for term in terms if _compact(term) in compact]
            for axis, terms in anchors.items()
        }
        distinctive_ok = not anchors["metric_distinctive"] or bool(matched["metric_distinctive"])
        metric_ok = bool(required) and len(matched["metric"]) >= required and distinctive_ok
        same_unit = any(_compact(unit) in compact for unit in units)
        if (not matched["metric"] or not distinctive_ok) and not same_unit:
            continue
        failures = []
        if not metric_ok:
            failures.append("지표·활동 앵커 불일치")
        if len(matched["period"]) != len(anchors["period"]):
            failures.append("기간 앵커 누락 또는 불일치")
        if len(matched["boundary"]) != len(anchors["boundary"]):
            failures.append("조직·사업장 범위 앵커 누락 또는 불일치")
        row = dict(
            page_num=hit["page_num"],
            char_start=start,
            char_end=end,
            quote=preview,
            matched_anchors=matched,
            linkage="matched" if not failures else "rejected",
            rejection_reason="; ".join(failures) or None,
            citation_verified=False,
            binding_accepted=False,
        )
        candidates[(hit["page_num"], start, end)] = row
    return list(candidates.values()), anchors


def search_elements(
    *,
    track: str | None,
    claim_quote: str,
    document: dict,
    elements: list[dict],
    confirmed_refs: dict[str, list[dict]],
    candidate_refs: dict[str, list[dict]],
) -> list[dict]:
    """Only the trusted caller's replayed citation/binding results can confirm.

    Document text and BM25 hits are diagnostics. Unapproved absence stays unknown,
    including when the UI reports a completed search miss. Conflict/N/A survive.
    """
    if track not in MAPPINGS:
        return []
    coverage = document["coverage"]
    text_by_page = {int(p): text for p, text in document["page_texts"].items()}
    order = coverage.get("search_order", sorted(text_by_page))
    pages = {p: text_by_page[p] for p in order if p in text_by_page}
    expected = list(range(1, coverage["page_count"] + 1))
    # Only explicitly pinned historical artifacts use the v2 reader semantics.
    # New/unstamped inputs fail closed without whole-page review evidence.
    legacy = document.get("profile_sha256") == LEGACY_SEARCH_PROFILE_HASH
    complete = (
        coverage["searched_pages"] == expected
        and coverage["readable_pages"] == expected
        and not coverage["unreadable_pages"]
        and not coverage["missing_pages"]
        and coverage.get("absence_readability_complete", legacy)
        and (legacy or coverage.get("whole_page_content_reviewed_pages") == expected)
    )
    anchors = sorted(set(re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9-]*|\d{4}", claim_quote)))
    anchor_hits = literal_hits(pages, anchors)
    tagged = {e["element_id"]: e for e in elements}
    result = []
    for element_id in MAPPINGS[track]:
        terms = ELEMENT_TERMS[element_id]
        hits = literal_hits(pages, terms)
        refs = confirmed_refs.get(element_id, [])
        candidates = candidate_refs.get(element_id, [])
        text_readable = set(coverage["readable_pages"])
        previews, role_anchors = native_candidate_windows(
            pages, [hit for hit in hits if hit["page_num"] in text_readable], claim_quote
        )
        matching = [row for row in previews if row["linkage"] == "matched"]
        rejected = [row for row in previews if row["linkage"] == "rejected"]
        state = tagged.get(element_id, {}).get("state", "unknown")
        if state == "present" and refs:
            status, reason = "confirmed", "CITATION_AND_BINDING_VALIDATED"
        elif (
            state not in ("conflict", "not_applicable", "present")
            and complete
            and not hits
            and not candidates
        ):
            status, reason = "not_found_in_report", "COMPLETE_SEARCH_NO_MATCH_DISPLAY_ONLY"
        else:
            status = "undetermined"
            reason = (
                "ELEMENT_CONFLICT"
                if state == "conflict"
                else "ELEMENT_NOT_APPLICABLE"
                if state == "not_applicable"
                else "COVERAGE_INCOMPLETE"
                if not complete
                else "CANDIDATE_LINKAGE_UNRESOLVED"
            )
        subreason: str | None = (
            "candidate_needs_review"
            if matching
            else "linkage_unclear"
            if rejected
            else "no_text_candidate"
        )
        if state in ("conflict", "not_applicable", "present") and status != "confirmed":
            subreason = "linkage_unclear"
        if status != "undetermined":
            subreason = None
        outside_pages = sorted(
            {h["page_num"] for h in hits} - set(document.get("selected_pages", pages))
        )
        scope_note = (
            "선택 범위 밖 후보는 정밀 파싱·원문 및 주장 연결 검증이 필요합니다."
            if outside_pages and not refs
            else "판독불가·미해결 쪽이 있어 보고서 전체의 부재를 확정할 수 없습니다."
            if not complete
            else "문서 전체 검색 완료; 검색 결과만으로 엔진 입력을 변경하지 않습니다."
        )
        if not hits and not complete:
            searched = coverage["searched_pages"]
            scope_note = (
                "검색 범위("
                + ", ".join(map(str, searched))
                + "쪽)에서 찾지 못함 · 판독 미완결; 엔진 입력 unknown 유지"
            )
        candidate_outside = sorted(
            {c["page_num"] for c in previews} - set(document.get("selected_pages", pages))
        )
        if subreason == "no_text_candidate":
            scope_note = (
                f"읽을 수 있는 텍스트 {len(coverage['readable_pages'])}쪽 전체에서 "
                "이 주장과 연결되는 후보를 찾지 못했습니다. "
                "사진·도식의 문구와 미판독 쪽은 미확인이며, 보고서 부재 판정이 아닙니다."
            )
        elif subreason == "linkage_unclear" and rejected:
            scope_note = "연결 거절: " + rejected[0]["rejection_reason"]
        elif subreason == "candidate_needs_review":
            scope_note = (
                "같은 검색어가 함께 보이는 native 후보이며, 인용·의미 연결은 미검증입니다. "
                + (
                    "선택 범위 밖은 정밀 파싱이 필요합니다."
                    if candidate_outside
                    else "원문 확인이 필요합니다."
                )
            )
        result.append(
            dict(
                element_id=element_id,
                evidence_status=status,
                engine_state=state,
                reason=reason,
                undetermined_reason=subreason,
                evidence_refs=refs,
                candidate_refs=candidates,
                search=dict(
                    profile=LEGACY_SEARCH_PROFILE if legacy else SEARCH_PROFILE,
                    profile_sha256=LEGACY_SEARCH_PROFILE_HASH if legacy else SEARCH_PROFILE_HASH,
                    document_search_sha256=document["artifact_sha256"],
                    coverage=coverage,
                    priority_scopes=document.get("priority_scopes", []),
                    scope_note=scope_note,
                    outside_selected_pages=outside_pages,
                    candidate_outside_selected_pages=candidate_outside,
                    terms=terms,
                    claim_anchor_terms=anchors,
                    hits=hits,
                    joint_hit_pages=sorted(
                        {h["page_num"] for h in hits} & {h["page_num"] for h in anchor_hits}
                    ),
                    candidate_count=len(matching),
                    rejected_candidate_count=len(rejected),
                    native_candidates=previews,
                    role_anchors=role_anchors,
                    unresolved_image_pages=coverage.get(
                        "image_dominant_unreadable_pages" if legacy else "image_pages", []
                    ),
                    truncated=False,
                    absence_admissible=False,
                ),
            )
        )
    return result
