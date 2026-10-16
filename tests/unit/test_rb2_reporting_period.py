from proofops.domain.provenance import canonical_hash

from evaluation.reporting_period import detect_reporting_period, validate_detection


def test_report_period_and_scope_heading_preserves_original_spans():
    from evaluation.rb2_reporting_period import detect

    text = (
        "보고서 기간과 범위 본 보고서는 2024년 1월 1일부터 12월 31일까지의 재무 및 "
        "비재무 성과를 기반으로 작성되었습니다. 이해관계자의\r\n의사결정에 영향을 줄 수 "
        "있는 중요한 사항은 2025년 상반기 성과까지 포함하고 있습니다."
    )
    assert detect_reporting_period({2: text}, 101, "a" * 64)["status"] == "not_found"
    result = detect({2: text}, 101, "a" * 64)
    assert result["selected"] == dict(
        report_year=2024, period_start="2024-01-01", period_end="2024-12-31"
    )
    assert result["exceptions"]
    validate_detection(result, "a" * 64)
    ref = result["candidates"][0]["source_ref"]
    assert ref["verification_state"] == "inspection_only"
    assert ref["quote"] == text[ref["char_start"] : ref["char_end"]]


def test_new_heading_does_not_adopt_targets_or_conflicts():
    from evaluation.rb2_reporting_period import detect

    for text in (
        "목표 보고서 기간과 범위: 2050년 1월 1일부터 12월 31일까지 탄소중립.",
        "보고서 기간과 범위: 일부 성과는 2025년 1월 1일부터 12월 31일까지입니다.",
        "보고서 기간과 범위: 2024년 2월 30일부터 12월 31일까지.",
        "보고서 기간과 범위: 2023 회계연도. 보고기간: 2024 회계연도.",
    ):
        assert detect({2: text}, 101, "a" * 64)["selected"] is None


def test_rb2_registration_and_v29_default_leave_historical_hashes():
    from proofops.application.analysis_profile import (
        FINALS_I25_POLICY,
        FINALS_I27_POLICY,
        FINALS_I28_POLICY,
        FINALS_I29_POLICY,
        FXH_POLICY,
        RB2_POLICY,
        V2_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )

    assert canonical_hash(FXH_POLICY) == (
        "aabfb9ee0a2351cb84b39b1474ccd45cbeb50bb33dee39d6f9a0f39189c41e09"
    )
    assert canonical_hash(FINALS_I25_POLICY) == (
        "2ed6dc6869c35a152887db1d55629c19a0902e95b8b50b64e5f52af25c86f4c0"
    )
    assert V2_POLICY == FINALS_I29_POLICY
    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I28_POLICY)) == FINALS_I28_POLICY
    )
    assert canonical_hash(FINALS_I27_POLICY) == (
        "fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804"
    )
    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I27_POLICY)) == FINALS_I27_POLICY
    )
    assert V2_POLICY["parser_output_policy"] == "rb2-output-v1"
    assert V2_POLICY["reporting_period_policy"] == "rb2-native-period-v1"
    assert policy_for(V2_PROFILE) == V2_POLICY
    pin = canonical_hash(RB2_POLICY)
    assert pin != canonical_hash(FXH_POLICY)
    assert policy_for(V2_PROFILE, pinned_hash=pin) == RB2_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == RB2_POLICY


def test_hosted_child_accepts_exact_rb2_pin_and_propagates_selector(tmp_path):
    from types import SimpleNamespace

    from proofops.application.analysis_profile import RB2_POLICY, V2_PROFILE, apply_pilot_profile

    from evaluation.hosted_r108 import prepare_argv
    from evaluation.rb2_reporting_period import configured_profile
    from tests.integration.test_mixed_parser import document

    source = tmp_path / "source.pdf"
    source.write_bytes(document().content)
    pin = canonical_hash(RB2_POLICY)
    config = dict(
        analysis_profile=V2_PROFILE,
        analysis_policy_sha256=pin,
        report_year=2024,
        period_start="2024-01-01",
        period_end="2024-12-31",
    )
    import json

    path = tmp_path / "live.json"
    path.write_text(json.dumps(config))
    assert configured_profile(path) == "rb2-native-period-v1"
    argv = prepare_argv(
        source,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        config,
        dict(analysis_profile_sha256=pin, pages=[1, 2, 3], claim_pages=[1]),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    args = SimpleNamespace(analysis_profile=V2_PROFILE, analysis_policy_sha256=pin)
    apply_pilot_profile(args)
    assert args.parser_output_policy == "rb2-output-v1"
