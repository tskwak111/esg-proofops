from copy import deepcopy

import pytest
from proofops.application.analysis_profile import policy_for, publication_policy_for
from proofops.application.tagging.fact_assembly_c3 import PROFILE, assemble, replay

from tests.unit.test_c2_assembly import case, seal


def test_new_profile_preserves_c2_and_simulation_cannot_publish():
    inputs, votes = case()
    result = assemble(votes, **inputs).to_dict()
    assert result["candidate_auto_confirmed"]
    assert not result["public_auto_confirmed"]
    assert replay(result, **inputs).to_dict() == result
    assert policy_for(PROFILE) == publication_policy_for(PROFILE)
    with pytest.raises(ValueError, match="PUBLICATION_DISABLED"):
        publication_policy_for("management-direct-certification-c2-v1")


@pytest.mark.parametrize("change", ["activity", "partial_scope", "period", "conflict"])
def test_incorrect_source_attribution_is_blocked(change):
    inputs, votes = case()
    for vote in votes:
        raw = vote["raw"]
        if change == "activity":
            raw["dimensions"]["activity"]["quote"] = "ISO 14001"
        elif change == "partial_scope":
            raw["dimensions"]["boundary"]["quote"] = "전 사업장"
        elif change == "period":
            raw["period_kind"] = "explicit_current"
            raw["dimensions"]["period"]["quote"] = "2026"
        else:
            raw["elements"]["M3"]["state"] = "conflict"
    result = assemble([seal(v) for v in deepcopy(votes)], **inputs).to_dict()
    assert not result["candidate_auto_confirmed"]
    assert not result["public_auto_confirmed"]
    assert result["engine_decision"] is None
