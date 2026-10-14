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


def test_v3_splits_kakao_award_recognition_from_iso_assertion_and_v2_is_frozen():
    text = (
        "카카오 데이터센터 안산은 시공 계획 단계부터 운영까지 에너지 절감 기술과 "
        "친환경 설계를 적용했습니다. "
        "그 결과 친환경 건축인증인 LEED Certified 등급을 획득하여 부지 선정, 대지 환경, "
        "수자원 효율성, 에너지 및 대기환경 등 항목에서 친환경 성과 효율성을 입증했습니다. "
        "또한 소비자시민모임에서 주최하는 에너지위너상을 수상하여 친환경 및 에너지 절감 운영을 "
        "인정받았으며, ISO 14001 인증을 통해 체계적인 환경 관리 역량을 유지하고 있습니다."
    )
    v2 = quotes(text, policy_version=2)
    v3 = quotes(text, policy_version=3)
    iso = "ISO 14001 인증을 통해 체계적인 환경 관리 역량을 유지하고 있습니다."
    assert len(v2) == 3 and "ISO 14001" in v2[-1] and "에너지위너상" in v2[-1]
    assert len(v3) == 4 and v3[-1] == iso
    assert v3[:2] == v2[:2]


def test_climate_governance_and_target_management_are_candidates_without_fragmenting_lists():
    text = "기후변화 위원회는 넷 제로 및 RE100의 연도별 목표와 이행 전략을 수립하고 있습니다."
    assert quotes(text) == [text]
    text = "당사는 기후변화 위험과 기회 요인을 식별·평가하며 관리하고 있습니다."
    assert quotes(text) == [text]


