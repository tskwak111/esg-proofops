"""Harness fixtures only: these are not Kia observations or approved financial gold."""

import json
from copy import deepcopy

import pytest

from evaluation.reconciliation_eval_kia import evaluate_gold, main


def manifest():
    return {
        "schema_version": "reconciliation-gold-1",
        "dataset_id": "harness-only",
        "cases": [
            {
                "case_id": "fixture-1",
                "item": "C1",
                "synthetic": True,
                "observed_status": "matched",
                "gold": {
                    "expected_status": "matched",
                    "approved_by": "fixture-reviewer",
                    "approved_at": "2026-10-09T01:00:00Z",
                    "evidence": {"reference": "fixture-approval-record", "sha256": "a" * 64},
                },
            }
        ],
    }


def test_synthetic_is_never_semantic_accuracy():
    data = manifest()
    before = deepcopy(data)
    report = evaluate_gold(data)
    assert data == before
    assert report["semantic_accuracy"]["status"] == "not_run"
    assert report["semantic_accuracy"]["value"] is None
    assert report["semantic_accuracy"]["denominator"] == 0
    assert report["synthetic_comparisons"] == 1
    assert report["cases"][0]["correct"] is True
    assert report["exclusion_counts"] == {"synthetic_fixture": 1}


def test_missing_gold_is_not_run_and_empty_dataset_has_no_score():
    data = manifest()
    data["cases"][0]["gold"] = None
    report = evaluate_gold(data)
    assert report["cases"][0]["status"] == "not_run"
    assert report["cases"][0]["correct"] is None
    assert "missing_gold" in report["cases"][0]["exclusion_reasons"]
    data["cases"] = []
    assert evaluate_gold(data)["semantic_accuracy"]["value"] is None


def test_denominator_counts_only_complete_declared_real_rows():
    # Exercise arithmetic using fabricated declarations; this is not a real-world score.
    data = manifest()
    case = data["cases"][0]
    case["synthetic"] = False
    for identifier, observed in [("wrong", "needs_explanation"), ("missing", None)]:
        row = deepcopy(case)
        row.update(case_id=identifier, observed_status=observed)
        data["cases"].append(row)
    report = evaluate_gold(data)
    metric = report["semantic_accuracy"]
    assert (metric["numerator"], metric["denominator"], metric["value"]) == (1, 2, 0.5)
    assert report["excluded_rows"] == 1
    assert report["exclusion_counts"] == {"missing_observed_status": 1}


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved_by", " "),
        ("approved_at", "2026-10-09"),
        ("approved_at", "2026-10-09T01:00:00"),
        ("approved_at", "invalid"),
        ("expected_status", "blocked"),
        ("expected_status", None),
        ("evidence", {}),
        ("evidence", {"reference": "x", "sha256": "bad"}),
    ],
)
def test_invalid_gold_is_rejected_not_silently_excluded(field, value):
    data = manifest()
    data["cases"][0]["gold"][field] = value
    with pytest.raises(ValueError):
        evaluate_gold(data)


@pytest.mark.parametrize("field", ["expected_status", "approved_by", "approved_at", "evidence"])
def test_approval_fields_are_required(field):
    data = manifest()
    del data["cases"][0]["gold"][field]
    with pytest.raises(ValueError):
        evaluate_gold(data)


def test_duplicate_rows_and_coverage_assertions_cannot_be_gold():
    data = manifest()
    data["cases"].append(deepcopy(data["cases"][0]))
    with pytest.raises(ValueError, match="duplicate_case_id"):
        evaluate_gold(data)
    data = manifest()
    data["cases"][0]["gold"]["search_coverage"] = "complete"
    with pytest.raises(ValueError, match="gold_fields_invalid"):
        evaluate_gold(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("synthetic", "false"),
        ("synthetic", 0),
        ("item", "C5"),
        ("observed_status", "blocked"),
        ("case_id", " "),
    ],
)
def test_case_fields_are_strict(field, value):
    data = manifest()
    data["cases"][0][field] = value
    with pytest.raises(ValueError):
        evaluate_gold(data)


def test_cli_strict_json_and_immutable_output(tmp_path):
    source, output = tmp_path / "gold.json", tmp_path / "report.json"
    source.write_text(json.dumps(manifest()), encoding="utf-8")
    args = ["--manifest", str(source), "--output", str(output)]
    assert main(args) == 0
    before = output.read_bytes()
    assert main(args) == 2
    assert output.read_bytes() == before
    source.write_text('{"dataset_id":"a","dataset_id":"b"}', encoding="utf-8")
    assert main(["--manifest", str(source), "--output", str(tmp_path / "invalid.json")]) == 2
    assert not (tmp_path / "invalid.json").exists()
