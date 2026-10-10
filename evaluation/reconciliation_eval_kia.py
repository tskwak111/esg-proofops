"""Offline gold comparison, with no built-in Kia rows or inferred expert labels.

Input: {schema_version: reconciliation-gold-1, dataset_id: str, cases: [...]}.
Each case has case_id, item (C1-C4), synthetic (bool), observed_status (a 1.1
status or null), and gold (null or {expected_status, approved_by, approved_at,
evidence: {reference, sha256}}). Approval time must include a timezone. Evidence
identifies the operator-supplied approval record, not a search-coverage receipt.
The operator owns approver authentication and evidence verification; this offline
comparison validates declarations only and never creates policy/coverage approvals.
Missing gold stays not_run. Synthetic comparisons are harness checks only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.reconciliation_cli import InputRejected, load_json, write_json

STATUSES = {"matched", "needs_explanation", "not_applicable"}


def expert_csv_manifest(
    path: Path,
    *,
    dataset_id: str,
    case_id_column: str,
    item_column: str,
    approved_manifest: dict[str, Any] | None = None,
    expected_rows: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Import explicit row identities, never prose labels or coverage approvals.

    Column names are supplied by the operator because the actual expert CSV is
    not bundled. Gold/outcomes come only from a separately validated manifest.
    """
    payload = path.read_bytes()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise InputRejected("csv_headers_invalid")
    if not {case_id_column, item_column} <= set(reader.fieldnames):
        raise InputRejected("csv_identity_columns_missing")
    if case_id_column == item_column:
        raise InputRejected("csv_identity_columns_must_differ")
    rows = list(reader)
    if expected_rows is not None and len(rows) != expected_rows:
        raise InputRejected("csv_row_count_mismatch")
    explicit = {}
    if approved_manifest is not None:
        evaluate_gold(approved_manifest)
        if approved_manifest["dataset_id"] != dataset_id:
            raise InputRejected("csv_dataset_mismatch")
        explicit = {case["case_id"]: case for case in approved_manifest["cases"]}
    cases = []
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise InputRejected("csv_row_shape_invalid")
        case_id = _text(row[case_id_column], "csv_case_id")
        item = row[item_column]
        case = explicit.get(case_id) or dict(
            case_id=case_id, item=item, synthetic=False, observed_status=None, gold=None
        )
        if case["item"] != item:
            raise InputRejected("csv_item_mismatch")
        cases.append(case)
    if set(explicit) - {case["case_id"] for case in cases}:
        raise InputRejected("csv_orphan_approval")
    manifest = dict(schema_version="reconciliation-gold-1", dataset_id=dataset_id, cases=cases)
    evaluate_gold(manifest)
    provenance = dict(
        sha256=hashlib.sha256(payload).hexdigest(),
        row_count=len(rows),
        case_id_column=case_id_column,
        item_column=item_column,
        ignored_columns=[
            key for key in reader.fieldnames if key not in {case_id_column, item_column}
        ],
        coverage_created=False,
    )
    return manifest, provenance


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputRejected(f"{name}_invalid")
    return value


