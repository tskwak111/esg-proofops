"""Fact periods and C4 denominator periods are registry evidence, never year guesses."""

import pytest

from evaluation.reconciliation_fixtures import build_case
from tests.reconciliation.test_integration import run_case


def _bindings(bundle, start="2024-01-01", end="2024-12-31"):
    for document in bundle["documents"].values():
        document["period_binding_required"] = True
        for binding in document["fact_bindings"].values():
            binding["period_binding"] = {"period_start": start, "period_end": end}
        for binding in document["source_bindings"].values():
            binding["period_binding"] = {"period_start": start, "period_end": end}


@pytest.mark.parametrize("name", ["c2-same-period", "c4-definition-and-method"])
def test_verified_periods_and_legacy_replay_match(tmp_path, name):
    bundle = build_case(name, tmp_path)
    assert run_case(bundle, tmp_path)["status"] == "matched"
    _bindings(bundle)
    assert run_case(bundle, tmp_path)["status"] == "matched"


def test_c2_cannot_substitute_report_period_for_missing_fact_period(tmp_path):
    bundle = build_case("c2-same-period", tmp_path)
    for document in bundle["documents"].values():
        document["period_binding_required"] = True
    assert run_case(bundle, tmp_path)["reason_codes"] == ["fact_period_binding_missing"]


@pytest.mark.parametrize(
    "start,end",
    [
        ("2023-01-01", "2023-12-31"),
        ("2023-07-01", "2024-06-30"),
        ("2022-01-01", "2024-12-31"),
        ("2024-02-30", "2024-12-31"),
    ],
)
def test_c2_mismatched_or_invalid_fact_period_blocks(tmp_path, start, end):
    bundle = build_case("c2-same-period", tmp_path)
    _bindings(bundle, start, end)
    assert run_case(bundle, tmp_path)["execution_state"] == "blocked"


@pytest.mark.parametrize(
    "start,end",
    [
        ("2023-07-01", "2024-06-30"),
        ("2022-01-01", "2024-12-31"),
    ],
)
def test_c2_verified_non_calendar_and_multi_year_periods_are_not_annualized(tmp_path, start, end):
    bundle = build_case("c2-same-period", tmp_path)
    _bindings(bundle, start, end)
    for role in ("sustainability", "financial"):
        fact = bundle["packet"][role]
        fact["normalized"] = f"{start}/{end}"
        for document in bundle["documents"].values():
            if fact["source_id"] in document["fact_bindings"]:
                document["fact_bindings"][fact["source_id"]]["normalized"] = fact["normalized"]
    assert run_case(bundle, tmp_path)["status"] == "matched"


@pytest.mark.parametrize("key", ["definition_source_ids", "calculation_source_ids"])
def test_c4_cross_year_definition_or_denominator_is_blocked(tmp_path, key):
    bundle = build_case("c4-definition-and-method", tmp_path)
    _bindings(bundle)
    source_id = bundle["packet"]["c4_context"][key][0]
    for document in bundle["documents"].values():
        if source_id in document["source_bindings"]:
            document["source_bindings"][source_id]["period_binding"] = {
                "period_start": "2023-01-01",
                "period_end": "2023-12-31",
            }
    assert run_case(bundle, tmp_path)["reason_codes"] == ["classification_period_mismatch"]
