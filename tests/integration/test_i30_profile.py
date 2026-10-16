"""I30 composes execution policies without changing historical replay pins."""

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash

V29B_HASH = "9fd37ccb4d397e2b3b4c0a468502cca4aed18dbb5d9a0853a72e0d7cae33153d"


def test_v29c_composition_and_v29b_replay():
    current = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I30_POLICY)
    )
    assert current == profiles.FINALS_I29B_POLICY | dict(
        integration_profile="finals-20261017-v29c",
        spt_claim_pipeline=profiles.SPT_POLICY["spt_claim_pipeline"],
        source=profiles.SPE_POLICY["source"],
        parser_execution_policy=profiles.SPP_POLICY["parser_execution_policy"],
        spg_publication=profiles.SPG_POLICY["spg_publication"],
    )
    assert canonical_hash(profiles.FINALS_I29B_POLICY) == V29B_HASH
    for selected in (
        current,
        profiles.FINALS_I29B_POLICY,
        profiles.FINALS_I29_POLICY,
        profiles.SPT_POLICY,
        profiles.SPE_POLICY,
        profiles.SPP_POLICY,
        profiles.SPG_POLICY,
    ):
        pin = canonical_hash(selected)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == selected


@pytest.mark.parametrize("name", ["V2_POLICY", "FINALS_I29B_POLICY"])
def test_hosted_composite_and_historical_projection(tmp_path, monkeypatch, name):
    from tests.integration.test_i28_profile import test_hosted_child_preserves_integrated_pins
    from tests.unit.test_s2_result_annotations import (
        test_result_keeps_occurrence_metadata_with_legacy_facade,
    )

    selected = getattr(profiles, name)
    test_hosted_child_preserves_integrated_pins(tmp_path, selected)
    test_result_keeps_occurrence_metadata_with_legacy_facade(tmp_path, monkeypatch, selected)
