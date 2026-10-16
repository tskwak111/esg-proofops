"""Opt-in lifetimes for verified receipt buffers; no proof or output changes."""

POLICY = dict(
    profile="rb4_receipt_lifetimes_v1",
    extraction="release-verified-prior-envelope-before-next-batch",
    loading="release-checked-serialized-inputs-before-source-replay",
    tagging="retain-pins-and-coverage-after-complete-source-replay",
    publication="compare-admitted-canonical-digest-before-decoding-another-copy",
    projection="release-verified-extraction-proof-after-outcome-admission",
    receipt_bytes="unchanged",
)

PUBLICATION_POLICY = dict(
    profile="rb4_publication_keys_v1",
    records="sort-keys-then-hash-one-complete-value-at-a-time",
    integrity="all-authoritative-rows-and-existing-cache-exclusions-unchanged",
)


def enabled(snapshot):
    policy = snapshot.get("analysis_profile_policy", {}).get("rb4_memory")
    if policy is None:
        return False
    if policy != POLICY:
        raise ValueError("RB4_MEMORY_POLICY_MISMATCH")
    return True


def publication_enabled(policy):
    value = policy.get("rb4_publication_digest")
    if value is None:
        return False
    if value != PUBLICATION_POLICY:
        raise ValueError("RB4_PUBLICATION_POLICY_MISMATCH")
    return True
