from dataclasses import replace

import pytest
from proofops.domain.values import LlmElement

from tests.acceptance.test_binding import span
from tests.unit.test_k5_context import case


def test_qt2_vetoes_regulators_strategy_and_generic_campaigns():
    from proofops.application.tagging.qt2_context import guard

    for element, text in [
        ("M2", "EPA, ECHA"),
        ("M2", "환경부를 대상으로 규제 동향을 질의합니다."),
        ("M2", "ESG위원회는 전년도 이행실적을 점검합니다."),
        ("M2", "전담조직으로부터 환경 이슈를 보고받아 의사결정을 수행합니다."),
        ("M2", "안전한 사업장을 중장기 전략과제로 선정합니다."),
        ("M2", "친환경 사업장을 비전으로 지향합니다."),
        ("M4", "환경경영 전반에 대한 감독과 주요 의사결정을 수행합니다."),
        ("M4", "창출하고 있습니다"),
        ("M4", "캠페인을 통해 환경적 가치를 창출하고 있습니다."),
        ("M2", "전사 전략의 일환으로 추진되고 있습니다."),
        ("M2", "환경부, 지방환경관서와의 협의"),
        ("M4", "서비스와 캠페인을 통해 환경보호를 위해 노력합니다."),
    ]:
        _, claim = case([text], (0, text))
        raw = LlmElement(element, "present", claim.source_refs, None, None, None)
        assert guard(raw).state == "unknown"
        assert guard(replace(raw, state="conflict")).state == "conflict"
        assert guard(replace(raw, state="unknown")).state == "unknown"


def test_qt2_preserves_concrete_scope_and_implemented_operation():
    from proofops.application.tagging.qt2_context import guard

    for element, text in [
        ("M2", "ISO 14001 인증은 국내 전 생산 사업장에 적용됩니다."),
        ("M2", "전사 차원의 관리·운영 체계를 구축하고 있습니다."),
        ("M2", "독립이사를 대상으로 정기적인 기후변화 교육을 실시합니다."),
        ("M2", "그룹의 전담조직이 사업본부별 이행실적을 점검합니다."),
        ("M2", "각 사업부와 관리 조직은 위원회에서 확정한 정책에 따라 목표를 수립합니다."),
        ("M2", "사업 활동 전반"),
        ("M2", "임직원이 부재한 층"),
        ("M4", "주요 사업장에서 매년 내부 환경심사를 수행합니다."),
        ("M4", "매년 감사를 실시하여 감독과 의사결정 결과를 보고합니다."),
        ("M4", "2024년 그린 캠페인을 실시하여 100명이 참여했습니다."),
    ]:
        _, claim = case([text], (0, text))
        raw = LlmElement(element, "present", claim.source_refs, None, None, None)
        assert guard(raw) == raw


def test_qt2_proposes_only_verified_nearby_same_paragraph():
    from proofops.application.tagging.qt2_context import context_refs

    text = "가상기업은 ISO 14001을 운영합니다. ISO 14001은 국내 생산 사업장에 적용됩니다."
    graph, claim = case(
        [text, "다른 회사는 해외 사업장에 적용합니다."], (0, text.split(". ")[0] + ".")
    )
    refs = context_refs(claim, graph, tenant_id=graph.tenant_id)
    assert any("국내 생산 사업장" in r.quote for r in refs)
    assert all(r.source_id == claim.source_refs[0].source_id for r in refs)
    assert not context_refs(
        replace(claim, source_quality="unverified"), graph, tenant_id=graph.tenant_id
    )


