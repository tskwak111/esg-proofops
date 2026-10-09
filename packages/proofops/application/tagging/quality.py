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


def hold_projection(item):
    """Explain an uninformative whole-pack range without changing facts or grades."""
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
    if track not in LADDER:
        reasons.append("트랙 미합의")
    if bounds.get("rule_gap"):
        reasons.append("규칙 미정")
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
