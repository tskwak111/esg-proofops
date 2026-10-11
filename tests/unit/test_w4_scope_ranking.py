"""Claim signals improve selection without changing admission or old replay."""

from copy import deepcopy

import pytest

from evaluation.report_scope import build_plan, validate_selection
from evaluation.report_sections import build_map


def inputs():
    study = build_map(
        16,
        [
            dict(page=1, title="Environment", path=["Environment"], method="outline"),
            dict(page=13, title="Appendix", path=["Appendix"], method="outline"),
        ],
    )
    study.update(
        source_path="/report.pdf",
        source_sha256="a" * 64,
        method="outline",
        issues=[],
        page_count=16,
    )
    texts = {
        p: ("Climate carbon emissions renewable energy. " * 6 + f"Chapter {p}")
        for p in range(1, 17)
    }
    # Long actionable page loses on hits/characters despite target and results.
    texts[12] = (
        "Our company provides these operational details. "
        * 30
        + "We will reduce Scope 1 carbon emissions 40% by 2030. "
        "Renewable energy generation reached 250 MWh in 2024. "
        "We implemented a PPA to deliver the carbon reduction plan."
    )
    texts[14] = "Environmental data\n" + texts[12]
    texts[15] = "Independent Assurance Statement\n" + texts[12]
    return study, texts


def test_actionable_long_page_outranks_dense_environmental_intro():
    study, texts = inputs()
    plan = build_plan(study, texts)
    assert 12 in plan["selected_claim_pages"]
    assert not {14, 15} & set(plan["selected_claim_pages"])
    assert len(plan["selected_claim_pages"]) <= 10
    assert len(plan["selected_evidence_pages"]) <= 30
    assert plan["source_quality"] == "unverified"


def test_prior_policy_hash_and_selection_replay_are_preserved():
    study, texts = inputs()
    old = build_plan(study, texts, ranking_policy="AS1-v1")
    assert (
        old["policy_sha256"] == "f13af2b8475ee1b3bb2fdfae111dea98cb0d8372e33efcd4d4b134378056e231"
    )
    assert 12 not in old["selected_claim_pages"]
    assert "claim_signal_score" not in old["pages"][11]
    new = build_plan(study, texts)
    assert new["policy_sha256"] != old["policy_sha256"]
    for plan in (old, new):
        assert validate_selection(plan, "a" * 64, 16)["claim_pages"] == plan["selected_claim_pages"]
        altered = deepcopy(plan)
        altered["pages"][11]["environmental_hits"] += 1
        with pytest.raises(ValueError, match="immutable"):
            validate_selection(altered, "a" * 64, 16)


def test_high_signal_conflict_unreadable_and_other_pages_stay_excluded():
    study, texts = inputs()
    study["conflict_pages"] = [12]
    plan = build_plan(study, texts)
    assert 12 not in plan["selected_claim_pages"]
    assert 12 in plan["conflict_pages"]


def test_new_policy_enforces_evidence_union_cap():
    study, texts = inputs()
    with pytest.raises(ValueError, match="30"):
        build_plan(study, texts, max_evidence_pages=31)


def test_korean_target_year_and_unit_first_environment_table_are_ranked():
    from evaluation.scope_claim_signals import claim_signals

    score, signals = claim_signals(
        "2030년까지 온실가스 감축 목표\n"
        "온실가스 Scope 1 배출량 tCO2-eq 719,949 696,590 679,822\n"
        "재생에너지 전환비율 % 7.7 12.8 16.7",
        [],
    )
    assert score > 0
    assert signals["target_year"] == 1
    assert signals["metric"] >= 2
    assert signals["table_rows"] == 2


def test_non_environment_numbers_do_not_create_local_claim_signals():
    from evaluation.scope_claim_signals import claim_signals

    _, signals = claim_signals("2030年 revenue grew 40%. Employees implemented training.", [])
    assert signals["target_year"] == signals["metric"] == signals["implementation"] == 0


@pytest.mark.parametrize("version", [[], {}, None])
def test_malformed_policy_version_is_rejected(version):
    study, texts = inputs()
    plan = build_plan(study, texts)
    plan["version"] = version
    with pytest.raises(ValueError, match="unsupported scope policy"):
        validate_selection(plan, "a" * 64, 16)
