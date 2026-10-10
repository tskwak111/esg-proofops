"""Page/note inventory must be completely reviewed before absence is asserted."""

import pytest

from tests.reconciliation.test_service import _call, _case


def _manifest(case):
    rows = []
    for document_id, document in case[3].items():
        document["coverage_units"] = [
            {"unit_id": "page-1", "kind": "page", "locator": "page:1"},
            {"unit_id": "note-1", "kind": "note", "locator": "note:1"},
        ]
        for binding in document["source_bindings"].values():
            binding["coverage_unit_id"] = "page-1"
        for unit in document["coverage_units"]:
            rows.append(
                {
                    "document_id": document_id,
                    "artifact_sha256": document["artifact_sha256"],
                    "unit_id": unit["unit_id"],
                    "locator": unit["locator"],
                    "readable": True,
                    "reviewed": True,
                    "source_ids": list(document["source_bindings"])
                    if unit["kind"] == "page"
                    else [],
                }
            )
    case[4]["receipt"]["coverage_manifest"] = rows
    return rows


def test_complete_page_and_note_manifest_and_legacy_both_pass(tmp_path):
    case = _case(tmp_path)
    assert _call(case)["status"] == "matched"
    _manifest(case)
    assert _call(case)["status"] == "matched"


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "unreadable",
        "unreviewed",
        "hash",
        "locator",
        "duplicate",
        "source",
        "inventory",
        "manifest",
    ],
)
def test_invalid_manifest_cannot_claim_complete(tmp_path, failure):
    case = _case(tmp_path)
    rows = _manifest(case)
    if failure == "missing":
        rows.pop()
    elif failure == "unreadable":
        rows[0]["readable"] = False
    elif failure == "unreviewed":
        rows[0]["reviewed"] = False
    elif failure == "hash":
        rows[0]["artifact_sha256"] = "0" * 64
    elif failure == "locator":
        rows[0]["locator"] = "page:99"
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "source":
        rows[0]["source_ids"] = ["forged"]
    elif failure == "inventory":
        del case[3]["sr-v1"]["coverage_units"]
    else:
        del case[4]["receipt"]["coverage_manifest"]
    result = _call(case)
    assert result["execution_state"] == "blocked"
    assert result["status"] is None


@pytest.mark.parametrize("owner,key", [("receipt", "candidate_limit"), ("document", "limits")])
def test_truncated_catalog_blocks_complete_even_without_manifest(tmp_path, owner, key):
    case = _case(tmp_path)
    target = case[4]["receipt"] if owner == "receipt" else case[3]["sr-v1"]
    target[key] = {"truncated": True}
    assert _call(case)["reason_codes"] == ["candidate_catalog_truncated_incomplete_search"]


@pytest.mark.parametrize(
    "catalog", [{"state": "incomplete"}, {"state": "complete"}, {"state": "unknown"}, "complete"]
)
def test_missing_catalog_cannot_fall_back_to_legacy_completeness(tmp_path, catalog):
    case = _case(tmp_path)
    case[3]["sr-v1"]["coverage_catalog"] = catalog
    result = _call(case)
    assert result["execution_state"] == "blocked"
    assert result["reason_codes"][0] in {"coverage_incomplete", "coverage_unverified"}
