"""V16 composes v15 admission/discovery with HX3 without rewriting either pin."""

from argparse import Namespace

import pytest
from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES, page_ocr_profile
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v16_default_is_v15_plus_exact_hx3_delta():
    selected = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I16_POLICY)
    )
    assert selected == profiles.FINALS_I16_POLICY
    assert selected == profiles.FINALS_I15_POLICY | dict(
        integration_profile="finals-20261014-v16",
        source="upstage-ocr-page-v16",
        result_outcome_projection="admitted-extraction-checkpoint-hx3-v1",
        failure_diagnostics="source-item-holds-and-code-locations-hx3-v1",
    )
    assert selected["source"] in PAGE_OCR_PROFILES
    reader = page_ocr_profile(selected["source"])
    assert reader.native_policy()["mode"] == selected["source"]
    assert selected["general_certification"]["enabled"] is False
    assert selected["replicas"] == 3
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        resume=False,
        analysis_policy_sha256=canonical_hash(selected),
    )
    profiles.apply_pilot_profile(args)
    assert args.analysis_policy_sha256 == canonical_hash(selected)
    assert args.claim_source_profile == selected["source"]
    assert args.extraction_qc_native_figures is True
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(selected))
        == selected
    )


@pytest.mark.parametrize(
    "policy,pin,reader,qc",
    [
        (
            profiles.FINALS_I15_POLICY,
            "6370602674ea415f510cc08171aff70dc7748379ad227dd187951e91523ba046",
            "upstage-ocr-page-v15",
            True,
        ),
        (
            profiles.FINALS_HX3_POLICY,
            "cdb1a5249deccb97ed2f30b03f77648ab150ffb70e63412f0a0bb86daa8a3bbf",
            "upstage-ocr-page-v16",
            False,
        ),
    ],
)
def test_both_premerge_pins_remain_readable_publishable_and_resumable(policy, pin, reader, qc):
    assert canonical_hash(policy) == pin
    assert canonical_hash(profiles.FINALS_I16_POLICY) != pin
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    args = Namespace(analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=pin)
    profiles.apply_pilot_profile(args)
    assert args.claim_source_profile == reader
    assert args.extraction_qc_native_figures is qc
    args.resume = True
    before = vars(args).copy()
    profiles.apply_pilot_profile(args)
    assert vars(args) == before
