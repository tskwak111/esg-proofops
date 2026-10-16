"""DEC-92/93 candidates are neither new facts nor approved grade mappings."""

from copy import deepcopy
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("category", [None, "emissions_estimate", "forward_looking"])
def test_calculation_marker_does_not_relabel_a_forecast(category):
    from proofops.application.tagging.v3_dec92 import validate_classification

    from tests.unit.test_k5_context import case

    quote = "가상기업은 산정 방법에 따라 향후 배출량을 100톤으로 전망합니다."
    graph, claim = case([quote], (0, quote))
    result = SimpleNamespace(
        track=SimpleNamespace(track="performance"), safe_harbor_category=category
    )
    if category == "forward_looking":
        assert validate_classification(result, claim, graph) is result
    else:
        with pytest.raises(ValueError, match="V3_DEC92_FORECAST_RETAG_REQUIRED"):
            validate_classification(result, claim, graph)


@pytest.mark.parametrize(
    "text,track,category",
    [
        ("2030년까지 배출량을 20% 감축하겠습니다.", "goal", "forward_looking"),
        ("2050년 넷제로와 RE100을 선언합니다.", "goal", "forward_looking"),
        ("‘2040 Carbon Negative’ 달성", "goal", "forward_looking"),
        ("데이터센터 각 춘천 RE70 수준의 재생에너지 확보", "goal", "forward_looking"),
        (
            "2040년까지 사업장 전력의 100% 재생에너지 전환을 선언했습니다.",
            "goal",
            "forward_looking",
        ),
        (
            "단계적으로 2030년까지 해외 사업장의 재생에너지 전환을 우선적으로 완료하고,",
            "goal",
            "forward_looking",
        ),
        ("향후 배출량은 100 tCO2eq로 전망됩니다.", "performance", "forward_looking"),
        ("가정 및 시나리오에 따라 100 tCO2eq로 전망됩니다.", "performance", "forward_looking"),
        ("당사는 RE100에 가입했습니다.", "management", None),
        ("당사는 RE100 이행을 위해 위원회를 운영합니다.", "management", None),
        ("2024년부터 예상 전력 사용량과 탄소비용을 사전에 반영합니다.", "management", None),
        (
            "2030년까지의 연도별 재무영향은 예상 매출액 대비 0.4% 미만입니다.",
            "management",
            "forward_looking",
        ),
        ("국가 NDC 목표를 설명합니다.", None, None),
        ("PUE 1.1x 유지", "performance", None),
    ],
)
def test_category_candidate_is_independent_of_basis_and_track(text, track, category):
    from proofops.application.tagging.v3_dec92 import forward_candidate

    assert forward_candidate(text, track=track)[0] == category


def test_historical_policy_prompt_and_target_replay():
    from proofops.application.analysis_profile import (
        FINALS_I24_POLICY,
        V2_PROFILE,
        V3_POLICY,
        policy_for,
        publication_policy_for,
    )
    from proofops.application.tagging.pb1_classification import COMPACT_PROMPT, forward_candidate
    from proofops.application.tagging.q1_contract import PRELIMINARY
    from proofops.application.tagging.v3_dec92 import PRELIMINARY as NEW_PROMPT
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(FINALS_I24_POLICY) == (
        "775e8d04aaed82bd86c002402f3b80fdabd7206e69a1e768403cbc0644638501"
    )
    assert canonical_hash(COMPACT_PROMPT) == (
        "2ef2d0019824be86a31b067b3666b857c443c54d52af5548872b8856fe3d6097"
    )
    assert canonical_hash(PRELIMINARY) == (
        "6f8cf2e4d892b0904fbf61ab2a8ec215ac1cc0b963916119d21492135ec9bf31"
    )
    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I24_POLICY)) == FINALS_I24_POLICY
    )
    assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(V3_POLICY)) == V3_POLICY
    assert "goal with category null" not in NEW_PROMPT
    for text in ("2030년까지 배출량을 20% 감축하겠습니다.", "2050년 넷제로와 RE100을 선언합니다."):
        assert forward_candidate(text) == (None, "ordinary_target")


@pytest.mark.parametrize(
    "category,label,items",
    [
        ("forward_looking", "전망", ["assumptions", "scenario_or_premises"]),
        (
            "emissions_estimate",
            "추정",
            ["identified_as_estimate", "estimation_method", "uncertainty"],
        ),
    ],
)
def test_display_preserves_null_mapping_and_unknown_checklist(category, label, items):
    from proofops.application.tagging.quality import hold_projection

    item = dict(
        provisional_grade=dict(
            evidence_grade=None,
            label=None,
            gap_ids=["GAP-001"],
            grade_range=dict(floor="E0", ceiling="E3"),
            elements=[],
        ),
        frozen_packet=dict(track="performance", safe_harbor_category=category),
    )
    before = deepcopy(item)
    result = hold_projection(item, profile="v3-dec92-v1")
    assert label in result["display"]
    assert result["evidence_grade"] is result["label"] is None
    assert result["v3_safe_harbor"]["reasonable_basis_documented"] is None
    assert result["v3_safe_harbor"]["legal_effect"] == "not_determined"
    assert result["v3_safe_harbor"]["checklist"] == {name: "unknown" for name in items}
    assert item == before


@pytest.mark.parametrize(
    "track,category", [("goal", "forward_looking"), ("performance", "emissions_estimate")]
)
def test_complete_general_ladder_cannot_override_safe_harbor_mapping(track, category):
    from dataclasses import replace

    from proofops.domain.rules.engine import evaluate
    from proofops.domain.rules.safe_harbor import record_safe_harbor

    from tests.acceptance.test_rules import inputs, pack

    tags, context = inputs(track)
    assert evaluate(tags, context, pack()).evidence_grade == "E3"
    candidate = replace(tags, safe_harbor_category=category)
    result = evaluate(candidate, context, pack())
    record = record_safe_harbor(candidate, context, pack())
    assert result.evidence_grade is result.label is None
    assert "GAP-001" in result.gap_ids
    assert record.reasonable_basis_documented is None
    assert record.legal_effect == "not_determined"


def test_foreign_company_basis_and_missing_estimate_facts_never_become_boolean_true():
    from proofops.application.tagging.quality import hold_projection

    item = dict(
        frozen_packet=dict(
            track="performance",
            safe_harbor_category="forward_looking",
            atomic_quote="가상기업의 배출량은 100톤으로 전망됩니다.",
            evidence_candidates=[dict(quote="다른기업은 가정과 시나리오를 공개했습니다.")],
        ),
        provisional_grade=dict(evidence_grade=None, label=None, gap_ids=["GAP-001"], elements=[]),
    )
    record = hold_projection(item, profile="v3-dec92-v1")["v3_safe_harbor"]
    assert record["reasonable_basis_documented"] is None
    assert set(record["checklist"].values()) == {"unknown"}
    assert record["checklist_status"] == "retag_required"
