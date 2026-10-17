"""I31 activates TB1/UX1 while preserving v29c execution and historic replay."""

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_ux1 import UX1_POLICY_SHA256, enabled_for

V29C_HASH = "ff6b228be7cc5f88bc4009a45358bbfe72283d9c9b86958aad646c60c7f69b74"


def test_v29d_composition_and_preserved_pins():
    assert canonical_hash(profiles.FINALS_I30_POLICY) == V29C_HASH
    assert profiles.policy_for(profiles.V2_PROFILE) == profiles.FINALS_I30_POLICY | dict(
        integration_profile="finals-20261017-v29d",
        source="i31_claim_source_v1",
        tb1_table_policy=profiles.TB1_POLICY["tb1_table_policy"],
        tb1_table_policy_sha256=profiles.TB1_POLICY["tb1_table_policy_sha256"],
        ux1_data_policy_sha256=UX1_POLICY_SHA256,
    )
    for policy in (
        profiles.FINALS_I29_POLICY,
        profiles.FINALS_I29B_POLICY,
        profiles.FINALS_I30_POLICY,
        profiles.TB1_POLICY,
        profiles.FINALS_I31_POLICY,
    ):
        pin = canonical_hash(policy)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) is policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) is policy
        assert enabled_for(
            dict(analysis_profile=profiles.V2_PROFILE, analysis_profile_sha256=pin)
        ) is (policy is profiles.FINALS_I31_POLICY)
    assert not enabled_for({})
    assert not enabled_for(
        dict(analysis_profile=profiles.V2_PROFILE, analysis_profile_sha256="0" * 64)
    )


@pytest.mark.parametrize("name", ["FINALS_I30_POLICY", "FINALS_I31_POLICY"])
def test_hosted_child_retains_both_pins(tmp_path, name):
    from tests.integration.test_i28_profile import test_hosted_child_preserves_integrated_pins

    test_hosted_child_preserves_integrated_pins(tmp_path, getattr(profiles, name))


def test_v29d_create_resume_and_tamper(tmp_path, monkeypatch):
    from tests.integration import test_qt1_pipeline

    monkeypatch.setattr(test_qt1_pipeline, "QT1_POLICY", profiles.FINALS_I31_POLICY)
    test_qt1_pipeline.test_new_profile_create_resume_and_tamper_guard(tmp_path, monkeypatch)
