"""Opt-in execution only; the v29b source and decision contracts are unchanged."""

POLICY = dict(
    profile="spg_publication_v1",
    evidence="same-process-full-replay-with-exact-input-digests",
    binding="tenant-run-source-checkpoints-parser-ocr-runtime-policy-hosted-fence",
    mismatch="full-source-replay",
    unresolved="retain-exact-negative-states-after-successful-full-replay-never-promote",
    storage="private-memory-only-bounded-64MiB",
    projection="batch-derived-search-writes-and-reuse-exact-graph-digest",
    coordinates="overlap-original-sha-bound-w19-inventory",
)


def enabled(policy):
    value = policy.get("spg_publication")
    if value is None:
        return False
    if value != POLICY:
        raise ValueError("SPG_PUBLICATION_POLICY_MISMATCH")
    return True
