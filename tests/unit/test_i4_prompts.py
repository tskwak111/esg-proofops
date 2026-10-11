import json

import pytest
from proofops.application.analysis_profile import FINALS_I3_POLICY, FINALS_I4_POLICY, policy_for
from proofops.application.tagging.finals_i4 import (
    K4_ELEMENTS,
    K4_PRELIMINARY,
    PROFILE,
    elements_k4,
    preliminary_k4,
)
from proofops.domain.provenance import canonical_hash

from evaluation.local_upstage_pilot import live_tagging_settings


def test_i4_settings_and_historical_policy_are_pinned():
    settings = live_tagging_settings(
        600,
        preliminary_pb1=True,
        compact_element_wire=True,
        element_definition_profile="k1-v1",
        prompt_profile=PROFILE,
    )
    assert settings["preliminary_settings"]["system_prompt"] == K4_PRELIMINARY
    assert settings["tagging_settings"]["system_prompt"] == K4_ELEMENTS
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I4_POLICY))
        == FINALS_I4_POLICY
    )
    assert canonical_hash(FINALS_I3_POLICY) == (
        "830ce06b7dec224b15be7a60d9813bd08038e5a229709193e6c621a9e18f92e3"
    )
    assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I3_POLICY)) == (
        FINALS_I3_POLICY
    )


def test_partial_render_uses_final_schema_and_only_requested_track():
    schema = {"type": "object", "additionalProperties": False, "properties": {}, "required": []}
    system = preliminary_k4(schema)
    assert "exactly claim_id" not in system
    assert "exactly track" in system
    assert "Output JSON schema:\n" + json.dumps(schema, sort_keys=True, separators=(",", ":")) in (
        system
    )
    system = elements_k4(schema, {"track": "goal", "safe_harbor_category": None})
    assert "G6 전환계획·달성수단" in system
    assert "G1/G2/G3/G5/P1/P2" in system
    assert '"id":"P1"' not in system
    assert '"id":"G1"' in system
    performance = elements_k4(schema, {"track": "performance", "safe_harbor_category": None})
    assert "current_value_id and unit_id" in performance
    assert "only to a claimed PUE observation" in performance
    assert "holds are independent" in performance
    for renderer in (preliminary_k4, lambda s: elements_k4(s, {"track": "goal"})):
        with pytest.raises(ValueError, match="IDENTITY_PROHIBITED"):
            renderer(schema | {"properties": {"claim_id": {"type": "string"}}})
        with pytest.raises(ValueError, match="EXTRA_PROPERTIES"):
            renderer(schema | {"additionalProperties": True})
