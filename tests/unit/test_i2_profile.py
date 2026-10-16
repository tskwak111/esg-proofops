"""I2 composes admitted J3 boundaries without reinterpreting historical runs."""

from argparse import Namespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_i2_pin_excludes_j3_after_failed_precision_gate():
    digest = canonical_hash(profiles.FINALS_I2_POLICY)
    policy = profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest)
    assert policy["integration_profile"] == "finals-20261011-v2"
    assert "selected_span_refinement" not in policy
    delta = {k for k, v in policy.items() if v != profiles.FINALS_I1_POLICY.get(k)}
    assert delta == {"integration_profile"}
    args = Namespace(analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=digest)
    profiles.apply_pilot_profile(args)
    assert not args.extraction_j3 and args.extraction_w9
    assert args.extraction_sentence_prefix and args.extraction_table_footnotes
    assert args.analysis_policy_sha256 == canonical_hash(policy)
    with pytest.raises(ValueError, match="PUBLICATION_PIN_MISMATCH"):
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest)


def test_rejected_j3_candidate_preserves_exact_replay_but_cannot_publish():
    policy = profiles.FINALS_I2_J3_POLICY
    assert policy == profiles.FINALS_I1_POLICY | dict(
        integration_profile="finals-20261011-v2",
        selected_span_refinement="j3-explicit-boundaries-v1",
    )
    digest = canonical_hash(policy)
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
    args = Namespace(analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=digest)
    profiles.apply_pilot_profile(args)
    assert args.extraction_j3 and args.extraction_w9
    assert args.extraction_sentence_prefix and args.extraction_table_footnotes
    with pytest.raises(ValueError, match="PUBLICATION_PIN_MISMATCH"):
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest)


@pytest.mark.parametrize(
    "policy,j3,prefix,notes",
    [
        (profiles.FINALS_I1_POLICY, False, True, True),
        (profiles.V2_W9_POLICY, False, False, False),
        (profiles.W3_POLICY, False, False, False),
    ],
)
def test_historical_options_follow_their_pin(policy, j3, prefix, notes):
    digest = canonical_hash(policy)
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
    args = Namespace(analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=digest)
    profiles.apply_pilot_profile(args)
    assert args.extraction_j3 is j3
    assert args.extraction_sentence_prefix is prefix
    assert args.extraction_table_footnotes is notes


def test_j3_original_opt_in_hash_and_flags_remain_exact():
    original = profiles.V2_W9_POLICY | dict(
        profile=profiles.J3_PROFILE, selected_span_refinement="j3-explicit-boundaries-v1"
    )
    assert profiles.J3_POLICY == original
    args = Namespace(analysis_profile=profiles.J3_PROFILE)
    profiles.apply_pilot_profile(args)
    assert args.extraction_j3 and args.extraction_w9
    assert not args.extraction_sentence_prefix and not args.extraction_table_footnotes
    assert args.analysis_policy_sha256 == canonical_hash(original)


def test_old_i1_pin_is_readable_but_cannot_publish_a_new_run():
    digest = "df58e8330bb2dbb46cc6b3f3690ca6a44d0c31f2cdc20a4c387569ebd131f37c"
    assert canonical_hash(profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest)) == digest
    with pytest.raises(ValueError, match="PUBLICATION_PIN_MISMATCH"):
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest)


def test_rejected_j3_leaves_every_i1_execution_option_identical():
    before = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        analysis_policy_sha256=canonical_hash(profiles.FINALS_I1_POLICY),
    )
    after = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        analysis_policy_sha256=canonical_hash(profiles.FINALS_I2_POLICY),
    )
    profiles.apply_pilot_profile(before)
    profiles.apply_pilot_profile(after)
    old = vars(before).copy()
    new = vars(after).copy()
    old.pop("analysis_policy_sha256")
    new.pop("analysis_policy_sha256")
    assert old == new
