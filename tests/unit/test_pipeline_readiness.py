"""Offline accounting must not convert missing evidence into a success signal."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evaluation.pipeline_readiness import (
    build_report,
    dependency_readiness,
    extraction_status,
    main,
    policy_readiness,
    provider_readiness,
    usage_summary,
)


def test_draft_policy_is_explicitly_unapproved():
    assert policy_readiness({"approved": False})["reason"] == "policy_unapproved"
    assert policy_readiness(None)["reason"] == "policy_missing"


def test_azure_configuration_and_solar_expiry_are_independent_of_transport():
    report = dependency_readiness(
        {},
        datetime(2026, 10, 10, tzinfo=UTC),
        {"reason": "AZURE_CREDENTIALS_REQUIRED", "parsing": "blocked"},
    )
    assert report["azure"]["configuration_status"] == "configuration_error"
    assert report["azure"]["recorded_pilot_reason"] == "AZURE_CREDENTIALS_REQUIRED"
    assert report["azure"]["transport_status"] == "not_probed"
    assert report["solar_capacity_policy"]["status"] == "expired"
    assert len(report["solar_capacity_policy"]["revisions"]) == 2
    assert report["solar_capacity_policy"]["approval_granted"] is False


def test_azure_values_never_leak_and_unexpired_policy_is_not_approved():
    secret = "secret-value"
    report = dependency_readiness(
        {
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": secret,
            "AZURE_DOCUMENT_INTELLIGENCE_KEY": secret,
        },
        datetime(2026, 9, 20, tzinfo=UTC),
        None,
    )
    assert secret not in json.dumps(report)
    assert report["azure"]["configuration_status"] == "configured_unprobed"
    assert report["solar_capacity_policy"]["status"] == "not_verified"


@pytest.mark.parametrize(
    ("raw", "claims", "expected"),
    [
        ("failed: OPENROUTER_REQUEST_FAILED", 0, "transport_error"),
        ("UPSTAGE_HTTP_401", 0, "transport_error"),
        ("OPENROUTER_API_KEY_MISSING_OR_INVALID", 0, "configuration_error"),
        ("MODEL_SPAN_OR_SCHEMA_INVALID", 0, "extraction_error"),
        ("succeeded", 0, "no_claims"),
        ("succeeded", None, "completed_count_unknown"),
        ("succeeded", 2, "claims_extracted"),
        (None, 0, "unknown"),
    ],
)
def test_failure_is_not_no_claims(raw, claims, expected):
    assert extraction_status(raw, claims) == expected


def test_provider_presence_is_not_authorization_and_never_leaks_secret():
    secret = "do-not-print-this-secret"
    report = provider_readiness("openrouter", "openai/gpt-6-luna", {"OPENROUTER_API_KEY": secret})
    assert secret not in json.dumps(report)
    assert report["configuration_status"] == "configured_unprobed"
    assert report["ready_for_live_call"] is False
    assert report["transport_status"] == "not_probed"
    invalid = provider_readiness("openrouter", secret, {"OPENROUTER_API_KEY": "bad key"})
    assert secret not in json.dumps(invalid)
    assert invalid["reason_codes"] == ["credential_missing_or_invalid", "unsupported_model"]


def test_reservation_never_becomes_actual_cost():
    report = usage_summary({"committed_or_reserved_usd": "0.32", "unsettled": 16})
    assert report["committed_or_reserved_usd"] == "0.32"
    assert report["actual_cost_usd"] is None
    assert report["unknown_reservation_cost_usd"] is None
    assert report["cost_with_vat_reserve_usd"] is None
    assert usage_summary({"actual_cost_usd": "NaN"})["actual_cost_usd"] is None
    assert usage_summary({"actual_cost_usd": "0"})["actual_cost_usd"] == "0"


def test_component_counts_and_policy_do_not_make_pipeline_ready():
    report = build_report(
        {
            "original_pipeline": {
                "extract": "failed: OPENROUTER_REQUEST_FAILED",
                "reconciliation": "not_run",
            },
            "component_check": {
                "same_original_input_packets": 16,
                "processed": 13,
                "rejected": 3,
                "accepted_claim_candidates": 14,
            },
        },
        provider="upstage",
        environ={},
        policy={"approved": True, "synthetic_only": True},
    )
    extraction = report["stages"]["4_extraction"]
    assert extraction["service_claims"] is None
    assert extraction["component_only"]["packet_accounting_balanced"] is True
    reconciliation = report["stages"]["5_reconciliation"]
    assert [gap["fact"] for gap in reconciliation["producer_gaps"]] == [
        "currency_amount",
        "revenue_share",
    ]
    assert reconciliation["policy"]["domain_approval_verified"] is False
    assert reconciliation["final_grade"] is None
    assert report["pipeline_ready"] is False


def test_mismatched_accounting_is_visible():
    report = build_report(
        {
            "component_check": {
                "same_original_input_packets": 16,
                "processed": 12,
                "rejected": 3,
            }
        },
        provider="upstage",
        environ={},
    )
    assert report["stages"]["4_extraction"]["component_only"]["packet_accounting_balanced"] is False


def test_cli_strict_exit_and_output_overwrite(tmp_path, capsys):
    comparison, output = tmp_path / "comparison.json", tmp_path / "report.json"
    comparison.write_text("{}", encoding="utf-8")
    argv = ["--comparison", str(comparison), "--provider", "openrouter", "--output", str(output)]
    assert main([*argv, "--strict"]) == 1
    original = output.read_bytes()
    assert main(argv) == 2
    assert output.read_bytes() == original
    assert "INVALID_INPUT_OR_OUTPUT" in capsys.readouterr().out


def test_cli_input_errors_are_redacted(tmp_path, capsys):
    comparison = tmp_path / "secret-value.json"
    comparison.write_text('{"rows": "secret-value"}', encoding="utf-8")
    assert main(["--comparison", str(comparison), "--provider", "upstage"]) == 2
    assert "secret-value" not in capsys.readouterr().out


def test_naver_baseline_when_available():
    path = Path(__file__).resolve().parents[2] / ".local/naver-baseline/comparison.json"
    if not path.exists():
        pytest.skip("local NAVER audit artifact not distributed")
    report = build_report(
        json.loads(path.read_text(encoding="utf-8")), provider="openrouter", environ={}
    )
    assert report["stages"]["4_extraction"]["service_status"] == "transport_error"
    assert report["benchmark"]["excluded_before_extraction"] == 14
    assert report["benchmark"]["semantic_accuracy"] is None
    assert report["ledger"][1]["actual_cost_usd"] is None
