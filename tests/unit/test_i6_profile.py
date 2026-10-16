from argparse import Namespace

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_i6_composes_i5_context_and_coverage_without_changing_old_pins():
    policy = profiles.FINALS_I6_POLICY
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy))
        == policy
    )
    assert policy["integration_profile"] == "finals-20261012-v6"
    for key in ("source", "verified_read_cache", "tagging_budget", "table_failure_profile"):
        assert policy[key] == profiles.FINALS_I5_POLICY[key]
    assert policy["sentence_context_policy"] == profiles.FINALS_K5_POLICY["sentence_context_policy"]
    for key in (
        "coverage_policy",
        "citation_restore",
        "risk_classification_policy",
        "facility_tagging_candidates",
    ):
        assert policy[key] == profiles.FINALS_K6_POLICY[key]
    for old, digest in (
        (
            profiles.FINALS_I5_POLICY,
            "04cef3a55bce657c7f75379948974120d1bf9c1459a730a474e33a6f64aca188",
        ),
        (
            profiles.FINALS_K5_POLICY,
            "2d952d6d8687f395101710be0a2a3fcb5aad9e3b41444f7548cfb961dd3d895e",
        ),
        (
            profiles.FINALS_K6_POLICY,
            "8fae18fee45ab7fccc4b9004b65fc7027e925c33c473de06649ac5fcacea0f5e",
        ),
    ):
        assert canonical_hash(old) == digest
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == old
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == old
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=canonical_hash(policy)
    )
    profiles.apply_pilot_profile(args)
    assert args.extraction_i4_identity and args.extraction_h1
    assert args.extraction_i5_tables and args.extraction_k6
    assert args.tagging_max_calls == 2000
    assert args.claim_source_profile == "upstage-ocr-page-v12"


def test_i6_enables_exact_s1_parse_receipt_scope_and_rejects_tampering():
    import pytest
    from proofops.adapters.local import i4_parse_scope, parse_table_cache

    policy = profiles.FINALS_I6_POLICY
    snapshot = dict(
        analysis_profile_policy=policy, analysis_profile_policy_sha256=canonical_hash(policy)
    )
    with i4_parse_scope.for_snapshot(snapshot, "tenant", "run"):
        assert parse_table_cache._scope.get()[:2] == ("tenant", "run")
    with pytest.raises(ValueError, match="I4_PARSE_POLICY_MISMATCH"):
        with i4_parse_scope.for_snapshot(
            snapshot | dict(analysis_profile_policy={}), "tenant", "run"
        ):
            pass
