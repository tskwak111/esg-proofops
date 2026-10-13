from dataclasses import replace

import pytest
from proofops.domain.values import LlmElement

from tests.unit.test_k5_context import case


def tagged(eid, quote, state="present"):
    _, claim = case([quote], (0, quote))
    return LlmElement(eid, state, claim.source_refs, None, None, None)


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("G6", "관련 활동을 추진하고 있습니다."),
        ("M4", "저탄소·순환 소재 제품 포트폴리오 확대를 통해 사업 경쟁력을 강화하고 있습니다."),
        ("M4", "재생에너지 조달 확대, 고효율 설비 운영 등 다양한 감축 활동을 추진합니다."),
        ("M4", "친환경 인증 제품 확대, 포장재 도입 등 환경 가치를 반영한 활동을 추진합니다."),
        ("M4", "시공 계획 단계부터 운영까지 에너지 절감 기술과 친환경 설계를 적용했습니다."),
        ("M4", "환경경영테이블을 통해 개선과제의 실행을 촉진하고 있습니다."),
        ("M2", "유관부서의 환경경영 이행과 개선과제의 실행"),
    ],
)
def test_generic_citations_do_not_establish_plan_results_or_boundary(eid, quote):
    from proofops.application.tagging.q1_contract import SEMANTIC_POLICY
    from proofops.application.tagging.semantic_admission import guard_element

    raw = tagged(eid, quote)
    assert guard_element(raw, policy=SEMANTIC_POLICY).state == "unknown"
    assert raw.state == "present"
    assert guard_element(raw).state == "present"  # historical policy unchanged


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("G6", "수소 혼·전소로 순차 전환하고 잔여 배출량에는 CCS를 도입할 계획입니다."),
        ("M4", "2023년 2월 CCS 사업화 추진반을 구성했습니다."),
        ("M4", "문헌조사 및 현장실사를 실시하여 조류의 실제 서식 현황을 파악했습니다."),
        ("M2", "국내 전 생산 사업장"),
    ],
)
def test_concrete_citations_and_unresolved_states_are_preserved(eid, quote):
    from proofops.application.tagging.q1_contract import SEMANTIC_POLICY
    from proofops.application.tagging.semantic_admission import guard_element

    raw = tagged(eid, quote)
    assert guard_element(raw, policy=SEMANTIC_POLICY).state == "present"
    for state in ("unknown", "conflict"):
        assert guard_element(replace(raw, state=state), policy=SEMANTIC_POLICY).state == state


def test_forecast_is_held_but_target_and_existing_cost_procedure_are_not():
    from proofops.application.tagging.q1_contract import forecast_quote

    assert forecast_quote("2030년까지의 연도별 재무영향은 예상 매출액 대비 0.4% 미만입니다.")
    assert not forecast_quote("2030년까지 재생에너지 전환율 100% 달성을 목표로 설정했습니다.")
    assert not forecast_quote("2024년부터 예상 전력 사용량과 탄소비용을 사전에 반영합니다.")


def test_targeted_guidance_keeps_unaffected_historical_wire():
    from proofops.application.tagging.k9_contract import preliminary as old
    from proofops.application.tagging.q1_contract import CLASSIFICATION_GUIDANCE, preliminary

    schema = dict(type="object", properties={}, additionalProperties=False)
    board = "이사회는 환경 투자 안건을 검토·승인합니다."
    assert preliminary(schema, quote=board) == old(schema, quote=board)
    assert CLASSIFICATION_GUIDANCE in preliminary(
        schema, quote="문헌조사 및 현장실사를 실시했습니다."
    )


def test_inflected_local_observed_year_keeps_literal_role_and_old_guard():
    from proofops.application.evidence.binding import (
        ClaimContext,
        accept_binding,
        local_relation_tags,
    )
    from proofops.application.tagging.q1_contract import SEMANTIC_POLICY

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_rules import pack

    quote = "2025년에는 총 8건의 에너지 효율화 과제로 약 3만 톤을 저감했습니다."
    graph, claim = case([quote], (0, quote))
    context = ClaimContext(claim, {"reporting_period": span(claim.source_refs[0], "2025년에는")})
    args = dict(
        original=graph,
        tenant_id=graph.tenant_id,
        rulepack=pack(),
        element_id="P1",
        local_value_identity=True,
    )
    ref = span(claim.source_refs[0], "약 3만 톤")
    relations = next(iter(local_relation_tags(context).values()))
    assert accept_binding(context, ref, relations, **args) == "undetermined"
    assert (
        accept_binding(context, ref, relations, structural_policy=SEMANTIC_POLICY, **args)
        == "accepted"
    )
    wrong = ClaimContext(
        claim,
        {"reporting_period": replace(context.dimensions["reporting_period"], quote="2024년에는")},
    )
    assert (
        accept_binding(wrong, ref, relations, structural_policy=SEMANTIC_POLICY, **args)
        != "accepted"
    )