def _fields(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise InputRejected(f"{name}_fields_invalid")
    return value


def _status(value: Any, name: str) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise InputRejected(f"{name}_invalid")
    return value


def evaluate_gold(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compare supplied outcomes; exclude missing labels/results and synthetic rows."""
    _fields(manifest, {"schema_version", "dataset_id", "cases"}, "manifest")
    if manifest["schema_version"] != "reconciliation-gold-1":
        raise InputRejected("gold_schema_invalid")
    dataset_id = _text(manifest["dataset_id"], "dataset_id")
    if not isinstance(manifest["cases"], list):
        raise InputRejected("cases_invalid")
    seen: set[str] = set()
    rows = []
    exclusions: Counter[str] = Counter()
    numerator = denominator = synthetic_checks = 0
    for case in manifest["cases"]:
        _fields(case, {"case_id", "item", "synthetic", "observed_status", "gold"}, "case")
        case_id = _text(case["case_id"], "case_id")
        if case_id in seen:
            raise InputRejected("duplicate_case_id")
        seen.add(case_id)
        if not isinstance(case["item"], str) or case["item"] not in {"C1", "C2", "C3", "C4"}:
            raise InputRejected("item_invalid")
        if type(case["synthetic"]) is not bool:
            raise InputRejected("synthetic_invalid")
        observed = case["observed_status"]
        if observed is not None:
            _status(observed, "observed_status")
        gold = case["gold"]
        expected = None
        if gold is not None:
            _fields(gold, {"expected_status", "approved_by", "approved_at", "evidence"}, "gold")
            expected = _status(gold["expected_status"], "expected_status")
            _text(gold["approved_by"], "approved_by")
            stamp = _text(gold["approved_at"], "approved_at")
            try:
                approved_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise InputRejected("approved_at_invalid") from exc
            if "T" not in stamp or approved_at.utcoffset() is None:
                raise InputRejected("approved_at_timezone_required")
            evidence = _fields(gold["evidence"], {"reference", "sha256"}, "evidence")
            _text(evidence["reference"], "evidence_reference")
            digest = _text(evidence["sha256"], "evidence_sha256")
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise InputRejected("evidence_sha256_invalid")
        reasons = []
        if gold is None:
            reasons.append("missing_gold")
        if observed is None:
            reasons.append("missing_observed_status")
        if case["synthetic"]:
            reasons.append("synthetic_fixture")
        comparable = gold is not None and observed is not None
        correct = observed == expected if comparable else None
        if not reasons:
            denominator += 1
            numerator += int(correct is True)
        if comparable and case["synthetic"]:
            synthetic_checks += 1
        exclusions.update(reasons)
        rows.append(
            {
                "case_id": case_id,
                "item": case["item"],
                "status": "compared" if comparable else "not_run",
                "observed_status": observed,
                "expected_status": expected,
                "correct": correct,
                "included_in_semantic_denominator": not reasons,
                "exclusion_reasons": reasons,
                "gold": gold,
            }
        )
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return {
        "schema_version": "reconciliation-gold-report-1",
        "dataset_id": dataset_id,
        "manifest_sha256": digest,
        "total_rows": len(rows),
        "cases": rows,
        "semantic_accuracy": {
            "status": "scored" if denominator else "not_run",
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "denominator_definition": "non-synthetic rows with explicit gold and observed status",
        },
        "excluded_rows": len(rows) - denominator,
        "exclusion_counts": dict(sorted(exclusions.items())),
        "exclusion_counts_overlap": True,
        "synthetic_comparisons": synthetic_checks,
        "limitations": [
            "Synthetic comparisons test the harness, not semantic accuracy or Kia readiness.",
            "Approval identity and evidence authenticity require operator verification.",
            "Missing gold and outcomes are excluded; score is conditional on included rows.",
            "No policy approval or search-coverage receipt is created or inferred.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--manifest", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--expert-csv", type=Path)
    cli.add_argument("--case-id-column", default="case_id")
    cli.add_argument("--item-column", default="item")
    cli.add_argument("--expected-rows", type=int, default=8)
    args = cli.parse_args(argv)
    try:
        manifest = load_json(args.manifest)
        evaluate_gold(manifest)
        provenance = None
        if args.expert_csv:
            manifest, provenance = expert_csv_manifest(
                args.expert_csv,
                dataset_id=manifest["dataset_id"],
                case_id_column=args.case_id_column,
                item_column=args.item_column,
                approved_manifest=manifest,
                expected_rows=args.expected_rows,
            )
        report = evaluate_gold(manifest)
        if provenance is not None:
            report["expert_csv"] = provenance
        write_json(args.output, report)
    except (OSError, ValueError) as exc:
        print(f"gold_evaluation_rejected:{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
