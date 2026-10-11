"""I3 combines selection, source and tagging policies while preserving old pins."""

from argparse import Namespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_i3_default_enables_all_admitted_options_and_v11_source():
    digest = canonical_hash(profiles.FINALS_I3_POLICY)
    policy = profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest)
    assert policy["integration_profile"] == "finals-20261011-v3"
    args = Namespace(analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=digest)
    profiles.apply_pilot_profile(args)
    for option in ("j3", "j7", "j8", "k1", "k3", "sentence_prefix", "table_footnotes"):
        assert getattr(args, "extraction_" + option) is True
    assert args.claim_source_profile == "upstage-ocr-page-v11"
    assert policy["hold_recovery_policy"] == profiles.FINALS_K2_POLICY["hold_recovery_policy"]
    assert policy["semantic_admission"] == profiles.K1_POLICY["semantic_admission"]
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
    assert not args.extraction_h1 and args.parser_local_resource_policy is None


def test_h1_future_policy_is_distinct_and_enables_bounded_parser_and_source_reader():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_H1_POLICY)
    )
    assert policy == profiles.FINALS_H1_POLICY
    assert canonical_hash(policy) != canonical_hash(profiles.FINALS_I3_POLICY)
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=canonical_hash(policy)
    )
    profiles.apply_pilot_profile(args)
    assert args.extraction_h1
    assert args.parser_local_resource_policy == "selected-pdf-h1-v1"
    assert args.claim_source_profile == "upstage-ocr-page-v12"


@pytest.mark.parametrize(
    "digest",
    [
        "df58e8330bb2dbb46cc6b3f3690ca6a44d0c31f2cdc20a4c387569ebd131f37c",
        "1a02f8e5e4ecb468e3cabb718de2c572f6f781cb9625f5d4e3d3f6b3cc62c7cf",
    ],
)
def test_historical_i1_i2_pins_remain_replayable(digest):
    policy = profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest)
    assert canonical_hash(policy) == digest
    args = Namespace(analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=digest)
    profiles.apply_pilot_profile(args)
    assert not args.extraction_j3 and not args.extraction_j8 and not args.extraction_k3
    assert args.claim_source_profile == "upstage-ocr-page-v10"