def test_activity_effect_matrix_retains_literal_means_and_fwu_cell():
    from proofops.application.ingest.q1_tables import activity_spans, cell_entries

    rows = [
        ["환경영향 완화 요소", "", "환경영향 완화 효과"],
        [
            "에너지 효율화",
            "② 냉수펌프 운영 최적화",
            "냉수펌프 효율 운영 감축 효과 (연간 253 tCO₂eq)",
        ],
        [
            "에너지 효율화",
            "③ 공조설비 운영 최적화",
            "FWU 온도 상향 및 팬 풍량 최적화 통한 감축 효과 (연간 994 tCO₂eq)",
        ],
    ]
    text = "\n".join("\t".join(row) for row in rows)
    cells = [
        dict(text=t, row=r, column=c, row_span=1, column_span=1)
        for r, row in enumerate(rows)
        for c, t in enumerate(row)
    ]
    entries = cell_entries(text, cells, source_id="original-table")
    assert any("FWU" in e["text"] for e in entries)
    spans = activity_spans(text, cells)
    assert [s["quote"] for s in spans] == ["② 냉수펌프 운영 최적화", "③ 공조설비 운영 최적화"]
    assert all(text[s["char_start"] : s["char_end"]] == s["quote"] for s in spans)
    other_text = text.replace("환경영향 완화 요소", "기타 항목")
    other_cells = [
        c | dict(text=c["text"].replace("환경영향 완화 요소", "기타 항목")) for c in cells
    ]
    assert activity_spans(other_text, other_cells) == []


@pytest.mark.parametrize(
    "value,accepted",
    [
        ("2024년도", True),
        ("2023년 10월", True),
        ("2024년12월31일 기준", True),
        ("2024년 2월 29일 기준", True),
        ("2024년 2월 30일 기준", False),
        ("2023년 2월 29일 기준", False),
        ("2024년 13월", False),
        ("2024년 0월 1일 기준", False),
        ("2030년까지", False),
        ("2025년 이후", False),
        ("최근4개년", False),
        ("2023년 및 2025년", False),
        ("2025년 배출량 기준", False),
        ("2025년 12월 말 기준", False),
        ("FY2024", False),
    ],
)
def test_r12_local_calendar_syntax_is_opt_in(value, accepted):
    from proofops.application.tagging.q1_contract import R12_POLICY, observed_period

    assert observed_period(value, policy=R12_POLICY) is accepted
    assert not observed_period(value)


def test_r12_date_remains_local_intrinsic_and_preserves_literal_roles():
    from proofops.application.evidence.binding import (
        ClaimContext,
        accept_binding,
        local_relation_tags,
    )
    from proofops.application.tagging.q1_contract import R12_POLICY, SEMANTIC_POLICY

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_rules import pack

    quote = "2024년 12월 31일 기준 내부심사원 교육을 정기적으로 운영한 결과 10명이 수료했습니다."
    graph, claim = case([quote], (0, quote))
    period = span(claim.source_refs[0], "2024년 12월 31일 기준")
    context = ClaimContext(claim, {"reporting_period": period})
    relations = next(iter(local_relation_tags(context).values()))
    ref = span(claim.source_refs[0], "내부심사원 교육을 정기적으로 운영")
    args = dict(original=graph, tenant_id=graph.tenant_id, rulepack=pack(), element_id="M1")
    reasons = []
    assert (
        accept_binding(
            context,
            ref,
            relations,
            structural_policy=SEMANTIC_POLICY,
            local_value_identity=True,
            **args,
        )
        == "undetermined"
    )
    assert (
        accept_binding(
            context,
            ref,
            relations,
            structural_policy=R12_POLICY,
            local_value_identity=True,
            diagnostics=reasons,
            **args,
        )
        == "accepted"
    )
    assert reasons == []
    assert context.dimensions["reporting_period"] == period
    reasons = []
    assert (
        accept_binding(
            context,
            ref,
            relations,
            structural_policy=R12_POLICY,
            diagnostics=reasons,
            **args,
        )
        == "undetermined"
    )
    assert "period_syntax_unsupported" in reasons
    assert (
        accept_binding(
            context,
            ref,
            relations,
            structural_policy=R12_POLICY,
            local_value_identity=True,
            **(args | dict(element_id="M4")),
        )
        == "undetermined"
    )
    invalid = replace(period, quote="2024년 2월 30일 기준")
    assert (
        accept_binding(
            ClaimContext(claim, {"reporting_period": invalid}),
            ref,
            relations,
            structural_policy=R12_POLICY,
            local_value_identity=True,
            **args,
        )
        != "accepted"
    )


