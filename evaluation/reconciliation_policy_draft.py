"""Create an unapproved 1.1 policy; never record an approval or infer numeric rules.

Run with --source config/accounting/reconciliation_rules.yaml --version <id>
--coverage-policy-id <id> --output <new-file>. The source hash pins exact bytes;
the source is evidence, not executable configuration or approval authority.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

from proofops.application.reconciliation.schema import validate_schema

from evaluation.reconciliation_cli import InputRejected, write_json


def build_policy_draft(
    source_path: Path, *, version: str, coverage_policy_id: str
) -> dict[str, Any]:
    """Return conservative REC rules with all approval-dependent values unresolved."""
    if not isinstance(version, str) or not version.strip():
        raise InputRejected("version_required")
    if not isinstance(coverage_policy_id, str) or not coverage_policy_id.strip():
        raise InputRejected("coverage_policy_id_required")
    source = source_path.read_bytes()
    if not source.strip():
        raise InputRejected("source_policy_empty")
    draft = {
        "schema_version": "1.1",
        "version": version,
        "approved": False,
        "synthetic_only": False,
        "current_stage": 1,
        "enabled_items": ["C1", "C2", "C3", "C4"],
        "c1_identity_rule": "exact_verified_entity_set",
        "c3_threshold": None,
        "c3_account_mapping_approved": False,
        "approved_by": None,
        "approved_on": None,
        "source_policy_sha256": hashlib.sha256(source).hexdigest(),
        "allowed_capex_account_ids": [],
        "coverage_policy_id": coverage_policy_id,
        "allowed_difference_types": [
            "operational_control_vs_control",
            "overseas_subsidiary_excluded",
            "equity_method_excluded",
            "acquisition_disposal_proration",
        ],
        "c2_timing_rule": "same_period_or_verified_explanation",
        "c4_required_explanations": ["definition", "calculation_basis"],
    }
    validate_schema("policy", draft)
    return draft


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", type=Path, required=True)
    cli.add_argument("--version", required=True)
    cli.add_argument("--coverage-policy-id", required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args(argv)
    try:
        draft = build_policy_draft(
            args.source, version=args.version, coverage_policy_id=args.coverage_policy_id
        )
        write_json(args.output, draft)
    except (OSError, ValueError) as exc:
        print(f"policy_draft_rejected:{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
