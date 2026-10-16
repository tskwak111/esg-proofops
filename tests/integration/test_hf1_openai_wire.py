"""HF1: exercise final v29 renderers; no HTTP, credentials or model calls."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.tagging import cf1_inventory, cf5_context
from proofops.application.tagging.c3_request_binding import CF2_POLICY, current_request
from proofops.application.tagging.element_inventory import inventory_request, plan_inventory
from proofops.application.tagging.finals_i4 import K4_ELEMENTS
from proofops.application.tagging.i24_inventory import transport_request
from proofops.application.tagging.k4_contract import RESPONSE_POLICY
from proofops.application.tagging.pb1_classification import COMPACT_PROFILE
from proofops.application.tagging.preliminary import preliminary_table_request
from proofops.domain.provenance import canonical_hash
from proofops_agent.sc1_inventory import SC1InventoryTransport

from tests.openai_wire_contract import assert_json_mode_request, strict_schema_issues


def rendered_cases(tmp_path, monkeypatch):
    """The same final wire tuples used by worker transports, with synthetic input."""
    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection
    from tests.integration.test_upstage_preliminary_table_transport import configured_with_table
    from tests.integration.test_upstage_tagging_v4 import configured

    sc1_root = tmp_path / "sc1"
    sc1_root.mkdir()
    live, inputs, _, _ = runtime(sc1_root, monkeypatch)
    scope = selection(inputs) | dict(cf1_inventory=cf1_inventory.POLICY)
    chunk = plan_inventory(live.graph, scope)["chunks"][0]
    original = inventory_request(chunk, 1, live.settings.model_sha256)
    live.allow_packet(original["run_id"], original["packet_sha256"])
    adapter = SC1InventoryTransport(
        live.probe,
        sc1_root / "wire",
        settings=live.settings,
        tenant_id=live.graph.tenant_id,
        authorize=live._authorize,
    )
    cases = {"sc1": adapter._wire_request(transport_request(original, live.settings))}

    pre_root = tmp_path / "preliminary"
    pre_root.mkdir()
    adapter, request, _, claim, graph = configured_with_table(pre_root, monkeypatch)
    settings = replace(
        adapter._settings,
        model_profile=COMPACT_PROFILE,
        system_prompt=cf5_context.PRELIMINARY,
        schema_json=Path("contracts/jsonschema/preliminary_tags.schema.json").read_text(),
    )
    adapter._settings = settings
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    packet = cf5_context.preserve_context(
        preliminary_table_request(claim, graph, tenant_id=graph.tenant_id), claim, graph
    )
    packet["preliminary_response_policy"] = RESPONSE_POLICY
    request.update(
        system_prompt=settings.rendered_system,
        user_json=json.dumps(packet),
        packet_sha256=canonical_hash(packet),
    )
    cases["preliminary"] = adapter._wire_request(request)
    request["preliminary_fact_fields"] = "preliminary-fact-fields-pb2-v1"
    cases["preliminary_pb2"] = adapter._wire_request(request)

    for track, element in (("goal", "G1"), ("performance", "P1"), ("management", "M1")):
        root = tmp_path / track
        root.mkdir()
        adapter, _, _, request = configured(root, monkeypatch)
        adapter._settings = replace(adapter._settings, system_prompt=K4_ELEMENTS)
        monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
        request["system_prompt"] = adapter._settings.system_for_track(track, None)
        user = json.loads(request["user_json"])
        user["untrusted_document_data"].update(
            tagging_response_policy=RESPONSE_POLICY, allowed_elements=[element]
        )
        request["user_json"] = json.dumps(user)
        cases[f"elements_{track}"] = adapter._wire_request(request)

    from proofops.application.tagging.relations import OCCURRENCE_V3_PROFILE
    from proofops_agent.upstage_relations import UpstageOccurrenceV3RelationsTransport

    from evaluation.local_upstage_pilot import live_tagging_settings
    from tests.acceptance.test_binding import corpus
    from tests.integration.test_r108_relation_occurrence_v3 import packet as relation_packet
    from tests.integration.test_upstage_relations_transport import configured as relation_configured

    root = tmp_path / "relation"
    root.mkdir()
    old, probe, _, request, _ = relation_configured(root, monkeypatch)
    graph, claim, refs = corpus()
    envelope = relation_packet(refs[:1], graph, claim) | dict(
        claim_id=claim.claim_id, retrieval_packet_sha256=request["retrieval_packet_sha256"]
    )
    config = live_tagging_settings(1024, relations=True, relation_profile="occurrence-v3")[
        "relation_settings"
    ]
    settings = replace(
        old._settings,
        model_profile=OCCURRENCE_V3_PROFILE,
        system_prompt=config["system_prompt"],
        schema_json=config["schema_json"],
    )
    adapter = UpstageOccurrenceV3RelationsTransport(
        probe,
        root / "v3",
        settings=settings,
        tenant_id=graph.tenant_id,
        authorize=lambda *args: None,
    )
    monkeypatch.setattr(adapter, "_authorize_request", lambda _: None)
    request.update(
        system_prompt=settings.rendered_system,
        user_json=json.dumps(envelope),
        packet_sha256=canonical_hash(envelope),
    )
    cases["relation"] = adapter._wire_request(request)

    req = current_request(
        dict(tenant_id=graph.tenant_id, original_sha256="a" * 64, packet_sha256="b" * 64),
        "No certification claim.",
        [dict(quote="No certification claim.", page_num=1)],
        {"cf2_c3_response_binding": CF2_POLICY},
        1,
    )
    cases["c3"] = req["system"], req["user_json"], {}, None, req["schema_json"]
    return cases


@pytest.fixture
def cases(tmp_path, monkeypatch):
    return rendered_cases(tmp_path, monkeypatch)


def test_every_v29_wire_has_trusted_json_instruction_and_valid_local_schema(cases, tmp_path):
    probe = OpenAIProbe("offline-only", tmp_path / "probe.sqlite3")
    for name, (system, user, _, _, schema) in cases.items():
        body = probe.request_body(system, user, request_id=name, json_mode=True)
        assert_json_mode_request(body, json.loads(schema))
        assert "{{OUTPUT_SCHEMA_JSON}}" not in system


def test_all_v29_schemas_are_audited_against_openai_strict_rules(cases):
    # JSON mode deliberately retains local conditional/source validation. These
    # exact incompatibilities must block any future switch to strict json_schema;
    # deleting those semantic constraints is not a fix for JSON-mode HTTP 400.
    expected = {
        "sc1": [],
        "c3": [],
        "preliminary": [
            "$:allOf",
            "$/allOf/0:else",
            "$/allOf/0:if",
            "$/allOf/0:then",
            "$/properties/dimensions:additionalProperties",
        ],
        "preliminary_pb2": [
            "$:allOf",
            "$/allOf/0:else",
            "$/allOf/0:if",
            "$/allOf/0:then",
            "$/properties/dimensions:required",
        ],
        "relation": ["$/properties/relations/items/properties/dimensions:required"],
    }
    for track in ("goal", "performance", "management"):
        expected[f"elements_{track}"] = [
            "$/$defs/Element:allOf",
            "$/$defs/Element/allOf/0:if",
            "$/$defs/Element/allOf/0:then",
        ]
    assert set(cases) == set(expected)
    for name, (_, _, _, _, raw) in cases.items():
        assert strict_schema_issues(json.loads(raw), name=name) == sorted(expected[name]), name


def test_saved_219_byte_error_body_is_exactly_reconstructed():
    body = json.dumps(
        {
            "error": {
                "message": "'messages' must contain the word 'json' in some form, "
                "to use 'response_format' of type 'json_object'.",
                "type": "invalid_request_error",
                "param": "messages",
                "code": None,
            }
        },
        indent=2,
    ).encode()
    assert len(body) == 219
    assert hashlib.sha256(body).hexdigest() == (
        "c259bb7f479b9faee0845ca7c0c7d8fca618e090ab8f4270edd4de252b2488f3"
    )


@pytest.mark.parametrize(
    "mutation, issue",
    [
        (lambda s: s.update(required=[]), "$/properties/child:required"),
        (lambda s: s.pop("additionalProperties"), "$/properties/child:additionalProperties"),
        (lambda s: s.update(oneOf=[{"type": "object"}]), "$/properties/child:oneOf"),
    ],
)
def test_strict_audit_detects_nested_regressions(mutation, issue):
    child = dict(
        type="object",
        additionalProperties=False,
        required=["value"],
        properties=dict(value=dict(type=["string", "null"], enum=["ok", None])),
    )
    schema = dict(
        type="object", additionalProperties=False, required=["child"], properties=dict(child=child)
    )
    assert strict_schema_issues(schema, name="valid") == []
    mutation(child)
    assert issue in strict_schema_issues(schema, name="valid")


def test_strict_audit_rejects_bad_name_and_enum_null_type():
    schema = dict(
        type="object",
        additionalProperties=False,
        required=["value"],
        properties=dict(value=dict(type="string", enum=["ok", None, 1])),
    )
    assert strict_schema_issues(schema, name="x" * 65) == [
        "$/properties/value:enum_or_const_type",
        "$:invalid_name",
    ]
