"""Opt-in fresh-run execution repair; no rule or evidence-admission changes."""

POLICY = dict(
    profile="fxh_fresh_execution_v1",
    max_request_bytes=32768,
    input_reservation="existing-32768-token-capacity; unchanged-money-and-dispatch-fences",
    inventory_chunk_bytes=2000,
    inventory_chunk_spans=8,
    inventory_output_tokens=4096,
    inventory_unlocated="uninspected-page; retain-block-error; never-absence",
    inventory_invalid_response="settled-invalid-chunk-only; authorization-budget-lease-stop",
    source_execution="registered-i24-private-reader-policy-snapshots-and-scoped-raw-OCR",
    c3_execution="retain-hosted-OCR-context; original-to-selected-page-admission-map",
)


def enabled(policy):
    value = policy.get("fxh_runtime")
    if value is not None and value != POLICY:
        raise ValueError("FXH_EXECUTION_POLICY_MISMATCH")
    return value == POLICY
