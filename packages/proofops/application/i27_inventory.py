"""Optional SC1 acquisition recovery; no authority to approve missing evidence."""

POLICY = dict(
    profile="i27_sc1_optional_transient_v1",
    retry_statuses=list(range(500, 600)),
    max_retries=1,
    backoff_base_seconds=1,
    backoff_multiplier=2,
    timeout="degrade-without-retry",
    exhausted="chunk-uninspected; scope-confirmation-unavailable",
    accounting="each-attempt-brokered; uncertain-reservations-retained",
    other_failures="existing-rules",
)
