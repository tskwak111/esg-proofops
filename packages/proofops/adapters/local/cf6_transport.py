"""CF6 current-response attestation at the authenticated broker boundary."""

import json
from dataclasses import replace

from proofops.adapters.local.model_response_cache import ModelResponseCache
from proofops.domain.provenance import canonical_hash


def authenticate(request, response, probe, *, settings, wire_system, wire_user, wire_schema):
    selected = request.get("cf6_confirmation")
    if selected is None or response.raw_response_json is None:
        return response
    from proofops.application.tagging.cf6_confirmation import policy

    if selected != policy(selected.get("required_votes")):
        raise ValueError("CF6_POLICY_MISMATCH")
    provider = json.loads(response.provider_response_json or "{}")
    if response.synthetic or any(
        k in provider for k in ("response_reuse", "saved_response_origin")
    ):
        return response
    body = probe.request_body(
        wire_system,
        wire_user,
        request_id=request["request_id"],
        max_tokens=request["max_tokens"],
        json_mode=True,
    )
    cache = provider.get("response_request", {})
    expected = dict(
        tenant_id=request["tenant_id"],
        replica=request["replicate_id"],
        role="elements",
        wire_sha256=canonical_hash(body),
        schema_sha256=canonical_hash(wire_schema),
        analysis_policy_sha256=request["cf6_analysis_policy_sha256"],
    )
    if (
        provider.get("request_id") != request["request_id"]
        or provider.get("provider_request_id") != response.usage.provider_request_id
        or provider.get("simulated", False) is not False
        or provider.get("schema_valid") is not True
        or provider.get("model") != body["model"]
        or provider.get("provider_model") != body["model"]
        or provider.get("model_binding_sha256") != canonical_hash(probe.wire_policy)
        or any(cache.get(k) != v for k, v in expected.items())
    ):
        raise ValueError("CF6_TRANSPORT_REQUEST_MISMATCH")
    _, digest = ModelResponseCache._verified(
        canonical_hash(cache),
        (str(probe.ledger), request["request_id"], json.dumps(provider), canonical_hash(provider)),
    )
    receipt = dict(
        schema="cf6-authenticated-transport-v1",
        authenticated=True,
        fresh_model_call=True,
        replay=False,
        binding=dict(
            request_id=request["request_id"],
            request_signature=request["request_signature"],
            tenant_id=request["tenant_id"],
            packet_sha256=request["packet_sha256"],
            replica=request["replicate_id"],
            model_sha256=settings.model_sha256,
            prompt_sha256=canonical_hash(request["system_prompt"]),
            analysis_policy_sha256=request["cf6_analysis_policy_sha256"],
        ),
        provider_request_id=provider["provider_request_id"],
        response_sha256=canonical_hash(provider),
        expanded_sha256=canonical_hash(response.raw_response_json),
        origin_receipt_sha256=digest,
    )
    return replace(
        response, provider_response_json=json.dumps(provider | dict(cf6_transport_receipt=receipt))
    )
