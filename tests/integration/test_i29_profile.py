"""I29 composes the authorized policies while preserving historical pins."""

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v29_composition_and_historical_publication():
    current = profiles.policy_for(profiles.V2_PROFILE)
    expected = profiles.FINALS_I28_POLICY | {
        "integration_profile": "finals-20261016-v29",
        "source": profiles.CF4_SOURCE_POLICY["source"],
        "cf2_c3_response_binding": profiles.CF2_C3_POLICY["cf2_c3_response_binding"],
        "cf1_inventory": profiles.CF1_POLICY["cf1_inventory"],
        "cf6_confirmation": profiles.CF6_POLICY["cf6_confirmation"],
        **{
            key: value
            for key, value in profiles.CF5_POLICY.items()
            if key.startswith(("tagging_prompt_", "cf5_context_"))
        },
    }
    assert current == expected
    assert canonical_hash(profiles.FINALS_I28_POLICY) == (
        "31808287164e43e17495bccb17e31e7c53c7746ff0f7c9148276958f7d28cab2"
    )
    for selected in (current, profiles.FINALS_I28_POLICY, profiles.FINALS_I27_POLICY):
        pin = canonical_hash(selected)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected


def test_v29_hosted_and_v28_replay_pin(tmp_path):
    from tests.integration.test_i28_profile import test_hosted_child_preserves_integrated_pins

    for selected in (profiles.policy_for(profiles.V2_PROFILE), profiles.FINALS_I28_POLICY):
        test_hosted_child_preserves_integrated_pins(tmp_path, selected)
