import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local.cf6_transport import authenticate
from proofops.application.budget import TokenUsage
from proofops.application.tagging.cf6_confirmation import POLICY
from proofops.application.tagging.service import RawTagResponse
from proofops.domain.provenance import canonical_hash

from tests.unit.test_fxb_c3_transport import recorded as origin_fixture


@pytest.fixture
def recorded(tmp_path):
    return origin_fixture.__wrapped__(tmp_path)


def inputs(recorded):
    original, provider, probe = recorded
    request = dict(
        request_id=original["id"],
        request_signature="a" * 64,
        tenant_id=original["identity"]["tenant_id"],
        packet_sha256=original["identity"]["packet_sha256"],
        replicate_id=1,
        cf6_confirmation=POLICY,
        cf6_analysis_policy_sha256=provider["response_request"]["analysis_policy_sha256"],
        system_prompt=original["system"],
        max_tokens=original["max_tokens"],
    )
    response = RawTagResponse(
        provider["content"],
        TokenUsage(10, 5, 0, 0, 1, "succeeded", provider["provider_request_id"]),
        False,
        json.dumps(provider),
    )
    kwargs = dict(
        settings=SimpleNamespace(model_sha256="b" * 64),
        wire_system=original["system"],
        wire_user=original["user_json"],
        wire_schema=original["schema_json"],
    )
    return request, response, probe, kwargs


def test_cf6_authenticates_matching_durable_origin(recorded):
    request, response, probe, kwargs = inputs(recorded)
    result = authenticate(request, response, probe, **kwargs)
    receipt = json.loads(result.provider_response_json)["cf6_transport_receipt"]
    assert receipt["authenticated"] and receipt["fresh_model_call"]
    assert receipt["expanded_sha256"] == canonical_hash(response.raw_response_json)


@pytest.mark.parametrize(
    "mutation",
    ["body", "provider", "policy", "replica", "schema", "wire", "self_receipt", "cache", "replay"],
)
def test_cf6_broker_rejects_resealed_or_reused_origin(recorded, mutation):
    request, response, probe, kwargs = inputs(recorded)
    provider = json.loads(response.provider_response_json)
    if mutation in ("cache", "replay"):
        provider["response_reuse" if mutation == "cache" else "saved_response_origin"] = {}
        response = replace(response, provider_response_json=json.dumps(provider))
        assert authenticate(request, response, probe, **kwargs) == response
        return
    if mutation == "body":
        provider["content"] = "{}"
    elif mutation == "provider":
        provider["provider_request_id"] = "invented"
    elif mutation == "self_receipt":
        provider["cf6_transport_receipt"] = {"authenticated": True}
    else:
        provider["response_request"][
            dict(
                policy="analysis_policy_sha256",
                replica="replica",
                schema="schema_sha256",
                wire="wire_sha256",
            )[mutation]
        ] = "changed"
    response = replace(response, provider_response_json=json.dumps(provider))
    with pytest.raises(ValueError, match="CF6_TRANSPORT|MODEL_RESPONSE_CACHE_INVALID"):
        authenticate(request, response, probe, **kwargs)
