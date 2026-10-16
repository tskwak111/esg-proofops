"""V13 promotes K11/H6 while preserving historical and bounded publication contracts."""

from argparse import Namespace

import pytest
from proofops.application import analysis_profile as profiles
from proofops.application.tagging.fact_assembly_c3 import PROFILE, REVIEWED_IDENTITY
from proofops.domain.provenance import canonical_hash


def test_v13_pin_is_exact_h6_contract_with_a_new_pin():
    selected = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I12_POLICY)
    )
    assert selected == profiles.FINALS_I12_POLICY
    assert selected == profiles.FINALS_H6_POLICY | dict(integration_profile="finals-20261013-v13")
    assert canonical_hash(selected) == (
        "488cb0b9339e4144ae9221845b21bfdd193d38a18cff60c24fb1c4cd6256090d"
    )
    assert selected["tagging_wire_policy"] == profiles.FINALS_K11_POLICY["tagging_wire_policy"]
    assert selected["general_certification"]["enabled"] is False
    assert selected["replicas"] == 3
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(selected))
        == selected
    )


@pytest.mark.parametrize(
    "policy,digest",
    [
        (
            profiles.FINALS_I11_POLICY,
            "0f7f5cd6f7b009d3e2d25bf049da7d91bc9675c595714555e365f16244f15559",
        ),
        (
            profiles.FINALS_K11_POLICY,
            "01ed39928d5a5c35671a78bd6eedb8e42b68a7ea40a1b0fccf4e444b32047c02",
        ),
        (
            profiles.FINALS_H6_POLICY,
            "6dbc7c31f75f28e61656f7e4db0e5479f70d83f9506b38e9e473c677ff6e7dd3",
        ),
    ],
)
def test_historical_pins_remain_exact_for_read_and_publication(policy, digest):
    assert canonical_hash(policy) == digest
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy


def test_v13_pilot_wires_h6_parser_and_reader_without_upgrading_resumes():
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        resume=False,
        analysis_policy_sha256=canonical_hash(profiles.FINALS_I12_POLICY),
    )
    profiles.apply_pilot_profile(args)
    assert args.analysis_policy_sha256 == canonical_hash(profiles.FINALS_I12_POLICY)
    assert args.parser_local_resource_policy == "selected-pdf-h6-v1"
    assert args.parser_failure_policy == "partial-v3"
    assert args.claim_source_profile == "upstage-ocr-page-v14"
    assert args.verify_claim_spans and args.verify_paragraphs and args.verify_merged_tables
    prior = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        resume=True,
        analysis_policy_sha256=canonical_hash(profiles.FINALS_I11_POLICY),
        claim_source_profile="upstage-ocr-page-v13",
    )
    before = vars(prior).copy()
    profiles.apply_pilot_profile(prior)
    assert vars(prior) == before


def test_v13_keeps_exact_lg_p36_identity_and_rejects_general_confirmation():
    assert profiles.certification_profile_for(REVIEWED_IDENTITY) == PROFILE
    for key in REVIEWED_IDENTITY:
        assert profiles.certification_profile_for(REVIEWED_IDENTITY | {key: "foreign"}) is None
    assert profiles.certification_profile_for({}) is None
    with pytest.raises(ValueError, match="ANALYSIS_PROFILE_PIN_MISMATCH"):
        profiles.policy_for(profiles.V2_PROFILE, pinned_hash="0" * 64)
