import pytest
from proofops.adapters.local import i4_parse_scope, parse_table_cache
from proofops.application.analysis_profile import FINALS_I3_POLICY, FINALS_I4_POLICY
from proofops.domain.provenance import canonical_hash


def test_composite_i4_activates_original_s1_scope_and_i3_does_not():
    for policy, active in ((FINALS_I4_POLICY, True), (FINALS_I3_POLICY, False)):
        snapshot = dict(
            analysis_profile_policy=policy, analysis_profile_policy_sha256=canonical_hash(policy)
        )
        with i4_parse_scope.for_snapshot(snapshot, "tenant", "run"):
            bound = parse_table_cache._scope.get()
            assert bool(bound) is active
            if active:
                assert bound[:2] == ("tenant", "run")
        assert parse_table_cache._scope.get() is None


def test_composite_scope_rejects_policy_tampering():
    snapshot = dict(
        analysis_profile_policy=FINALS_I4_POLICY | dict(parse_replay_cache={}),
        analysis_profile_policy_sha256=canonical_hash(FINALS_I4_POLICY),
    )
    with pytest.raises(ValueError, match="I4_PARSE_POLICY_MISMATCH"):
        with i4_parse_scope.for_snapshot(snapshot, "tenant", "run"):
            pass