# A-01 literal regression inputs; provisional AI gold is not evidence approval.
# fmt: off
@pytest.mark.parametrize(
    "claim_id,text",
    [
        (
            'R108-SK-C030',
            (
                'Scope 3 배출량 산정 범위를 확대할 수 있도록 지속 '
                '검토 중입니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C005',
            (
                '지속가능경영위원회     현대자동차의 기후 관련 위험 및 '
                '기회를 감독하는 최상위 의사결정기구는 이사회 \n산하 '
                '지속가능경영위원회입니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C007',
            (
                '기후변화를 포함한 ESG 주요 현안에 대해 반기마다 '
                '논의하며, 탄소감축, 기후변화 대응, \n제품 전과정에서의 '
                '친환경성, 공급망 ESG 관리 등 중점 추진 과제를 '
                '중심으로 핵심이슈에 대한 전략적 \n접근과 중장기적 계획, '
                '개선 추진활동에 대한 사항을 결의하고 감독합니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C009',
            (
                'MCM에서 검토된 결과에 따라, 주요 \n리스크 요인, '
                '중장기 사업 전략과 연계된 성과 개선 필요사항, 그리고 '
                '최고 의사결정기구의 심의·승인이 \n필요한 사안 등은 '
                '지속가능경영위원회에 상정됩니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C011',
            (
                '그룹 탄소중립 위원회는 연 1회 개최되며, \n현대자동차그룹'
                ' 회장이 주재하고 주요 계열사 CEO가 참여하여 각 '
                '계열사의 탄소중립 전략, 실행 계획 및 \n과정을 종합적으로'
                ' 점검하는 역할을 수행합니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C021',
            (
                '• 목표 검토 프로세스     현대자동차의 이사회는 '
                '탄소중립을 포함한 중장기 환경경영 전략 수립, 환경 \n투자'
                ' 등 사업전략 추진 및 경영활동에 필수적인 안건에 대해 '
                '검토·승인합니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C026',
            (
                '• 목표에 포함된 온실가스 배출량 범위     현대자동차의'
                ' 기후 관련 목표에 대한 온실가스 배출량 범위는 \n'
                'Scope 1, 2, 3(일부)입니다.'
            ),
        ),
        (
            'R108-HYUNDAI-C027',
            (
                '• 목표에 대한 설명     현대자동차의 기후 관련 목표는'
                ' 총 배출량 목표입니다.'
            ),
        ),
        (
            'R108-POSCO-C028',
            (
                '직접 감축은 화력발전의 경우 \n설비 효율 개선, 연료 '
                '전환과 CCS를 통해 가능하며 포스코인터내셔널은 정부 정책'
                ' 및 기술 상용화 시점을 고려하여 국내 주요 \n사업장인 '
                '인천LNG복합발전소를 수소 혼·전소로의 순차적 전환과 '
                '동시에 잔여 배출량 포집을 위한 CCS 기술을 단계적으로 '
                '도\n입할 계획입니다.'
            ),
        ),
        (
            'R108-SAMSUNG-C005',
            (
                '2024년에는 인도, 이집트, \n마다가스카르에서 '
                '산림농업(Agroforestry) 사업과 맹그로브 조성 \n'
                '사업을 발굴하여 총 46만 톤의 외부감축 배출권을 '
                '확보했습니다.'
            ),
        ),
        (
            'R108-SAMSUNG-C006',
            (
                'DX부문은 자연기반 온실가스 외부감축사업을 지속해서 발굴해'
                ' 나갈 \n예정입니다.'
            ),
        ),
        (
            'R108-SAMSUNG-C007',
            (
                '온실가스를 영구적으로 제거할 수 있는 CDR(Carbon'
                ' \nDioxide Removal) 사업을 우선으로 '
                '선별하되, 지역주민들의 삶의 \n질 향상과 소득 증대, '
                '육상·해상 생태계 보호, 생물다양성 보전 등 UN\n'
                '지속가능발전목표(SDGs, Sustainable '
                'Development Goals)에 대한 \n효과도 함께 '
                '고려하여 전 지구적 기후변화 대응과 지속가능한'
            ),
        ),
        (
            'R108-SAMSUNG-C008',
            (
                '1) 2024년까지 누적 64대 전환'
            ),
        ),
        (
            'R108-SAMSUNG-C012',
            (
                'DX부문은 앞으로도 재생에너지 확대에 \n기여하는 PPA를 '
                '지속적으로 발굴할 계획입니다.'
            ),
        ),
        (
            'R108-SAMSUNG-C020',
            (
                '또한, PPA 제도 시행에 \n따라 PPA를 확대, 추진할 '
                '계획입니다.'
            ),
        ),
    ],
)
# fmt: on
def test_advisor_dropped_disclosures_remain_selectable(claim_id, text):
    candidates = atomic_candidates(text)
    assert candidates, claim_id
    assert all(text[c.start : c.end] for c in candidates)


@pytest.mark.parametrize("purpose", ["달성을 위해", "달성을 위한", "달성을 목적으로"])
def test_purpose_conjunction_is_one_establishment_claim(purpose):
    text = f"탄소중립 실현 및 감축 목표 {purpose} 협의체가 2024년 신설되었습니다."
    assert quotes(text) == [text]


@pytest.mark.parametrize("quantity", ["46만 톤", "1천 톤", "0.2억 톤"])
def test_scaled_emissions_credit_quantity_is_literal_even_without_action(quantity):
    text = f"2024년 외부감축 배출권 {quantity}"
    assert quotes(text) == [text]


def test_context_dependent_candidate_keeps_own_quote_and_literal_parent_only():
    first = "당사는 재생에너지 전환을 추진합니다."
    second = "1) 2024년까지 누적 64대 전환"
    text = first + " " + second
    candidates = atomic_candidates(text)
    footnote = candidates[-1]
    assert text[footnote.start : footnote.end] == second
    assert footnote.context_dependent is True
    assert text[footnote.parent_start : footnote.parent_end] == text
    assert quotes("1) 2024년까지 임직원 수 64명") == []


def test_gate_diagnostics_count_sentences_before_splitting():
    diagnostics = {}
    text = "범례: 재생에너지. " + (
        "당사는 2024년 온실가스 배출량을 8% 감축했으며, "
        "2030년까지 40% 감축할 계획입니다."
    )
    candidates = atomic_candidates(text, diagnostics=diagnostics)
    assert len(candidates) == 2
    assert diagnostics == {
        "parent_count": 2,
        "gate_rejected_count": 1,
        "eligible_parent_count": 1,
        "candidate_count": 2,
        "context_dependent_count": 0,
    }
