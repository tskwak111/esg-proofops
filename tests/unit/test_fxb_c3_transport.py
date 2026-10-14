import json
import sqlite3
from copy import deepcopy

import pytest
from proofops.adapters.local.c3_transport import authenticate_response
from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_I22_POLICY
from proofops.application.tagging.c3_request_binding import current_request, request_binding
from proofops.domain.provenance import canonical_hash

from tests.unit.test_c2_assembly import case
from tests.unit.test_openai_luna import response as provider_response


@pytest.fixture
def recorded(tmp_path):
    inputs, votes = case()
    request = current_request(
        votes[0]["identity"],
        inputs["context"].claim.quote,
        inputs["packet"].to_dict()["c2_sources"],
        FINALS_I22_POLICY,
        1,
    )
    probe = OpenAIProbe("fake", tmp_path / "test-only.sqlite3")
    probe.configure_response_policy(request["snapshot"], role="elements")
    probe._post = lambda body: provider_response(json.dumps(votes[0]["raw"]))
    with probe.response_context(role="elements", replica=1):
        result = probe.complete(
            request["system"],
            request["user_json"],
            request_id=request["id"],
            max_tokens=request["max_tokens"],
            json_mode=True,
            schema_json=request["schema_json"],
        )
    return request, result, probe


def test_fresh_authentication_requires_matching_ledger_and_raw_provider_sidecar(recorded):
    request, result, probe = recorded
    authenticated = authenticate_response(request, result, probe)
    receipt = authenticated["transport_receipt"]
    assert receipt["authenticated"] is True
    assert receipt["fresh_model_call"] is True
    assert receipt["replay"] is False
    assert receipt["binding"] == request_binding(request)
    assert receipt["response_sha256"] == canonical_hash(result)
    assert receipt["origin_receipt_sha256"] == canonical_hash(
        {k: v for k, v in result.items() if k != "content"}
    )


@pytest.mark.parametrize(
    "change",
    [
        "content",
        "provider_id",
        "request_id",
        "wire_sha256",
        "schema_sha256",
        "analysis_policy_sha256",
        "model",
        "signature",
        "missing_ledger",
        "raw_sidecar",
    ],
)
def test_transport_cannot_authenticate_edited_or_unbound_responses(recorded, change):
    request, original, probe = recorded
    result = deepcopy(original)
    if change == "content":
        raw = json.loads(result["content"])
        raw["track"] = "goal"
        result["content"] = json.dumps(raw)
    elif change == "provider_id":
        result["provider_request_id"] = "invented"
    elif change == "request_id":
        result["request_id"] = "historical"
    elif change in ("wire_sha256", "schema_sha256", "analysis_policy_sha256"):
        result["response_request"][change] = "0" * 64
    elif change == "model":
        result["model_binding_sha256"] = "0" * 64
    elif change in ("signature", "missing_ledger"):
        with sqlite3.connect(probe.ledger) as db:
            if change == "signature":
                db.execute("UPDATE probe_calls SET signature=?", ("0" * 64,))
            else:
                db.execute("DELETE FROM probe_calls")
    else:
        path = next(probe._responses.glob("*.json"))
        raw = json.loads(path.read_text())
        raw["provider_response"]["choices"][0]["message"]["content"] = "{}"
        path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="C3_TRANSPORT|MODEL_RESPONSE_CACHE_INVALID"):
        authenticate_response(request, result, probe)


def test_cache_hit_never_gets_fresh_transport_authority(recorded, tmp_path):
    request, original, first = recorded
    second = OpenAIProbe("fake", tmp_path / "second.sqlite3")
    second.configure_response_policy(request["snapshot"], role="elements")
    second._post = lambda body: pytest.fail("cached reply must not call a model")
    retry = request | dict(id="new-local-request")
    with second.response_context(role="elements", replica=1):
        result = second.complete(
            retry["system"],
            retry["user_json"],
            request_id=retry["id"],
            max_tokens=retry["max_tokens"],
            json_mode=True,
            schema_json=retry["schema_json"],
        )
    assert result["response_reuse"]
    assert result["provider_request_id"] == original["provider_request_id"]
    assert "transport_receipt" not in authenticate_response(retry, result, second)
