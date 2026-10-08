"""Literal atomic candidates; no model calls or evidence approvals."""

import pytest
from proofops.application.claims import validate_extraction_response
from proofops.application.ingest.atomic_candidates import atomic_candidates


def quotes(text, **kwargs):
    return [text[c.start : c.end] for c in atomic_candidates(text, **kwargs)]


def test_soft_wrap_and_four_shared_predicate_targets():
    text = (
        "당사는 2050년까지 넷 제로 및 RE100 달성을 장기 목표로 설정하고 이\n"
        "를 이행하기 위해 2030년까지 Scope 1&2 온실가스 배출량 2020년 수준 유지 \n"
        "및 재생에너지 사용률 33% 달성을 중간 목표로 수립했습니다."
    )
    candidates = atomic_candidates(text)
    assert len(candidates) == 4
    assert any("Scope 1&2" in text[c.start : c.end] for c in candidates)
    assert all(text[c.parent_start : c.parent_end] == text for c in candidates)
    spans = [
        dict(
            char_start=c.start,
            char_end=c.end,
            quote=text[c.start : c.end],
            kind="claim",
            reason=None,
            topic_ids=["environment"],
        )
        for c in candidates
    ]
    assert len(validate_extraction_response({"spans": spans}, text)) == 4


def test_performance_management_goal_split_keeps_quantities():
    text = (
        "당사는 태양광 발전설비 2.2MW를 준공하여 연간 3,126.6MWh를 생산하였으며, "
        "현재 2.5MW 설비를 추가 건설 중으로 2026년부터 2.8GWh를 공급할 계획입니다."
    )
    selected = quotes(text)
    assert len(selected) == 3
    assert "3,126.6MWh" in selected[0]
    assert "2.5MW" in selected[1]
    assert "2026년부터 2.8GWh" in selected[2]


def test_baseline_scope_and_lists_of_means_are_not_independent_targets():
    text = "2030년까지 Scope 1 및 Scope 2 온실가스 배출량을 2018년 대비 45% 감축한다."
    assert quotes(text) == [text]
    text = "당사는 온실가스 저감을 위해 식각 및 박막 증착 공정에서 대체가스를 도입했습니다."
    assert quotes(text) == [text]


@pytest.mark.parametrize(
    "text",
    [
        "목표 및 이행 성과",
        "온실가스 배출량 (tCO2-eq)",
        "2022 2023 2024",
        "GRI 305-1 온실가스 배출량 72",
        "범례: 재생에너지, 일반에너지",
        "검증인은 온실가스 배출량 검증을 위해 표본 추출과 인터뷰를 수행했습니다.",
        "맹그로브 숲은 일반 열대림 대비 5~10배 많은 탄소를 흡수하는 것으로 알려져 있습니다.",
        "임직원 수 2024년 10,000명",
        "당사는 친환경 미래를 지향합니다.",
    ],
)
def test_non_claims_stay_out(text):
    assert quotes(text) == []


def test_table_row_and_chart_disclosure_and_assured_actual_value():
    for text in [
        "온실가스 배출량\t2024년\t1,579,162\ttCO2-eq",
        "2030년 재생에너지 사용률 33% 달성 목표",
        "검증 대상 회사의 2024년 온실가스 배출량은 100 tCO2-eq입니다.",
    ]:
        assert quotes(text) == [text]


def test_explicit_table_rows_keep_separate_values_and_do_not_extract_header():
    header = "지표\t연도\t값\t단위"
    first = "온실가스 배출량\t2024년\t1,579,162\ttCO2-eq"
    second = "재생에너지 사용률\t2024년\t33\t%"
    assert quotes("\n".join((header, first, second)), kind="table") == [first, second]


def test_cell_needs_literal_same_table_axes_and_keeps_only_its_value():
    assert quotes("1,579,162", kind="table_cell") == []
    assert quotes(
        "1,579,162", kind="table_cell", table_context=("온실가스 배출량", "2024년", "tCO2-eq")
    ) == ["1,579,162"]
    assert quotes("1,579,162", kind="table_cell", table_context=("임직원 수", "2024년", "명")) == []


def test_multiple_target_years_do_not_cut_decimal_comma_or_percent():
    text = "온실가스 배출량을 2030년까지 40%, 2050년까지 100% 감축할 계획입니다."
    assert len(quotes(text)) == 2
    text = "2024년 총 온실가스 배출량은 1,579,162 tCO2-eq로 전년 대비 3.2% 감소하였습니다."
    assert quotes(text) == [text]


def test_climate_governance_and_target_management_are_candidates_without_fragmenting_lists():
    text = "기후변화 위원회는 넷 제로 및 RE100의 연도별 목표와 이행 전략을 수립하고 있습니다."
    assert quotes(text) == [text]
    text = "당사는 기후변화 위험과 기회 요인을 식별·평가하며 관리하고 있습니다."
    assert quotes(text) == [text]
