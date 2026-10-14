"""Immutable HX6 candidate routing contract; no source admission."""

POLICY = dict(
    profile="hx6-page-recovery-v1",
    native="original-byte-native-and-local-prose-readability; candidate-only",
    provider="one-physical-page-at-a-time; shared-ledger; maximum-two-attempts",
    retry="explicit-429-500-502-503-504-only; no-ambiguous-paid-resubmission",
    failure="only-unrecovered-pages-unreadable; existing-source-admission-required",
)