def test_r12_policy_is_pinned_and_old_prompt_bytes_are_unchanged():
    from proofops.application.tagging.q1_contract import (
        R12_CLASSIFICATION_GUIDANCE,
        R12_POLICY,
        preliminary,
        validate_policy,
    )
    from proofops.domain.provenance import canonical_hash

    schema = dict(type="object", properties={}, additionalProperties=False)
    quote = "환경 교육을 실시했습니다."
    before = preliminary(schema, quote=quote)
    after = preliminary(schema, quote=quote, policy=R12_POLICY)
    assert after == before + R12_CLASSIFICATION_GUIDANCE
    assert canonical_hash(after) != canonical_hash(before)
    assert len(after.encode()) < 16384
    with pytest.raises(ValueError):
        validate_policy(R12_POLICY | dict(max_request_bytes=32768))


@pytest.mark.parametrize(
    "period",
    ["2024년 2월 30일 기준", "2030년까지", "최근4개년", "2023년 및 2025년", "2025년 이후"],
)
def test_r12_invalid_period_does_not_bypass_binding(period):
    from proofops.application.evidence.binding import (
        ClaimContext,
        accept_binding,
        local_relation_tags,
    )
    from proofops.application.tagging.q1_contract import R12_POLICY

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_rules import pack

    quote = f"{period} 내부심사원 교육을 실시했습니다."
    graph, claim = case([quote], (0, quote))
    context = ClaimContext(claim, {"reporting_period": span(claim.source_refs[0], period)})
    diagnostics = []
    assert (
        accept_binding(
            context,
            span(claim.source_refs[0], "내부심사원 교육"),
            next(iter(local_relation_tags(context).values())),
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="M1",
            local_value_identity=True,
            structural_policy=R12_POLICY,
            diagnostics=diagnostics,
        )
        == "undetermined"
    )
    assert diagnostics == ["period_syntax_unsupported"]


def test_r12_date_cannot_expand_cross_source_company_or_calendar_fiscal_binding():
    from proofops.application.evidence.binding import (
        ClaimContext,
        accept_binding,
        local_relation_tags,
    )
    from proofops.application.tagging.q1_contract import R12_POLICY, SEMANTIC_POLICY

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_rules import pack

    text = "기업A 2024년 12월 31일 기준 내부심사원 교육을 실시했습니다."
    other = "기업B FY2024 내부심사원 교육을 실시했습니다."
    graph, claim = case([text, other], (0, text))
    ref = claim.source_refs[0]
    context = ClaimContext(
        claim,
        {"entity": span(ref, "기업A"), "reporting_period": span(ref, "2024년 12월 31일 기준")},
    )
    foreign = graph.blocks[1].source_ref()
    foreign_roles = {"entity": span(foreign, "기업B"), "reporting_period": span(foreign, "FY2024")}
    for policy in (SEMANTIC_POLICY, R12_POLICY):
        assert (
            accept_binding(
                context,
                foreign,
                foreign_roles,
                original=graph,
                tenant_id=graph.tenant_id,
                rulepack=pack(),
                element_id="M1",
                local_value_identity=True,
                structural_policy=policy,
            )
            != "accepted"
        )
    relations = next(iter(local_relation_tags(context).values()))
    wrong = relations | {"entity": span(foreign, "기업B")}
    assert (
        accept_binding(
            context,
            span(ref, "내부심사원 교육"),
            wrong,
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="M1",
            local_value_identity=True,
            structural_policy=R12_POLICY,
        )
        == "rejected"
    )
