"""R19-T06/T08: no inferred achievements, foreign means or future completion."""

from dataclasses import replace

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.tagging.v3_context import accepts_context, augment_packet
from proofops.application.tagging.v3_dec92 import guard
from proofops.domain.values import LlmElement

from tests.acceptance.test_binding import span
from tests.unit.test_k5_context import case

MEANS = "가상기업은 환경투자 검토를 환경투자심의위원회 승인 절차로 운영합니다."
CLAIM = "가상기업은 환경투자 검토 체계를 갖추고 있습니다."


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "foreign_actor",
        "foreign_substring_actor",
        "different_block",
        "bullet",
        "blank_line",
        "unverified",
        "object_only",
        "future",
        "negated",
        "year",
        "facility",
        "subspan",
        "foreign_relation",
        "unknown_facility",
        "following",
        "intervening_sentence",
        "skipped_long_sentence",
        "tenant",
    ],
)
def test_only_existing_preceding_means_with_explicit_continuity_are_admitted(fault):
    means, claim_text = MEANS, CLAIM
    if fault == "foreign_actor":
        means = means.replace("가상기업", "다른기업")
    if fault == "foreign_substring_actor":
        means = means.replace("가상기업", "초가상기업")
    if fault == "object_only":
        means = "가상기업은 환경투자 검토 안건을 확인했습니다."
    if fault == "future":
        means = means.replace("운영합니다", "운영할 예정입니다")
    if fault == "negated":
        means = means.replace("운영합니다", "운영하지 않습니다")
    if fault == "year":
        means = means.replace("환경투자 검토를", "2023년 환경투자 검토를")
    if fault == "facility":
        means = means.replace("환경투자 검토를", "부산공장 환경투자 검토를")
        claim_text = claim_text.replace("환경투자 검토 체계를", "서울공장 환경투자 검토 체계를")
    separator = "\n• " if fault == "bullet" else "\n\n" if fault == "blank_line" else " "
    if fault == "intervening_sentence":
        separator = " 다른기업은 자체 승인 절차를 운영합니다. "
    if fault == "skipped_long_sentence":
        separator = " " + "다른 사업 내용 " * 300 + ". "
    texts = [means, claim_text] if fault == "different_block" else [means + separator + claim_text]
    if fault == "following":
        texts = [claim_text + " " + means]
    graph, claim = case(
        texts,
        (1 if fault == "different_block" else 0, claim_text),
        quality="unverified" if fault == "unverified" else "verified",
    )
    context = ClaimContext(
        claim,
        {
            "entity": span(claim.source_refs[0], "가상기업"),
            "metric": span(claim.source_refs[0], "환경투자 검토"),
            "reporting_period": None,
        },
    )
    if fault == "facility":
        context = replace(
            context,
            dimensions=dict(context.dimensions)
            | {"facility": span(claim.source_refs[0], "서울공장")},
        )
    if fault == "unknown_facility":
        context = replace(context, dimensions=dict(context.dimensions) | {"facility": None})
    ref = span(graph.blocks[0].source_ref(), means)
    if fault == "subspan":
        ref = span(ref, "승인 절차")
    relations = {"entity": span(ref, "승인 절차")} if fault == "foreign_relation" else None
    tenant = "00000000-0000-4000-8000-000000000001" if fault == "tenant" else graph.tenant_id
    assert accepts_context(
        context, ref, graph, tenant_id=tenant, element_id="M1", relation_tags=relations
    ) is (fault is None)
    assert not accepts_context(context, ref, graph, tenant_id=tenant, element_id="M4")


def test_future_review_stays_goal_and_does_not_receive_m1_catalog():
    quote = "가상기업은 환경투자 검토를 할 예정입니다."
    graph, claim = case([MEANS + " " + quote], (0, quote))
    data = dict(
        track="goal", allowed_elements=[f"G{i}" for i in range(1, 9)], evidence_candidates=[]
    )
    after = augment_packet(data, claim, graph, tenant_id=graph.tenant_id)
    assert after["track"] == "goal"
    assert "M1" not in after["allowed_elements"]
    assert after["evidence_candidates"] == []
    raw = LlmElement("M1", "present", claim.source_refs, None, None, None)
    assert guard(raw, claim_quote=quote).state == "unknown"


@pytest.mark.parametrize(
    "quote,element,expected",
    [
        (
            (
                "포스코인터내셔널은 E&P(자원 탐사·생산) 사업 역량을 바탕으로 2023년 2월 "
                "CCS 사업화 추진반을 구성하여 그룹 탄\n소 감축을 추진함과 동시에 "
                "사업 기회를 발굴하고 있습니다."
            ),
            "P1",
            "unknown",
        ),
        (
            (
                "포스코인터내셔널은 E&P(자원 탐사·생산) 사업 역량을 바탕으로 2023년 2월 "
                "CCS 사업화 추진반을 구성하여 그룹 탄\n소 감축을 추진함과 동시에 "
                "사업 기회를 발굴하고 있습니다."
            ),
            "M4",
            "present",
        ),
        ("향후 배출량은 100 tCO2eq로 전망됩니다.", "P1", "unknown"),
        ("당사는 별도 사업으로 2024년 배출량 100 tCO2eq를 감축했습니다.", "P1", "present"),
        (
            "현대자동차의 이사회는 탄소중립을 포함한 중장기 환경경영 전략 수립, "
            "환경 투자 등 사업전략 추진 및 경영활동에 필수적인 안건에 대해 검토·승인합니다.",
            "M1",
            "present",
        ),
    ],
)
def test_explicit_formation_and_current_review_preserved_without_inferred_results(
    quote, element, expected
):
    _, claim = case([quote], (0, quote))
    raw = LlmElement(element, "present", claim.source_refs, None, None, None)
    result = guard(raw, claim_quote=quote)
    assert result.state == expected
    assert result.evidence_refs == raw.evidence_refs
    for state in ("unknown", "conflict"):
        unchanged = replace(raw, state=state)
        assert guard(unchanged, claim_quote=quote) == unchanged


def test_pue_and_necessity_preserve_existing_v24_semantics():
    from proofops.application.analysis_profile import V3_POLICY
    from proofops.application.tagging.k1_semantics import track_requires_review
    from proofops.application.tagging.k6_citations import risk_without_commitment
    from proofops.application.tagging.semantic_admission import guard_element

    quote = "• PUE(전력사용효율지수)2) 1.1x 유지"
    _, claim = case([quote], (0, quote))
    assert not track_requires_review(quote, "performance")
    assert track_requires_review(quote, "management")
    raw = LlmElement("M1", "present", claim.source_refs, None, None, None)
    assert (
        guard_element(raw, policy=V3_POLICY["semantic_admission"], claim_quote=quote).state
        == "unknown"
    )
    assert risk_without_commitment(
        "데이터센터 에너지 사용량의 지속적인 증가가 예상됨에 따라 "
        "고효율 설비 및 에너지 절감 기술 도입 및 투자 필요성 증가"
    )
