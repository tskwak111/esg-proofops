"""Claim signals improve selection without changing admission or old replay."""

from copy import deepcopy

import pytest

from evaluation.report_scope import (
    RANKING_POLICY_SHA256,
    SUPPORT_POLICY_SHA256,
    SUPPORT_VERSION,
    build_plan,
    validate_selection,
)
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


def test_quantified_assurance_signal_promotes_page_without_widening_scope():
    study = build_map(
        5,
        [dict(page=1, title="Environment", path=["Environment"], method="outline")],
    )
    study.update(
        source_path="/generic.pdf",
        source_sha256="a" * 64,
        method="outline",
        issues=[],
        page_count=5,
    )
    texts = {
        page: (
            f"{46 + page}\nClimate emissions target 2030: reduce Scope 1 emissions by 25%. "
            + "Renewable energy installation is implemented through a PPA. "
            + f"This is a distinct environmental narrative page {page}. "
            + "Environmental monitoring covers climate and emissions. " * 5
        )
        for page in range(1, 5)
    }
    texts[5] = (
        "51\n"
        + "Climate emissions and renewable energy results are reported here. " * 5
        + "The verified environmental result is 4,753 tCO2eq under limited assurance."
    )

    old = build_plan(study, texts, max_environment_pages=4, ranking_policy="W4-v2")
    new = build_plan(
        study,
        texts,
        max_environment_pages=4,
        ranking_policy=SUPPORT_VERSION,
    )

    assert 5 not in old["selected_claim_pages"]
    assert 5 in new["selected_claim_pages"]
    assert len(old["selected_claim_pages"]) == len(new["selected_claim_pages"]) == 4
    assert len(new["selected_claim_pages"]) <= 10
    page = next(record for record in new["pages"] if record["page"] == 5)
    assert page["claim_selection_decision"] == {
        "stage": "claim_page_selection",
        "selected": True,
        "candidate_rank": 1,
        "extraction_status": "not_evaluated",
        "reason": "selected_by_same_page_quantified_assurance_priority",
        "ranking_only": True,
        "evidence_verified": False,
    }
    assert [entry for entry in new["printed_page_map"] if entry["printed_label"] == "51"] == [
        dict(
            printed_label="51",
            pdf_page=5,
            mapping_method="verified_consecutive_native_header_run",
            run_start_pdf_page=1,
            run_end_pdf_page=5,
        )
    ]
    assert new["policy_sha256"] == SUPPORT_POLICY_SHA256
    assert validate_selection(new, "a" * 64, 5)["claim_pages"] == new["selected_claim_pages"]


def test_quantified_assurance_signal_never_crosses_pages_or_promotes_appendix():
    from evaluation.scope_claim_signals import claim_support_signals

    _, page50 = claim_support_signals(
        "ISO 14001 environmental management certification; no quantitative result.", []
    )
    _, page51 = claim_support_signals(
        "Environmental emissions result: 4,753 tCO2eq. Limited assurance was completed.", []
    )
    assert page50["same_page_quantified_assurance"] == 0
    assert page51["same_page_quantified_assurance"] == 1

    source = build_map(
        6,
        [
            dict(page=1, title="Environment", path=["Environment"], method="outline"),
            dict(page=6, title="Appendix", path=["Appendix"], method="outline"),
        ],
    )
    source.update(
        source_path="/generic.pdf",
        source_sha256="a" * 64,
        method="outline",
        issues=[],
        page_count=6,
    )
    page_texts = {page: "Climate emissions renewable energy. " * 8 for page in range(1, 6)}
    page_texts[5] = (
        "Independent Assurance Statement\nEnvironmental emissions result 4,753 tCO2eq. "
        "Limited assurance was completed."
    )
    plan = build_plan(source, page_texts, ranking_policy=SUPPORT_VERSION)
    record = next(item for item in plan["pages"] if item["page"] == 5)
    assert record["category"] == "assurance"
    assert record["claim_selected"] is False
    assert 5 not in plan["claim_candidate_pages"]


def test_printed_page_map_requires_a_consecutive_native_label_run():
    from evaluation.report_scope import _verified_native_printed_page_map

    mapping = _verified_native_printed_page_map(
        {
            1: "Cover page",
            2: "1\nBody",
            3: "2\nBody",
            4: "3\nBody",
            5: "Unrelated title\n99\nBody",
            6: "Other page",
        }
    )
    assert [(item["printed_label"], item["pdf_page"]) for item in mapping] == [
        ("1", 2),
        ("2", 3),
        ("3", 4),
    ]
    assert {item["run_start_pdf_page"] for item in mapping} == {2}
    assert {item["run_end_pdf_page"] for item in mapping} == {4}


def test_new_opt_in_hash_does_not_change_w4_or_as1_replay_hashes():
    study, texts = inputs()
    as1 = build_plan(study, texts, ranking_policy="AS1-v1")
    w4 = build_plan(study, texts, ranking_policy="W4-v2")
    w5 = build_plan(study, texts, ranking_policy=SUPPORT_VERSION)

    assert (
        as1["policy_sha256"] == "f13af2b8475ee1b3bb2fdfae111dea98cb0d8372e33efcd4d4b134378056e231"
    )
    assert w4["policy_sha256"] == RANKING_POLICY_SHA256
    assert w4["policy_sha256"] == "542b59b0512b48f5e88b8ef508a64072a3112e2b6ec97bbbcbbadc2ce038f986"
    assert w5["policy_sha256"] == SUPPORT_POLICY_SHA256
    assert w5["policy_sha256"] == "2d4e44da6505e873151bc172ae999a2307a1ec6b552c9c5912be049155c4e264"
    assert w5["policy_sha256"] not in {as1["policy_sha256"], w4["policy_sha256"]}


@pytest.mark.parametrize("version", [[], {}, None])
def test_malformed_policy_version_is_rejected(version):
    study, texts = inputs()
    plan = build_plan(study, texts)
    plan["version"] = version
    with pytest.raises(ValueError, match="unsupported scope policy"):
        validate_selection(plan, "a" * 64, 16)
