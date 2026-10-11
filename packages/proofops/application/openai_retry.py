"""Opt-in recovery contract; an empty or unclassified 403 is never transient."""

from proofops.domain.provenance import canonical_hash

POLICY = dict(
    profile="openai-structured-overload-403-once-t1-v1",
    status=403,
    error_code="server_is_overloaded",
    error_type="service_unavailable_error",
    require_provider_request_id=True,
    require_retry_after=True,
    max_retries=1,
    min_delay_seconds=5,
    max_delay_seconds=30,
    jitter_seconds=1,
    reservation="new-hosted-broker-call-id-original-uncertain-retained",
    recheck="price-owner-source-expiry-budget-after-delay",
    scope="one-complete-including-schema-attempts-no-crash-redelivery",
    empty_body="stop",
)
POLICY_HASH = canonical_hash(POLICY)
