"""QA2 negative admission; historical Q1/R12 replay stays unchanged."""

from dataclasses import replace

import pytest
from proofops.application.tagging.q1_contract import (
    QA2_POLICY,
    R12_POLICY,
    guard,
    observed_period,
)
from proofops.domain.provenance import canonical_hash

from tests.unit.test_q1_structural import tagged


@pytest.mark.parametrize("eid", ["M3", "M4"])
@pytest.mark.parametrize(
    "quote",
    [
        "환경 실무자 교육을 다음 분기에 실시할 방침입니다.",
        "환경 교육을 실시할 예정입니다.",
        "ISO 14001 내부심사원 교육을 17명에게 실시할 예정입니다.",
        "2027년 외부기관의 ISCC 인증을 취득할 방침입니다.",
        "협력사 환경 교육 시행 예정입니다.",
        "환경 교육을 실시할 계획입니다.",
    ],
)
def test_qa2_blocks_future_votes_without_rewriting_raw(eid, quote):
    element = tagged(eid, quote)
    assert guard(element) == element
    assert guard(element, policy=R12_POLICY) == element
    admitted = guard(element, policy=QA2_POLICY, claim_quote=quote)
    assert admitted.state == "unknown"
    assert admitted.reason_code == "QA2_FUTURE_IMPLEMENTATION_REQUIRES_REVIEW"
    assert admitted.evidence_refs == element.evidence_refs
    assert element.state == "present"
    assert admitted.normalized_value is None and admitted.credited_from is None


@pytest.mark.parametrize("state", ["unknown", "conflict"])
def test_qa2_preserves_unresolved_states(state):
    element = tagged("M4", "환경 교육을 실시할 예정입니다.", state)
    assert guard(element, policy=QA2_POLICY) == element


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("M4", "환경 실무자 교육을 실시했습니다."),
        ("M4", "2025년 환경 교육에 17명이 참여했습니다."),
        ("M4", "환경 교육 방침을 개정했습니다."),
        ("M3", "외부 인증기관의 ISCC 인증을 취득했습니다."),
        ("M1", "환경 교육을 실시할 방침입니다."),
    ],
)
def test_qa2_never_mints_votes_or_vetoes_completed_support(eid, quote):
    element = tagged(eid, quote)
    assert guard(element, policy=QA2_POLICY, claim_quote=quote) == element


def test_qa2_cannot_hide_future_suffix_in_a_short_citation():
    element = tagged("M4", "환경 교육")
    assert (
        guard(element, policy=QA2_POLICY, claim_quote="환경 교육을 실시할 예정입니다.").state
        == "unknown"
    )


def test_qa2_completed_sentence_survives_separate_future_sentence():
    quote = "환경 교육을 실시했습니다. 다음 분기 교육은 실시할 예정입니다."
    element = tagged("M4", "환경 교육을 실시했습니다.")
    assert guard(element, policy=QA2_POLICY, claim_quote=quote) == element
    planned = replace(element, evidence_refs=tagged("M4", "실시할 예정입니다.").evidence_refs)
    assert guard(planned, policy=QA2_POLICY, claim_quote=quote).state == "unknown"


@pytest.mark.parametrize(
    "period,expected",
    [
        ("2024년 12월 31일 기준", True),
        ("2024년도", True),
        ("2024년 2월 30일 기준", False),
        ("2030년까지", False),
        ("최근 4개년", False),
        ("2023년 및 2025년", False),
    ],
)
def test_qa2_preserves_f2_calendar_contract(period, expected):
    assert observed_period(period, policy=QA2_POLICY) is expected
    assert observed_period(period, policy=R12_POLICY) is expected


def test_qa2_keeps_archived_r12_hash():
    assert canonical_hash(R12_POLICY) == (
        "fb3f3f717bbe69163d35949ff09347f5db23fdce6c85d7b0ab9aa6c6eb89a57c"
    )
    assert canonical_hash(QA2_POLICY) != canonical_hash(R12_POLICY)


@pytest.mark.parametrize(
    "period,expected",
    [
        ("2024년 12월 31일 기준", "accepted"),
        ("2025년 4월 31일 기준", "undetermined"),
        ("2024년 00월 기준", "undetermined"),
        ("2025년 3월부터", "undetermined"),
        ("2025년도 및 2026년도", "undetermined"),
    ],
)
def test_qa2_f2_binding_stays_local_and_intrinsic(period, expected):
    from proofops.application.evidence.binding import (
        ClaimContext,
        accept_binding,
        local_relation_tags,
    )

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_rules import pack
    from tests.unit.test_k5_context import case

    text = f"기업A {period} 협력사 환경 교육을 정기적으로 운영했습니다."
    foreign = "기업B FY2024 다른 사업장에서 환경 교육을 운영했습니다."
    graph, claim = case([text, foreign], (0, text))
    ref = claim.source_refs[0]
    context = ClaimContext(
        claim, dict(entity=span(ref, "기업A"), reporting_period=span(ref, period))
    )
    roles = next(iter(local_relation_tags(context).values()))
    for policy in (R12_POLICY, QA2_POLICY):
        diagnostics = []
        options = dict(
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            local_value_identity=True,
            structural_policy=policy,
            diagnostics=diagnostics,
        )
        assert (
            accept_binding(context, span(ref, "환경 교육"), roles, element_id="M1", **options)
            == expected
        )
        assert diagnostics == ([] if expected == "accepted" else ["period_syntax_unsupported"])
        assert (
            accept_binding(context, span(ref, "환경 교육"), roles, element_id="M4", **options)
            == "undetermined"
        )
        other = graph.blocks[1].source_ref()
        assert (
            accept_binding(
                context,
                other,
                dict(entity=span(other, "기업B"), reporting_period=span(other, "FY2024")),
                element_id="M1",
                **options,
            )
            != "accepted"
        )
