"""Versioned semantic guidance and display-only QI1 hold explanations."""

from proofops.domain.provenance import canonical_hash

ELEMENT_DEFINITIONS = """
QI1 guidance: original v2.0 §4.4/4.5 and docs/28, no new grade rules.
M1 = named means OR concrete implementation state. Intent, consideration,
exploration, possibility, opportunity recognition or intent to make a plan alone
is not M1. Synthetic positives: '솔빛은 폐열 회수 설비를 가동 중이다.';
'들샘은 ISO 50001 에너지관리시스템을 운영한다.'
Synthetic negatives: '친환경 대안을 검토하고 도입 방안을 모색한다.';
'신기술로 시장을 개척할 수 있다는 기회를 인식한다.';
'앞으로 감축 계획을 수립하고자 다양한 노력을 기울일 것이다.'
M2 = applicable organization, facilities, division or legal entity boundary.
Time horizons, risk types, materials or quantities alone are not M2.
Synthetic positives: '국내 세 생산공장에 적용한다.'; '포장사업부와 연결법인이 적용 대상이다.'
Synthetic negatives: '단기 2년, 장기 8년으로 분석한다.';
'물리적 위험과 전환 위험을 관리한다.'; '폐용제 전량 45톤을 처리한다.'
P2 = explicit comparison baseline (previous-year/base-year comparison).
A reporting year alone is not P2. Synthetic positives: '전년 대비 전력량을 9% 줄였다.';
'2021년 기준값 대비 취수량을 18% 감축했다.'
Synthetic negatives: '전력 사용량 760MWh(2023)'; '2022년 보고서에 재활용량을 공시했다.'
Examples are fictional guidance, never evidence. Unsupported elements remain
unknown; no absence authority or ladder threshold changes.
""".strip()
ELEMENT_DEFINITIONS_HASH = canonical_hash(ELEMENT_DEFINITIONS)

# Element sets from the explicit original ladder, not additional rubric requirements.
LADDER = {
    "goal": (
        ("E1", ("G1", "G2")),
        ("E2", ("G1", "G2", "G3", "G4")),
        ("E3", ("G1", "G2", "G3", "G4", "G5", "G6")),
    ),
    "performance": (("E1", ("P1",)), ("E2", ("P1", "P2", "P3")), ("E3", ("P1", "P2", "P3", "P4"))),
    "management": (("E1", ("M1",)), ("E2", ("M1", "M2")), ("E3", ("M1", "M2", "M3"))),
}


def hold_projection(item, *, profile=None):
    """Explain an uninformative whole-pack range without changing facts or grades."""
    if profile == "v3-dec92-v1":
        from proofops.application.tagging.v3_dec92 import hold_projection as v3_hold

        return v3_hold(item)
    if profile == "k2-v1":
        return _cause_specific_hold(item)
    result = item["provisional_grade"]
    bounds = result.get("grade_range") or {}
    if result.get("evidence_grade") or (bounds.get("floor"), bounds.get("ceiling")) != ("E0", "E3"):
        return result
    track = (item.get("frozen_packet") or {}).get("track")
    tracks = [track] if track in LADDER else []
    if not tracks:
        for record in item.get("preliminary_records", []):
            candidate = ((record.get("values") or {}).get("track") or {}).get("track")
            if candidate in LADDER and candidate not in tracks:
                tracks.append(candidate)
    # A fallback checklist is explicitly conditional, never a track decision.
    if not tracks:
        tracks = list(LADDER)
    present = {e["element_id"] for e in result.get("elements", []) if e["state"] == "present"}
    reasons = []
    if (item.get("source_status") or {}).get("status") != "verified":
        reasons.append("원문 미검증")
    if profile in ("hf1-v1", "dec24-v1"):
        runs = item.get("tag_runs", [])
        if any(
            any(e.startswith("TAGGING_EVIDENCE_ID_") for e in run.get("errors", []))
            or any(
                w.startswith("CITATION_RESTORE_UNRESOLVED:")
                for w in (run.get("guarded") or {}).get("warnings", [])
            )
            for run in runs
        ):
            reasons.append("인용 복원 실패")
        if result.get("reason") == "REPLICA_HEADER_UNRESOLVED":
            reasons.append("replica 미해결")
    if track not in LADDER:
        reasons.append("트랙 미합의")
    if result.get("gap_ids") if profile in ("hf1-v1", "dec24-v1") else bounds.get("rule_gap"):
        reasons.append("규칙 미정")
    if profile == "dec24-v1" and "GAP-001" in result.get("gap_ids", []):
        from proofops.application.tagging.dec24 import ESTIMATE_HOLD

        category = (item.get("frozen_packet") or {}).get("safe_harbor_category")
        if category in ("forward_looking", "emissions_estimate"):
            if set(result["gap_ids"]) == {"GAP-001"}:
                reasons = [reason for reason in reasons if reason != "규칙 미정"]
            reasons.append(ESTIMATE_HOLD)
    if not present:
        reasons.append("근거 없음")
    return result | dict(
        display_type="hold",
        display="판정 보류",
        hold_reasons=reasons,
        hold_reason_detail=item.get("reason") or result.get("reason"),
        evidence_note=(
            "근거 없음은 이 패킷에 인정된 근거가 없다는 뜻이며 " "문서 전체 부재 판정이 아닙니다."
        ),
        needed_evidence=[
            dict(
                track=t,
                target_grade=grade,
                elements=[eid for eid in elements if eid not in present],
            )
            for t in tracks
            for grade, elements in LADDER[t]
            if any(eid not in present for eid in elements)
        ],
    )


