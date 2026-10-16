"""Literal J7 clause boundaries, including condition and historical-policy guards."""

import pytest
from proofops.application.claims import validate_extraction_response
from proofops.application.ingest.j7_split import refine_selected


def selected(text, **options):
    return dict(
        char_start=0,
        char_end=len(text),
        quote=text,
        kind="claim",
        reason=None,
        topic_ids=["environment"],
        **options,
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "• 기후 목표를 경영진 ESG KPI로 승인하며, 성과 및 목표 달성현황을 모니터링",
            ["• 기후 목표를 경영진 ESG KPI로 승인하며,", "성과 및 목표 달성현황을 모니터링"],
        ),
        (
            "• 연 1회 이상 기후변화 교육을 실시하며, 필요 시 워킹그룹을 통해 환경 사안을 논의 진행",
            [
                "• 연 1회 이상 기후변화 교육을 실시하며,",
                "필요 시 워킹그룹을 통해 환경 사안을 논의 진행",
            ],
        ),
        (
            "환경 정책을 수립·운영하고 있으며, 전담 부서에서 위험 식별 및 대응 과제 관리를 수행",
            [
                "환경 정책을 수립·운영하고 있으며,",
                "전담 부서에서 위험 식별 및 대응 과제 관리를 수행",
            ],
        ),
        (
            "기후 대응 전략을 총괄하고, 과제 설정 및 이행 관리하며, 대내외 대응 방향성 확산",
            ["기후 대응 전략을 총괄하고, 과제 설정 및 이행 관리하며,", "대내외 대응 방향성 확산"],
        ),
        (
            "기후 로드맵을 수립했으며, 자체발전과 PPA를 통해 RE100을 달성할 계획입니다.",
            ["기후 로드맵을 수립했으며,", "자체발전과 PPA를 통해 RE100을 달성할 계획입니다."],
        ),
        (
            "효율을 설계에 반영하고 에너지 절감 기술 개발에 선제적으로 투자",
            ["효율을 설계에 반영하고", "에너지 절감 기술 개발에 선제적으로 투자"],
        ),
        (
            "설비를 도입하고, 태양광 연계 시 전력 소비 20% 절감 예상",
            ["설비를 도입하고,", "태양광 연계 시 전력 소비 20% 절감 예상"],
        ),
        ("설비를 도입하고 전력 소비 20% 절감 예상", ["설비를 도입하고", "전력 소비 20% 절감 예상"]),
        (
            "2030년까지 해외 전환을 완료하고, 2040년까지 전 사업장 전환을 완료할 예정으로, "
            "이는 RE100이 권고하는 2050년 전환보다 10년 앞선 목표입니다.",
            [
                "2030년까지 해외 전환을 완료하고, 2040년까지 전 사업장 전환을 완료할 예정으로,",
                "이는 RE100이 권고하는 2050년 전환보다 10년 앞선 목표입니다.",
            ],
        ),
    ],
)
def test_literal_independent_clauses(text, expected):
    spans, changes = refine_selected([selected(text)], text, kind="paragraph")
    assert [s["quote"] for s in spans] == expected
    assert changes
    validate_extraction_response({"spans": spans}, text, reject_unclosed_quotations=True)
    assert all(text[s["char_start"] : s["char_end"]] == s["quote"] for s in spans)


@pytest.mark.parametrize(
    "text",
    [
        "2030년까지 해외 전환을 완료하고, 2040년까지 전 사업장 전환을 완료할 예정입니다.",
        "RE100 이행을 위해 친환경 에너지 확대가 중요하며, 이를 위한 검토 프로세스를 수립했습니다.",
        "환경 정책을 수립하고 이를 이사회에서 승인합니다.",
        "기후 정책을 수립하고, 이를 통해 감축 목표 달성 기반을 마련합니다.",
        "설비를 도입하고 에너지 절감 효과가 기대됩니다.",
        "태양광 연계 시 설비를 도입하고, 전력 소비 20% 절감 예상",
        "환경 정책을 수립하고, 또한",
        "목표 ‘환경 정책을 수립하고, 전담 부서에서 운영’의 달성을 지원합니다.",
        "환경 대응(정책을 수립하고, 전담 부서에서 운영)을 지원합니다.",
        "Scope 1, 2 및 3 배출량의 1,000 tCO2e 감축을 추진합니다.",
        "태양광 연계 시 전력 변환 및 배전 효율 향상으로 에너지 효율 20% 향상 예상",
        "• 환경 정책을 수립하고\n이를 운영한다.",
    ],
)
def test_dependencies_lists_and_non_numeric_expectations_keep_parent(text):
    span = selected(text)
    assert refine_selected([span], text, kind="paragraph") == ([span], [])


def test_unknown_and_unselected_content_remain_unchanged():
    text = "환경 정책을 수립하고, 전담 부서에서 관리한다."
    span = selected(text)
    span.update(kind="unknown", reason="unreadable")
    assert refine_selected([span], text, kind="paragraph") == ([span], [])
    assert refine_selected([], text, kind="paragraph") == ([], [])


def test_forecast_does_not_borrow_means_installation_year():
    text = "2024년 설비를 도입하고, 전력 소비 20% 절감 예상"
    spans, _ = refine_selected([selected(text)], text, kind="paragraph")
    assert [s["quote"] for s in spans] == ["2024년 설비를 도입하고,", "전력 소비 20% 절감 예상"]
    assert "2024" not in spans[1]["quote"]


def test_expansion_never_truncates_original_selection():
    text = " ".join("환경 정책을 승인하며," for _ in range(65)) + " 성과를 모니터링"
    span = selected(text)
    assert refine_selected([span], text, kind="paragraph") == ([span], [])


def test_j7_profiles_are_distinct_and_old_j3_hash_is_frozen():
    from proofops.application.analysis_profile import J3_POLICY, J7_POLICY, J7_PROFILE, policy_for
    from proofops.domain.provenance import canonical_hash
    from proofops_agent.upstage_extraction import _profile_with_options

    assert (
        canonical_hash(J3_POLICY)
        == "7cfad49df307f64676e005323b21b08804702c714335bf2222b27fa07dab6af6"
    )
    assert policy_for(J7_PROFILE) == J7_POLICY
    old = _profile_with_options(
        source_ids=True, extraction_pb1=True, extraction_w9=True, extraction_j3=True
    )
    new = _profile_with_options(
        source_ids=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=True,
        extraction_j7=True,
    )
    assert old.prompt_sha256 == new.prompt_sha256
    assert old.rule_sha256 != new.rule_sha256
    assert old.rule_sha256 == "2aec21e6c502afd02a706c0ed01122872500dbbe09a7b936788d0242d7a00606"
    with pytest.raises(ValueError, match="J7"):
        _profile_with_options(extraction_j7=True)
