from copy import deepcopy

import pytest


def test_observed_headers_and_hyphenated_co2_units_keep_original_offsets():
    from proofops.application.ingest.k6_coverage import observations

    text = (
        "지표\t단위\t2023년 실적\t2024년 실적\n"
        "온실가스 Scope 1 배출량\ttCO2-eq\t696,590\t679,822\n"
        "재생에너지 전환비율\t%\t12.8\t16.7"
    )
    rows = observations(text)
    assert [r["value"] for r in rows] == ["679,822", "16.7"]
    assert all(text[r["start"] : r["end"]] == r["quote"] for r in rows)
    assert all(r["year"] == "2024" for r in rows)
    assert rows[0]["unit"] == "tCO2-eq"


@pytest.mark.parametrize(
    "header", ["2024년 목표", "2024년 계획", "2024년 예상", "2024년 실적 2030"]
)
def test_forecasts_and_ambiguous_headers_never_become_observed_performance(header):
    from proofops.application.ingest.k6_coverage import observations

    assert observations(f"지표\t단위\t{header}\n온실가스\ttCO2-eq\t123") == []


def test_target_rescue_is_literal_and_rejects_general_forecasts_and_notes():
    from proofops.application.ingest.k6_coverage import target_spans

    quote = (
        "가나다는 2050년까지 넷 제로 달성을 장기 목표로 설정하고 2030년까지 온실가스 배출량 유지"
    )
    assert target_spans(quote, kind="paragraph")[0]["quote"] == quote
    continuation = "및 재생에너지 사용률 33% 달성을 중간 목표로 수립했습니다."
    assert target_spans(continuation, kind="paragraph")[0]["quote"] == continuation
    for text in (
        "업계는 2050년 온실가스 증가를 예상합니다.",
        "*2030년 목표에는 사업장 배출량 포함",
        "2030년 재생에너지 목표",
        "기관은 2030년 목표 수립을 권고했습니다.",
    ):
        assert target_spans(text, kind="paragraph") == []


def test_repeated_unit_can_only_be_restored_with_selected_adjacent_numbers():
    from proofops.application.tagging.k6_citations import anchor_units

    refs = {"e0": {"quote": "약 2,944 tCO₂를 저장, 연간 약 156 tCO₂ 흡수"}}
    selected = [{"id": "e0", "quote": q} for q in ("2,944", "tCO₂", "156", "tCO₂")]
    before = deepcopy(selected)
    fixed = anchor_units(selected, refs)
    assert [s["quote"] for s in fixed] == ["2,944", "2,944 tCO₂", "156", "156 tCO₂"]
    assert selected == before
    assert anchor_units([{"id": "e0", "quote": "tCO₂"}], refs)[0]["quote"] == "tCO₂"
    for raw in ("2,944 tCO₂ / 2,944 tCO₂", "2,944 MWh, 156 tCO₂", "12,944 tCO₂, 156 tCO₂"):
        assert anchor_units(selected[:2], {"e0": {"quote": raw}}) == selected[:2]


def test_risk_need_is_never_promoted_to_company_goal():
    from proofops.application.tagging.k6_citations import risk_without_commitment

    assert risk_without_commitment(
        "에너지 사용량 증가가 예상됨에 따라 고효율 설비 투자 필요성 증가"
    )
    assert not risk_without_commitment(
        "고효율 설비 투자 필요성 증가에 대응해 2030년까지 설비를 도입할 계획입니다."
    )
    assert not risk_without_commitment(
        "2030년까지 재생에너지 사용률 33% 달성을 목표로 수립했습니다."
    )
    assert not risk_without_commitment("투자 필요성 증가에 대응해 2030년 탄소중립이 목표입니다.")
