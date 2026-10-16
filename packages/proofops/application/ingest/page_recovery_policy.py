"""Immutable HX6 candidate routing contract; no source admission."""

POLICY = dict(
    profile="hx6-page-recovery-v1",
    native="original-byte-native-and-local-prose-readability; candidate-only",
    provider="one-physical-page-at-a-time; shared-ledger; maximum-two-attempts",
    retry="explicit-429-500-502-503-504-only; no-ambiguous-paid-resubmission",
    failure="only-unrecovered-pages-unreadable; existing-source-admission-required",
)

CLAIM_LAYOUT_POLICY = POLICY | dict(
    profile="hx6-claim-layout-p2-v2",
    claim_pages="provider-structure-first; readable-native-only-on-provider-failure",
    fallback="preserve-readable-local-claim-candidates-and-provider-failure-record",
)


S3_CLAIM_LAYOUT_POLICY = CLAIM_LAYOUT_POLICY | dict(
    profile="s3_hx6-claim-layout-v1",
    provider="single-page-requests; four-per-wave; shared-ledger; maximum-two-attempts",
    execution="serial-subset-and-grounding; context-propagated-transports; ordered-results",
    stop="drain-reserved-wave; no-new-wave-or-retry-after-terminal-stop",
)
