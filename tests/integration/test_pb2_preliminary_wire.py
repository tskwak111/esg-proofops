"""Offline wire-shape check; authorization is covered by the existing harness."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from proofops.application.tagging.pb1_classification import COMPACT_PROFILE, COMPACT_PROMPT
from proofops.application.tagging.preliminary import preliminary_table_request
from proofops.domain.provenance import canonical_hash

from tests.integration.test_upstage_preliminary_table_transport import configured_with_table


def test_pb2_shape_has_only_known_axes_and_legacy_wire_is_unchanged(tmp_path, monkeypatch):
    adapter, request, _, claim, graph = configured_with_table(tmp_path, monkeypatch)
    settings = replace(
        adapter._settings,
        model_profile=COMPACT_PROFILE,
        system_prompt=COMPACT_PROMPT,
        schema_json=Path("contracts/jsonschema/preliminary_tags.schema.json").read_text(),
    )
    adapter._settings = settings
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    envelope = preliminary_table_request(
        claim,
        graph,
        tenant_id=graph.tenant_id,
        role_resolution=True,
        goal_role=True,
        actor_role=True,
        period_role=True,
    )
    envelope["prompt_sha256"] = canonical_hash(COMPACT_PROMPT)
    request.update(
        model_profile=settings.model_profile,
        system_prompt=settings.rendered_system,
        binding=asdict(settings.binding),
        user_json=json.dumps(envelope),
        packet_sha256=canonical_hash(envelope),
    )
    base = adapter._wire_request(request)
    assert base[4] == settings.schema_json
    request["preliminary_fact_fields"] = "preliminary-fact-fields-pb2-v1"
    current = adapter._wire_request(request)
    shape = json.loads(current[4])["properties"]["dimensions"]
    assert shape["additionalProperties"] is False
    assert set(shape["properties"]) == {
        "entity",
        "metric",
        "reporting_period",
        "facility",
        "scope",
        "product",
        "material",
        "boundary",
    }
    assert current[0].startswith(base[0])
    assert current[1] == base[1]
    request["preliminary_fact_fields"] = "unsupported"
    with pytest.raises(ValueError, match="POLICY_UNKNOWN"):
        adapter._wire_request(request)
