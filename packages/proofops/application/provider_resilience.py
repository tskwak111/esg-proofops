"""Versioned partial processing contract; no grading or evidence admission."""

POLICY = dict(
    profile="provider-partial-f1-v1",
    failure_scope="request-only",
    uncertain_cost="accounting_pending",
    consecutive_denials=3,
    requests_per_second=4,
    retry="t1-structured-403-once-only",
    circuit_scope="new-model-dispatches",
    publication="partial-with-failure-count",
)
ISOLATED_CODES = frozenset({"PROVIDER_PROCESSING_FAILED", "PROVIDER_CIRCUIT_OPEN"})
RESPONSE_ERROR_DIAGNOSTIC_POLICY = dict(
    profile="openai-response-uncertainty-f1-v1",
    received_http="preserve-status-and-safe-headers",
    missing_response="null-status-and-body-hash",
    exception="type-only-no-message",
    cost="retain-uncertainty",
)

INITIAL_PROJECTION_POLICY = dict(
    profile="provider-failure-projection-f1-v1",
    source="immutable-tag-usage-and-stable-reason",
    failed_call="affected-claim-hold",
    successful_votes="retain-verified-provisional-facts",
    historical_reports="immutable",
)
PROJECTION_POLICY = INITIAL_PROJECTION_POLICY | dict(
    profile="provider-failure-projection-f1-v2", confirmed_grade="null-for-affected-claim"
)


def claim_hold_reason(projection):
    """Read trusted transport outcomes, never search model/source text for codes."""
    codes = {
        (run.get("usage") or {}).get("error_code")
        for run in projection.get("tag_runs") or []
        if (run.get("usage") or {}).get("status") == "failed"
    }
    for field in ("preliminary_records", "relation_records"):
        codes.update(
            (record.get("stable_reason") or {}).get("error_code")
            for record in projection.get(field) or []
            if record.get("status") == "needs_review"
        )
    return next((code for code in sorted(ISOLATED_CODES, reverse=True) if code in codes), None)
