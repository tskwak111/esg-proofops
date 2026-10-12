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
# S5 is an execution contract. Historical F1 resilience and transport pins stay
# byte-equivalent; live settings are frozen separately for each new run.
SCHEDULER_POLICY = dict(
    profile="physical-attempt-role-queues-s5-v1",
    roles=["elements", "relation", "preliminary", "extract"],
    priority="tagging-critical-path-first-fifo-within-role",
    max_priority_bypass=8,
    concurrency="physical-attempt-only-shared-across-roles-and-retries",
    pacing="uniform-start-spacing-no-burst",
    default_workers=8,
    max_workers=16,
    default_rps=4,
    max_rps=8,
)
# New execution ceiling only; S5 remains byte-identical for historical replay.
SCHEDULER_C24_POLICY = SCHEDULER_POLICY | dict(
    profile="physical-attempt-role-queues-c24-v1", max_workers=24, max_rps=12
)
ISOLATED_CODES = frozenset({"PROVIDER_PROCESSING_FAILED", "PROVIDER_CIRCUIT_OPEN"})
RESPONSE_ERROR_DIAGNOSTIC_POLICY = dict(
    profile="openai-response-uncertainty-f1-v1",
    received_http="preserve-status-and-safe-headers",
    missing_response="null-status-and-body-hash",
    exception="type-only-no-message",
    cost="retain-uncertainty",
)
HTTP_DIAGNOSTIC_POLICY = dict(
    profile="openai-http-diagnostics-e05-v1",
    transport="unchanged-stdlib-fresh-http1-tls-verified",
    context="wire-sha256-utc-monotonic-role-replica-reservation-connection",
    timings="connect-tls-combined-ttfb-total;unmeasured-stages-null",
    headers="allowlist-bounded-no-secret-body-cookie",
    storage="private-immutable-document-owned-sidecar",
    cost="uncertain-reservation-retained;no-new-retry",
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
