"""V12 promotes bounded K10/C4 while every historical policy remains replayable."""

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v12_pinned_policy_activates_reviewed_certification_and_k10_v2():
    from proofops.application.tagging.fact_assembly_c3 import POLICY, POLICY_HASH
    from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE

    selected = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I11_POLICY)
    )
    assert selected["integration_profile"] == "finals-20261013-v12"
    for key, value in profiles.FINALS_K10_V2_POLICY.items():
        if key != "integration_profile":
            assert selected[key] == value
    assert selected["direct_certification_policy"] == POLICY
    assert selected["direct_certification_policy_sha256"] == POLICY_HASH
    assert selected["general_certification"]["profile"] == C4_PROFILE
    assert selected["general_certification"]["enabled"] is False
    assert "G3" in selected["residual_review"]
    assert selected["replicas"] == 3
    assert selected["provider_resilience"]["consecutive_denials"] == 3
    for prior in (
        profiles.FINALS_I10_POLICY,
        profiles.FINALS_K10_POLICY,
        profiles.FINALS_K10_V2_POLICY,
    ):
        digest = canonical_hash(prior)
        assert digest != canonical_hash(selected)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == prior
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == prior


def test_v12_certification_is_limited_to_every_r8_reviewed_identity_pin():
    from proofops.application.tagging.fact_assembly_c3 import PROFILE, REVIEWED_IDENTITY

    assert profiles.certification_profile_for(REVIEWED_IDENTITY) == PROFILE
    for key in REVIEWED_IDENTITY:
        changed = REVIEWED_IDENTITY | {key: "foreign"}
        assert profiles.certification_profile_for(changed) is None
    for prior in (profiles.FINALS_I10_POLICY, profiles.FINALS_K10_V2_POLICY):
        assert (
            profiles.certification_profile_for(REVIEWED_IDENTITY, pinned_hash=canonical_hash(prior))
            is None
        )
