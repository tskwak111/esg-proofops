"""Integrated defaults must compose every opt-in and retain exact old pins."""

from argparse import Namespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


@pytest.mark.parametrize(
    "digest",
    [
        "3acefc784aeff5e2c922ceb4cc9d8aed06e089f28eff1980524458e9baf7f1b8",
        "7cf6e2a0933b62f384333e7b3317f780a632a942bd565088f230617fcca0fb3d",
        "4d879787cbea984a35795bc644ab305b77cbbc7b1c03659f2801b9d8b4f69928",
        "f348b07e73e35c3d353666cc382ee7b8a756b7c3aa6838520ae6101dcad9bee4",
        "9f4bc1f593d6f930bdc3c0a8f4a224f20422e4863465c869e0f3084a49b5f00d",
    ],
)
def test_historical_pins_are_exact(digest):
    assert canonical_hash(profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest)) == digest


def test_default_composes_all_integrated_features():
    policy = profiles.policy_for(profiles.V2_PROFILE)
    assert policy["integration_profile"] == "finals-20261011-v1"
    assert policy["scope"] == "bounded-v2"
    assert policy["table_claims"] == "pb1-w9-v1"
    assert policy["extraction_sentence_prefix"] == "same-paragraph-sentence-prefix-w7-v1"
    assert policy["semantic_admission"] == profiles.W8_POLICY
    assert policy["element_definition_profile"] == "finals-i1-v1"
    assert policy["table_footnotes"] == "table-footnotes-dec24-v1"
    assert policy["execution_profile"] == "w3-speed-v1"
    assert policy["stage_overlap"] is False
    assert policy["citation_restore"] == "citation-selected-value-pb6-v1"
    args = Namespace(analysis_profile=profiles.V2_PROFILE)
    profiles.apply_pilot_profile(args)
    assert args.extraction_sentence_prefix
    assert args.extraction_w9 and args.extraction_table_footnotes
    assert args.analysis_policy_sha256 == canonical_hash(policy)


def test_explicit_w3_pin_keeps_its_original_extraction_options():
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        analysis_policy_sha256=canonical_hash(profiles.W3_POLICY),
    )
    profiles.apply_pilot_profile(args)
    assert not getattr(args, "extraction_w9", False)
    assert not getattr(args, "extraction_sentence_prefix", False)
    assert not getattr(args, "extraction_table_footnotes", False)
