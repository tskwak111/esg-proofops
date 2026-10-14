from copy import deepcopy

import pytest
from proofops.application.analysis_profile import policy_for, publication_policy_for
from proofops.application.tagging import fact_assembly_c3_v2 as c3_v2
from proofops.application.tagging.fact_assembly_c3 import (
    POLICY as C3_V1_POLICY,
)
from proofops.application.tagging.fact_assembly_c3 import (
    POLICY_HASH as C3_V1_HASH,
)
from proofops.application.tagging.fact_assembly_c3 import (
    PROFILE as C3_V1_PROFILE,
)
from proofops.application.tagging.fact_assembly_c3 import assemble as c3_assemble
from proofops.application.tagging.fact_assembly_c3_v2 import (
    REVIEWED_SOURCE_FINGERPRINT_SHA256,
    REVIEWED_SOURCE_IDENTITY,
    source_fingerprint_payload,
)
from proofops.domain.provenance import canonical_hash

from tests.unit.test_c2_assembly import case


def test_analysis_policy_dispatch_adds_c3_v2_without_repinning_c3_v1():
    assert policy_for(c3_v2.PROFILE, pinned_hash=c3_v2.POLICY_HASH) == c3_v2.POLICY
    assert publication_policy_for(c3_v2.PROFILE, pinned_hash=c3_v2.POLICY_HASH) == c3_v2.POLICY
    assert policy_for(C3_V1_PROFILE, pinned_hash=C3_V1_HASH) == C3_V1_POLICY
    assert publication_policy_for(C3_V1_PROFILE, pinned_hash=C3_V1_HASH) == C3_V1_POLICY
    assert (
        c3_v2.legacy.POLICY_HASH
        == "2291a8e0cc28a6128d467297cde38008ce0ae3a93345026bfedfa1d4986e4bf1"
    )
    assert policy_for(c3_v2.PROFILE, pinned_hash=c3_v2.legacy.POLICY_HASH) == c3_v2.legacy.POLICY
    assert (
        publication_policy_for(c3_v2.PROFILE, pinned_hash=c3_v2.legacy.POLICY_HASH)
        == c3_v2.legacy.POLICY
    )
    assert c3_v2.POLICY_HASH != c3_v2.legacy.POLICY_HASH
    with pytest.raises(ValueError, match="C3_V2_PUBLICATION_PROFILE_MISMATCH"):
        policy_for(c3_v2.PROFILE, pinned_hash=C3_V1_HASH)


def test_source_fingerprint_is_the_reviewed_lg_statement_and_element_evidence():
    assembly = {
        "identity": {
            "tenant_id": REVIEWED_SOURCE_IDENTITY["tenant_id"],
            "original_sha256": REVIEWED_SOURCE_IDENTITY["original_sha256"],
            "rulepack_sha256": REVIEWED_SOURCE_IDENTITY["rulepack_sha256"],
        },
        "statement_boundary": [
            {
                "page_num": 36,
                "char_start": 169,
                "char_end": 376,
                "bbox": [38.438, 469.9369999999999, 803.816, 543.8219999999999],
                "quote": REVIEWED_SOURCE_IDENTITY["normalized_exact_claim"],
                "verification_state": "verified",
            }
        ],
        "derived_results": [
            {
                "result": {
                    "elements": {
                        element_id: {
                            "state": "present",
                            "binding": "accepted",
                            "source_refs": [
                                {
                                    **span,
                                    "quote": span["normalized_exact_span"],
                                    "verification_state": "verified",
                                }
                                for span in spans
                            ],
                        }
                        for element_id, spans in REVIEWED_SOURCE_IDENTITY[
                            "element_evidence_refs"
                        ].items()
                    }
                }
            }
            for _ in range(3)
        ],
    }
    assert (
        canonical_hash(source_fingerprint_payload(assembly)) == REVIEWED_SOURCE_FINGERPRINT_SHA256
    )


@pytest.mark.parametrize(
    "change", ["tenant", "source", "statement", "element_evidence", "rulepack"]
)
def test_source_fingerprint_rejects_changed_scope_text_or_evidence(change):
    payload = deepcopy(REVIEWED_SOURCE_IDENTITY)
    if change == "tenant":
        payload["tenant_id"] = "00000000-0000-4000-8000-000000000000"
    elif change == "source":
        payload["original_sha256"] = "0" * 64
    elif change == "statement":
        payload["statement_spans"][0]["char_end"] += 1
    elif change == "element_evidence":
        payload["element_evidence_refs"]["M4"][0]["normalized_exact_span"] += " 변경"
    else:
        payload["rulepack_sha256"] = "1" * 64
    assert canonical_hash(payload) != REVIEWED_SOURCE_FINGERPRINT_SHA256


def test_saved_reply_simulation_recomputes_current_tags_but_cannot_publicly_confirm(monkeypatch):
    inputs, votes = case()
    previous = c3_assemble(votes, **inputs).to_dict()
    fingerprint = source_fingerprint_payload(previous)
    fingerprint_hash = canonical_hash(fingerprint)
    monkeypatch.setattr(c3_v2, "REVIEWED_SOURCE_FINGERPRINT_SHA256", fingerprint_hash)
    monkeypatch.setattr(c3_v2, "REVIEWED_SOURCE_IDENTITY", fingerprint)

    receipt = c3_v2.assemble(votes, **inputs).to_dict()

    assert receipt["source_fingerprint"] == fingerprint
    assert receipt["source_fingerprint_sha256"] == fingerprint_hash
    assert receipt["candidate_auto_confirmed"]
    assert not receipt["public_auto_confirmed"]
    assert receipt["engine_decision"]["evidence_grade"] == "E3"
    assert receipt["simulated"] is True
    assert c3_v2.replay(receipt, **inputs).to_dict() == receipt

    altered = deepcopy(votes)
    altered[0]["raw"]["elements"]["M4"]["evidence"]["quote"] = "변경된 근거"
    from tests.unit.test_c2_assembly import seal

    changed = c3_v2.assemble([seal(v) for v in altered], **inputs).to_dict()
    assert not changed["candidate_auto_confirmed"]
    assert not changed["public_auto_confirmed"]
    assert "SOURCE_FINGERPRINT_NOT_APPROVED" in changed["unresolved"]
