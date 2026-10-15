"""V23 composes F5 v3, FXA visibility, and D2 without rewriting old policies."""

from hashlib import sha256
from pathlib import Path

import pytest
from proofops.adapters.local import upstage_ocr_profile_d2_v21 as d2
from proofops.adapters.local.claim_source_policies import page_ocr_profile, publication_reader
from proofops.adapters.local.historical_prose_replay import historical_pre_d2_reader
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v23_default_composes_v22_and_d2_and_keeps_historical_pins():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I23_POLICY)
    )
    assert policy == profiles.FINALS_I23_POLICY
    assert policy["integration_profile"] == "finals-20261015-v23"
    assert policy["fact_assembly_profile"] == "grade-relevant-unanimity-v3"
    changed = {"integration_profile", "fact_assembly_profile"}
    assert {k: v for k, v in policy.items() if k not in changed} == {
        k: v for k, v in profiles.FINALS_I22_POLICY.items() if k not in changed
    }
    assert canonical_hash(profiles.FINALS_I22_POLICY) == (
        "2a2faa8835e3ed14633091797a30ac54a28681f44a7d096ced323b85f4d8417a"
    )
    assert canonical_hash(profiles.FINALS_FXC_POLICY) == (
        "53e6afe139576dbc514dc3964399c99287aca62dbdd611300196b491b1276210"
    )
    reader = page_ocr_profile(policy["source"])
    assert reader.previous is d2
    assert reader.native_policy() == d2.native_policy()
    assert reader.table_span_policy() == d2.table_span_policy()
    assert reader.table_policy_sha256() == d2.table_policy_sha256()
    assert publication_reader(reader.claim_source_policy()) is reader
    old = historical_pre_d2_reader()
    assert sha256(Path(old.__file__).read_bytes()).hexdigest() == (
        "e365f48e672edf2353185a5756a95ab98b5ddd0636496ce78b5a8114190218db"
    )
    assert page_ocr_profile(old.PROFILE, policy=old.claim_source_policy()) is not reader
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_MISMATCH"):
        publication_reader(old.claim_source_policy())
    assert canonical_hash(policy) != canonical_hash(profiles.FINALS_I22_POLICY)