def test_qt2_context_requires_matching_activity_and_preserves_period_facility():
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.tagging.qt2_context import accepts_context

    text = (
        "가상기업은 2024년 서울공장 ISO 14001을 운영합니다. "
        "서울공장 ISO 14001은 2024년 심사를 완료했습니다."
    )
    quote = text.split(". ")[0] + "."
    graph, claim = case([text], (0, quote))
    full = graph.blocks[0].source_ref()
    ref = span(full, text[len(quote) + 1 :])
    context = ClaimContext(
        claim,
        {
            "entity": span(full, "가상기업"),
            "metric": span(full, "ISO 14001"),
            "reporting_period": span(claim.source_refs[0], "2024년"),
            "facility": span(claim.source_refs[0], "서울공장"),
        },
    )
    assert accepts_context(context, ref, graph, tenant_id=graph.tenant_id, element_id="M4")
    for mismatch in ("2023년", "부산공장", "ISO 50001"):
        changed = text[len(quote) + 1 :].replace(
            "2024년" if "년" in mismatch else "서울공장" if "공장" in mismatch else "ISO 14001",
            mismatch,
        )
        other, other_claim = case([quote + " " + changed], (0, quote))
        other_context = replace(
            context,
            claim=other_claim,
            dimensions={
                k: span(other_claim.source_refs[0], v.quote) for k, v in context.dimensions.items()
            },
        )
        assert not accepts_context(
            other_context,
            span(other.blocks[0].source_ref(), changed),
            other,
            tenant_id=other.tenant_id,
            element_id="M4",
        )


def test_qt2_is_opt_in_and_historical_policies_stay_default():
    from proofops.application.analysis_profile import (
        FINALS_I23_POLICY,
        QT2_ELEMENTS_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I23_POLICY)) == FINALS_I23_POLICY
    )
    assert QT2_ELEMENTS_POLICY != FINALS_I23_POLICY
    for policy in (FINALS_I23_POLICY, QT2_ELEMENTS_POLICY):
        assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
        assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy


def test_qt2_p2_accepts_selected_comparison_year_without_fabricating_votes():
    from proofops.application.tagging.pb2_table_evidence import observation_sources
    from proofops.application.tagging.qt2_context import prepare_table

    from tests.unit.test_pb2_table_evidence import observation_case

    graph, source, claim = observation_case()
    sources = observation_sources(claim, graph, tenant_id=source.tenant_id)
    # v7 fixture does not attest prior year. Withhold until that header verifies.
    raw = LlmElement("P2", "present", claim.source_refs, "2023", None, None)
    assert not prepare_table(raw, claim, graph, tenant_id=source.tenant_id)[1]
    assert sources is not None


@pytest.mark.parametrize("mutation", ["foreign_actor", "different_block", "unverified"])
def test_qt2_does_not_credit_neighbor_by_proximity(mutation):
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.tagging.qt2_context import accepts_context

    quote = "가상기업은 ISO 14001을 운영합니다."
    other = "다른기업은 ISO 14001을 국내 사업장에 적용합니다."
    texts = [quote + " " + other] if mutation != "different_block" else [quote, other]
    graph, claim = case(
        texts, (0, quote), quality="unverified" if mutation == "unverified" else "verified"
    )
    context = ClaimContext(
        claim,
        {
            "entity": span(claim.source_refs[0], "가상기업"),
            "metric": span(claim.source_refs[0], "ISO 14001"),
        },
    )
    ref = span(graph.blocks[-1].source_ref(), other)
    assert not accepts_context(context, ref, graph, tenant_id=graph.tenant_id, element_id="M2")


def test_qt2_p2_selected_year_requires_same_row_comparison_value():
    from types import SimpleNamespace

    from proofops.adapters.local.upstage_ocr_profile_v8 import cell_proof
    from proofops.application.evidence.span_citations import span_verified_graph
    from proofops.application.tagging.qt2_context import prepare_table
    from proofops.domain.values import SourceRef

    from tests.unit.test_pb1_source import fixture

    graph, source, row = fixture()
    proof = cell_proof(graph, source.content, [row], tenant_id=source.tenant_id)[0]
    refs = [replace(row, verification_state="verified")] + [
        replace(SourceRef(**c["source_ref"]), verification_state="verified")
        for c in proof["cell_proofs"]
    ]
    graph = span_verified_graph(graph, refs, "0" * 64)
    claim = SimpleNamespace(
        tenant_id=source.tenant_id, source_refs=(refs[0],), source_quality="verified"
    )
    year = next(r for r in refs if r.quote == "2023")
    value = next(r for r in refs if r.quote == "10")
    element = LlmElement("P2", "present", (year, value), "2023", None, None)
    assert prepare_table(element, claim, graph, tenant_id=source.tenant_id)[1]
    for changed in [
        replace(element, state="unknown"),
        replace(element, evidence_refs=(year,)),
        replace(element, normalized_value="2024"),
    ]:
        assert not prepare_table(changed, claim, graph, tenant_id=source.tenant_id)[1]
