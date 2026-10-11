"""Activate S1 for the exact I4 composite while preserving S1's pinned bytes."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import parse_table_cache
from proofops.domain.provenance import canonical_hash


@contextmanager
def for_snapshot(snapshot, tenant, run):
    from proofops.application.analysis_profile import (
        FINALS_I4_POLICY,
        FINALS_I6_POLICY,
        FINALS_K6_POLICY,
        S1_POLICY,
    )

    configured = next(
        (
            p
            for p in (FINALS_I4_POLICY, FINALS_K6_POLICY, FINALS_I6_POLICY)
            if snapshot.get("analysis_profile_policy_sha256") == canonical_hash(p)
        ),
        None,
    )
    if configured is not None:
        if (
            snapshot.get("analysis_profile_policy") != configured
            or configured["parse_replay_cache"] != S1_POLICY["parse_replay_cache"]
            or S1_POLICY["parse_replay_cache"]["implementation_sha256"]
            != sha256(Path(parse_table_cache.__file__).read_bytes()).hexdigest()
        ):
            raise ValueError("I4_PARSE_POLICY_MISMATCH")
        with parse_table_cache.scope(tenant, run):
            yield
    else:
        with parse_table_cache.for_snapshot(snapshot, tenant, run):
            yield
