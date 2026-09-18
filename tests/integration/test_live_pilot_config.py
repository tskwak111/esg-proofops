"""Pilot config must create distinct real bindings without granting rule authority."""

import pytest
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.service import TaggingSettings

from evaluation.local_upstage_pilot import live_tagging_settings


def test_live_pilot_settings_have_independent_real_profiles():
    result = live_tagging_settings(12)
    preliminary, tagging = (
        TaggingSettings(**(result[key] | {"binding": ModelBinding(**result[key]["binding"])}))
        for key in ("preliminary_settings", "tagging_settings")
    )
    assert preliminary.binding.binding_id != tagging.binding.binding_id
    assert preliminary.binding.synthetic is tagging.binding.synthetic is False
    assert preliminary.model_id == tagging.model_id == "solar-pro4"
    assert preliminary.model_profile == "upstage-preliminary-source-quotes-v1"
    assert tagging.model_profile == "upstage-compact-ids-frozen-unicode-v1"
    assert set(result) == {"preliminary_settings", "tagging_settings", "input_reservation_policy"}


@pytest.mark.parametrize("calls", [True, 0, 5, 61, 12.5])
def test_live_pilot_rejects_invalid_call_limit(calls):
    with pytest.raises(ValueError):
        live_tagging_settings(calls)


def test_preliminary_schema_rejects_the_observed_live_string_dimension():
    import json

    import jsonschema

    schema = json.loads(live_tagging_settings(12)["preliminary_settings"]["schema_json"])
    jsonschema.Draft202012Validator.check_schema(schema)
    response = dict(
        claim_id="11111111-1111-4111-8111-111111111111",
        track="management",
        safe_harbor_category=None,
        track_confidence=0.8,
        dimensions=dict(entity=None, metric="project description", reporting_period=None),
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(response, schema)
    response["dimensions"]["metric"] = dict(source_index=0, quote="emissions")
    jsonschema.validate(response, schema)
    response["dimensions"]["metric"] = None
    jsonschema.validate(response, schema)
