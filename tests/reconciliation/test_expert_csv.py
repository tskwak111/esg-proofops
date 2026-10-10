"""Expert prose must not become gold or search coverage."""

import pytest

from evaluation.reconciliation_eval_kia import evaluate_gold, expert_csv_manifest


def test_eight_rows_without_approved_gold_are_not_run(tmp_path):
    path = tmp_path / "expert.csv"
    path.write_text(
        "row,check,search_coverage,expected_status\n"
        + "".join(f"r{i},C{i % 4 + 1},complete,matched\n" for i in range(8)),
        encoding="utf-8-sig",
    )
    manifest, provenance = expert_csv_manifest(
        path, dataset_id="unapproved", case_id_column="row", item_column="check", expected_rows=8
    )
    result = evaluate_gold(manifest)
    assert result["semantic_accuracy"]["status"] == "not_run"
    assert result["semantic_accuracy"]["denominator"] == 0
    assert all(row["gold"] is None for row in manifest["cases"])
    assert provenance["coverage_created"] is False
    assert provenance["ignored_columns"] == ["search_coverage", "expected_status"]


@pytest.mark.parametrize(
    "csv_text",
    [
        "case_id,item\nx,C1\nx,C2\n",
        "case_id,item\nx,C5\n",
        "case_id,item\nx,C1,extra\n",
        "case_id,item,item\nx,C1,C1\n",
    ],
)
def test_invalid_csv_fails_closed(tmp_path, csv_text):
    path = tmp_path / "expert.csv"
    path.write_text(csv_text, encoding="utf-8")
    with pytest.raises(ValueError):
        expert_csv_manifest(path, dataset_id="test", case_id_column="case_id", item_column="item")


def test_row_count_is_explicit(tmp_path):
    path = tmp_path / "expert.csv"
    path.write_text("case_id,item\nx,C1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="csv_row_count_mismatch"):
        expert_csv_manifest(
            path, dataset_id="test", case_id_column="case_id", item_column="item", expected_rows=8
        )


def test_only_separate_matching_approval_manifest_supplies_gold(tmp_path):
    path = tmp_path / "expert.csv"
    path.write_text("case_id,item,expected_status\nx,C1,needs_explanation\n", encoding="utf-8")
    explicit = {
        "schema_version": "reconciliation-gold-1",
        "dataset_id": "test",
        "cases": [
            {
                "case_id": "x",
                "item": "C1",
                "synthetic": False,
                "observed_status": "matched",
                "gold": {
                    "expected_status": "matched",
                    "approved_by": "fixture-approver",
                    "approved_at": "2026-10-09T00:00:00Z",
                    "evidence": {"reference": "fixture-approval", "sha256": "a" * 64},
                },
            }
        ],
    }
    manifest, _ = expert_csv_manifest(
        path,
        dataset_id="test",
        case_id_column="case_id",
        item_column="item",
        approved_manifest=explicit,
    )
    result = evaluate_gold(manifest)
    assert result["semantic_accuracy"]["denominator"] == 1
    assert result["semantic_accuracy"]["numerator"] == 1
    explicit["cases"][0]["case_id"] = "orphan"
    with pytest.raises(ValueError, match="csv_orphan_approval"):
        expert_csv_manifest(
            path,
            dataset_id="test",
            case_id_column="case_id",
            item_column="item",
            approved_manifest=explicit,
        )
