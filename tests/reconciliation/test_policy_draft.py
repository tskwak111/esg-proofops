"""Draft production cannot turn examples or source assertions into approval."""

import hashlib
import json
from pathlib import Path

import pytest
from proofops.application.reconciliation.schema import validate_schema
from proofops.application.reconciliation.service import reconcile

from evaluation.reconciliation_policy_draft import build_policy_draft, main
from tests.reconciliation.test_policy import _case

SOURCE = Path(__file__).parents[2] / "config/accounting/reconciliation_rules.yaml"


def test_draft_preserves_unresolved_decisions_and_exact_source_hash():
    before = SOURCE.read_bytes()
    policy = build_policy_draft(SOURCE, version="review-draft", coverage_policy_id="pending")
    validate_schema("policy", policy)
    assert policy["source_policy_sha256"] == hashlib.sha256(before).hexdigest()
    assert policy["approved"] is False
    assert policy["approved_by"] is policy["approved_on"] is None
    assert policy["c3_threshold"] is None
    assert policy["allowed_capex_account_ids"] == []
    assert policy["c3_account_mapping_approved"] is False
    assert policy["current_stage"] == 1 and "C5" not in policy["enabled_items"]
    assert SOURCE.read_bytes() == before


def test_draft_without_registry_is_blocked_by_real_service(tmp_path):
    packet, _, reader, documents, coverage = _case(tmp_path)
    policy = build_policy_draft(SOURCE, version="draft", coverage_policy_id="pending")
    result = reconcile(
        packet,
        policy,
        source_reader=reader,
        explanation_search=lambda _: [],
        policy_registry={},
        coverage_registry=coverage,
        document_registry=documents,
    )
    assert result["execution_state"] == "blocked"
    assert "policy_unapproved" in result["reason_codes"]


def test_cli_writes_new_file_only_and_ignores_source_approval(tmp_path):
    source = tmp_path / "source.yaml"
    source.write_text("approved: true\nannual_capex_multiple: 5.0\n", encoding="utf-8")
    output = tmp_path / "draft.json"
    args = [
        "--source",
        str(source),
        "--version",
        "draft",
        "--coverage-policy-id",
        "pending",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    before = output.read_bytes()
    assert json.loads(before)["approved"] is False
    assert json.loads(before)["c3_threshold"] is None
    assert main(args) == 2
    assert output.read_bytes() == before


@pytest.mark.parametrize("version,coverage", [("", "id"), ("id", " ")])
def test_requires_explicit_identifiers(version, coverage):
    with pytest.raises(ValueError):
        build_policy_draft(SOURCE, version=version, coverage_policy_id=coverage)
