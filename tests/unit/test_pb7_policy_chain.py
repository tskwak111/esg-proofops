"""PB7 merges PB6 without losing deployed PA4 or standalone policy replay."""

import pytest
from proofops.application.analysis_profile import (
    MODEL_RESPONSE_POLICY,
    V2_PB6_POLICY,
    V2_POLICY,
    V2_PRE_PB7_POLICY,
    policy_for,
)
from proofops.domain.provenance import canonical_hash


@pytest.mark.parametrize(
    "policy, expected",
    [
        (V2_PRE_PB7_POLICY, "639ba0a01ebde2856deef9d5811195417bb13e369d57d7568fe3c8399634b12d"),
        (V2_PB6_POLICY, "e483d3ac82014f2658c185b3091b23fe1011ef9923ec9d3bb8ad19f37aad74a7"),
    ],
)
def test_both_original_policies_replay_by_exact_hash(policy, expected):
    assert canonical_hash(policy) == expected
    assert policy_for("finals-unattended-v2", pinned_hash=expected) == policy


def test_integrated_default_adds_only_pb6_selection_policy():
    assert V2_POLICY == V2_PRE_PB7_POLICY | dict(citation_restore="citation-selected-value-pb6-v1")
    assert V2_POLICY["model_response_policy"] == MODEL_RESPONSE_POLICY
    assert policy_for("finals-unattended-v2") == V2_POLICY
