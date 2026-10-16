"""A bounded run must retain the fresh W5 ranking, not an old page list."""

from copy import deepcopy

import pytest

from evaluation.ranked_scope_selection import ranked_subset
from evaluation.report_scope import SUPPORT_VERSION, build_plan
from evaluation.report_sections import build_map


def proposal():
    texts = {p: ("환경 개선을 위해 재생에너지 사용량을 확대했습니다. " * 12) for p in range(1, 13)}
    texts[11] += "온실가스 배출량 1234 tCO2e. 제3자 검증을 받았습니다."
    study = build_map(12, [dict(page=1, title="환경", path=["환경"], method="outline")])
    study.update(
        method="outline",
        issues=[],
        page_count=12,
        source_sha256="a" * 64,
        source_path="original.pdf",
    )
    return build_plan(study, texts, max_environment_pages=10, ranking_policy=SUPPORT_VERSION)


def test_ranked_subset_keeps_source_backed_priority_and_original_proposal():
    plan = proposal()
    before = deepcopy(plan)
    selected = ranked_subset(plan, claim_limit=9)
    assert len(selected["claim_pages"]) == 9
    assert 11 in selected["claim_pages"]
    assert selected["proposal_sha256"] == plan["plan_sha256"]
    assert selected["pages"] == plan["selected_evidence_pages"]
    assert plan == before
    assert selected["selection_sha256"] != ranked_subset(plan, claim_limit=10)["selection_sha256"]


def test_subset_rejects_modified_proposal_and_invalid_caps():
    plan = proposal()
    changed = deepcopy(plan)
    changed["pages"][0]["claim_signal_score"] += 1
    with pytest.raises(ValueError, match="immutable scope"):
        ranked_subset(changed, claim_limit=9)
    for limit in (True, 0, 11):
        with pytest.raises(ValueError):
            ranked_subset(plan, claim_limit=limit)
