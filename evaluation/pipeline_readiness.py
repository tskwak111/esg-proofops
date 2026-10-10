"""Offline stage 4/5 diagnostics; never invokes providers or grants approvals.

Run: python -m evaluation.pipeline_readiness --comparison PATH --provider openrouter
Exit 0 means diagnostics completed, NOT pipeline readiness; --strict exits 1
while any downstream prerequisite remains blocked. Invalid input exits 2.
Only credential presence is inspected in the process environment; no .env is read.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MODELS = {"openrouter": ("openai/gpt-6-luna",), "upstage": ("solar-pro3", "solar-pro4")}
KEYS = {"openrouter": "OPENROUTER_API_KEY", "upstage": "UPSTAGE_API_KEY"}
ROOT = Path(__file__).resolve().parents[1]
COST_FIELDS = (
    "cost_with_vat_reserve_usd",
    "committed_or_reserved_usd",
    "unknown_reservation_cost_usd",
)
COUNT_FIELDS = (
    "model_calls",
    "reserved_calls",
    "settled_calls",
    "unsettled_calls",
    "input_tokens",
    "output_tokens",
    "extractor_calls",
    "calls",
    "settled",
    "unsettled",
)


def count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def money(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return str(amount) if amount.is_finite() and amount >= 0 else None


def usage_summary(usage: dict) -> dict:
    """Reservations are not actual spend; absent/unknown amounts remain null."""
    return {
        **{key: count(usage.get(key)) for key in COUNT_FIELDS},
        **{key: money(usage.get(key)) for key in COST_FIELDS},
        "actual_cost_usd": money(usage.get("actual_cost_usd")),
        "token_usage_complete": usage.get("token_usage_complete") is True,
    }


def provider_readiness(provider: str, model: str | None, environ: dict) -> dict:
    key = environ.get(KEYS[provider], "")
    present = isinstance(key, str) and bool(key)
    valid = present and not any(char.isspace() for char in key)
    supported = model is None or model in MODELS[provider]
    reasons = []
    if not valid:
        reasons.append("credential_missing_or_invalid")
    if not supported:
        reasons.append("unsupported_model")
    return {
        "provider": provider,
        "credential_present": present,
        "model_supported": supported,
        "configuration_status": "configuration_error" if reasons else "configured_unprobed",
        "reason_codes": reasons,
        "transport_status": "not_probed",
        "ready_for_live_call": False,
        "remaining_checks": ["transport", "budget_authorization", "model_binding_approval"],
    }


def extraction_status(raw: Any, accepted: Any = None) -> str:
    status = raw.lower() if isinstance(raw, str) else ""
    if any(code in status for code in ("api_key", "unsupported_model", "config", "policy")):
        return "configuration_error"
    if any(code in status for code in ("request_failed", "http_", "unavailable", "timeout")):
        return "transport_error"
    if "failed" in status or "invalid" in status:
        return "extraction_error"
    if status in ("succeeded", "completed", "success"):
        n = count(accepted)
        return "no_claims" if n == 0 else "claims_extracted" if n else "completed_count_unknown"
    return "not_run" if status == "not_run" else "unknown"


def policy_readiness(policy: dict | None) -> dict:
    # Self-asserted approval, including synthetic examples, cannot establish trust.
    reason = "trusted_policy_registry_not_verified"
    if policy is None:
        reason = "policy_missing"
    elif policy.get("approved") is not True:
        reason = "policy_unapproved"
    return {
        "status": "blocked",
        "reason": reason,
        "declared_approved": policy.get("approved") is True if policy else False,
        "synthetic_only": policy.get("synthetic_only") is True if policy else None,
        "domain_approval_verified": False,
        "c3_threshold_present": policy.get("c3_threshold") is not None if policy else False,
        "c3_account_mapping_declared": (
            policy.get("c3_account_mapping_approved") is True if policy else False
        ),
    }


def dependency_readiness(environ: dict, checked_at: datetime, azure_report: dict | None) -> dict:
    """Read pinned Solar expiry literals without importing any provider or parsing adapter."""
    policy_path = ROOT / "packages/proofops/application/input_reservation.py"
    expiries = []
    try:
        tree = ast.parse(policy_path.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in ("_EXPIRES_AT", "_REFRESHED_EXPIRES_AT")
                and node.value is not None
            ):
                expiry = ast.literal_eval(node.value)
                instant = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                expiries.append(
                    {
                        "revision": "refreshed" if "REFRESHED" in node.target.id else "legacy",
                        "expires_at": instant.isoformat(),
                        "status": "expired" if checked_at >= instant else "unexpired",
                    }
                )
    except (OSError, ValueError, TypeError, SyntaxError):
        expiries = []
    azure_keys = ("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_KEY")
    missing = [name for name in azure_keys if not environ.get(name, "").strip()]
    recorded_reason = (azure_report or {}).get("reason")
    return {
        "checked_at": checked_at.isoformat(),
        "azure": {
            "configuration_status": "configuration_error" if missing else "configured_unprobed",
            "missing_variables": missing,
            "transport_status": "not_probed",
            "recorded_pilot_reason": "AZURE_CREDENTIALS_REQUIRED"
            if recorded_reason == "AZURE_CREDENTIALS_REQUIRED"
            else None,
            "recorded_pilot_parsing": (azure_report or {}).get("parsing")
            if (azure_report or {}).get("parsing") in ("blocked", "not_run", "succeeded")
            else "unknown",
        },
        "solar_capacity_policy": {
            "revisions": expiries,
            "status": "expired"
            if len(expiries) == 2 and all(row["status"] == "expired" for row in expiries)
            else "not_verified",
            "source": policy_path.relative_to(ROOT).as_posix(),
            "approval_granted": False,
        },
    }


def build_report(
    comparison: dict,
    *,
    provider: str,
    model: str | None = None,
    environ: dict | None = None,
    policy: dict | None = None,
    checked_at: datetime | None = None,
    azure_report: dict | None = None,
) -> dict:
    original = comparison.get("original_pipeline", {})
    component = comparison.get("component_check", {})
    benchmark = comparison.get("benchmark", {})
    rows = comparison.get("rows", [])
    ledger = comparison.get("ledger", [])
    if (
        not all(isinstance(item, dict) for item in (original, component, benchmark))
        or not isinstance(rows, list)
        or not all(isinstance(row, dict) for row in rows)
        or not isinstance(ledger, list)
        or not all(isinstance(row, dict) for row in ledger)
    ):
        raise ValueError("invalid comparison structure")
    for key in ("paid_usage", "effective_graph_replay_usage"):
        if not isinstance(component.get(key, {}), dict):
            raise ValueError("invalid usage structure")
    statuses = Counter(
        row.get("system_status")
        for row in rows
        if row.get("system_status") in ("excluded_before_extractor", "candidate_only_unverified")
    )
    attempted = count(component.get("same_original_input_packets"))
    processed, rejected = count(component.get("processed")), count(component.get("rejected"))
    balanced = (
        attempted == processed + rejected
        if attempted is not None and processed is not None and rejected is not None
        else None
    )
    stages = {
        "4_extraction": {
            "service_status": extraction_status(
                original.get("extract"), original.get("accepted_claims")
            ),
            "service_claims": count(original.get("accepted_claims")),
            "component_only": {
                "attempted_packets": attempted,
                "processed_packets": processed,
                "rejected_packets": rejected,
                "packet_accounting_balanced": balanced,
                "accepted_claim_candidates": count(component.get("accepted_claim_candidates")),
                "end_to_end_evidence": False,
                "paid_usage": usage_summary(component.get("paid_usage", {})),
                "replay_usage": usage_summary(component.get("effective_graph_replay_usage", {})),
            },
        },
        "5_reconciliation": {
            "service_status": (
                original.get("reconciliation")
                if original.get("reconciliation") in ("not_run", "failed")
                else "unknown"
            ),
            "ready": False,
            "tagging_status": (
                original.get("tagging")
                if original.get("tagging") in ("not_run", "failed")
                else "unknown"
            ),
            "producer_gaps": [
                {"item": "C3", "fact": "currency_amount", "status": "missing_producer"},
                {"item": "C4", "fact": "revenue_share", "status": "missing_producer"},
            ],
            "producer_scope": "main sustainability claim tagging to linkage exchange",
            "producer_evidence": "packages/proofops/application/linkage_exchange.py",
            "policy": policy_readiness(policy),
            "financial_packet": "not_verified",
            "final_grade": None,
        },
    }
    return {
        "schema": "downstream-pipeline-readiness-1",
        "offline": True,
        "network_calls": 0,
        "pipeline_ready": False,
        "dependencies": dependency_readiness(
            dict(os.environ) if environ is None else environ,
            checked_at or datetime.now(UTC),
            azure_report,
        ),
        "provider": provider_readiness(
            provider, model, dict(os.environ) if environ is None else environ
        ),
        "stages": stages,
        "benchmark": {
            "selected_reference_cases": count(benchmark.get("selected_reference_cases")),
            "rows_observed": len(rows),
            "row_status_counts": dict(statuses),
            "excluded_before_extraction": count(
                benchmark.get("excluded_before_extraction_due_to_unlocated_source")
            ),
            "semantic_accuracy": None,
            "whole_report_recall": None,
            "expert_gold_verified": False,
        },
        "ledger": [
            {
                "provider": entry.get("provider") if entry.get("provider") in MODELS else "unknown",
                **usage_summary(entry),
            }
            for entry in ledger
        ],
        "limits": [
            "Component candidates do not establish service completion or semantic accuracy.",
            "Producer gaps are the audited code baseline, not inferred from empty claims.",
            "No policy registry, financial packet, or domain approval is verified here.",
            "Unknown costs are null; committed or reserved amounts are not actual spend.",
        ],
    }


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--provider", choices=MODELS, required=True)
    parser.add_argument("--model")
    parser.add_argument(
        "--azure-report", type=Path, help="Optional existing offline Azure pilot report"
    )
    parser.add_argument("--policy", type=Path, help="Optional JSON policy; never grants approval")
    parser.add_argument("--output", type=Path, help="New JSON file; refuses overwrite")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            read_object(args.comparison),
            provider=args.provider,
            model=args.model,
            policy=read_object(args.policy) if args.policy else None,
            azure_report=read_object(args.azure_report) if args.azure_report else None,
        )
        rendered = json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        print(rendered, end="")
    except (OSError, ValueError, TypeError):
        # Input/transport messages can contain secrets: emit only a stable code.
        print('{"error": "INVALID_INPUT_OR_OUTPUT"}')
        return 2
    return 1 if args.strict and not report["pipeline_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