def _cause_specific_hold(item):
    result = hold_projection(item, profile="dec24-v1")
    codes = {
        (record.get("stable_reason") or {}).get("error_code")
        for key in ("preliminary_records", "relation_records")
        for record in item.get(key, [])
    }
    codes.add(item.get("reason"))
    for run in item.get("tag_runs", []):
        codes.update(run.get("errors", []))
    if (
        "Q1_FORWARD_LOOKING_CATEGORY_REVIEW" in codes
        or result.get("reason") == "Q1_FORWARD_LOOKING_CATEGORY_REVIEW"
    ):
        return result | dict(
            evidence_grade=None,
            label=None,
            grade_range=None,
            grade_basis="retag_required",
            display_type="hold",
            display="미래 전망 · 가정·시나리오 검토 필요",
            hold_reasons=["미래 전망의 일반 성과등급 보류", "세이프하버 범주·가정·한계 확인 필요"],
            safe_harbor_candidate="forward_looking",
            gap_ids=["GAP-001", "GAP-002"],
        )
    if result.get("display_type") != "hold" or result.get("evidence_grade"):
        return result
    reasons = [r for r in result.get("hold_reasons", []) if r != "근거 없음"]
    display_failed = "DISPLAY_QUOTE_UNRESOLVED" in codes or any(
        (record.get("values") or {}).get("dimension_restore_errors")
        for record in item.get("preliminary_records", [])
    )
    if display_failed or "인용 복원 실패" in reasons:
        reasons = [r for r in reasons if r not in {"트랙 미합의", "인용 복원 실패"}]
        reasons.append("원문 위치 확인 필요")
    if "원문 미검증" in reasons:
        reasons = ["원문 위치 확인 필요" if r == "원문 미검증" else r for r in reasons]
    if any(
        c and c.startswith(("TAGGING_EVIDENCE_ID_", "TRACK_CATEGORY_CHANGED", "LLM_SCHEMA_INVALID"))
        for c in codes
    ):
        reasons.append("태깅 불일치")
    unresolved = result.get("unresolved_elements") or [
        e["element_id"] for e in result.get("elements", []) if e["state"] in {"unknown", "conflict"}
    ]
    if unresolved:
        reasons.append("미확인 요소: " + ", ".join(unresolved))
    if not reasons:
        reasons.append("미확인 · 태깅 결과 확인 필요")
    return result | dict(
        hold_reasons=list(dict.fromkeys(reasons)),
        evidence_note="미확인·위치 확인·태깅 불일치는 문서 전체의 근거 부재 판정이 아닙니다.",
    )
