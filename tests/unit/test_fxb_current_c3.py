import json
from copy import deepcopy
from dataclasses import replace

import pytest
from proofops.adapters.local import c3_processing
from proofops.application.analysis_profile import FINALS_I22_POLICY
from proofops.application.tagging import fact_assembly_c3_v2 as c3
from proofops.application.tagging.c3_request_binding import request_binding
from proofops.application.tagging.fact_assembly_c3 import assemble as previous_assemble
from proofops.domain.provenance import canonical_hash

from tests.unit.test_c2_assembly import case, seal


@pytest.fixture
def reviewed_case(monkeypatch):
    inputs, votes = case()
    inputs["rulepack"] = replace(
        inputs["rulepack"], status="active", approved_by="test-only", approved_at="test-only"
    )
    fingerprint = c3.source_fingerprint_payload(previous_assemble(votes, **inputs).to_dict())
    monkeypatch.setattr(c3, "REVIEWED_SOURCE_IDENTITY", fingerprint)
    monkeypatch.setattr(c3, "REVIEWED_SOURCE_FINGERPRINT_SHA256", canonical_hash(fingerprint))

    class Publication:
        def __init__(self, output):
            pass

        def initialize(self, *args, **kwargs):
            pass

        def result(self, *args):
            return {"confirmed_grade": "E3"}

    monkeypatch.setattr(c3_processing, "LocalC3Publication", Publication)
    from proofops.application.evidence.retrieval import freeze_packet

    packet = freeze_packet(inputs["packet"].to_dict() | dict(run_id="fresh-run"))
    inputs["packet"] = packet
    return inputs, votes[0]["raw"]


def fresh_response(request, raw):
    binding = request_binding(request)
    response = dict(
        request_id=request["id"],
        provider_request_id=f"fresh-provider-{request['replica']}",
        provider="openai",
        model="gpt-6-luna",
        provider_model="gpt-6-luna",
        model_binding_sha256=binding["model_sha256"],
        response_request={
            k: binding[k]
            for k in (
                "tenant_id",
                "source_sha256",
                "replica",
                "role",
                "wire_sha256",
                "schema_sha256",
                "analysis_policy_sha256",
            )
        },
        schema_valid=True,
        content=json.dumps(raw),
    )
    receipt = dict(
        schema="c3-authenticated-transport-v1",
        authenticated=True,
        fresh_model_call=True,
        replay=False,
        binding=binding,
        provider_request_id=response["provider_request_id"],
        response_sha256=canonical_hash(response),
        origin_receipt_sha256=canonical_hash({k: v for k, v in response.items() if k != "content"}),
    )
    return response | dict(simulated=False, transport_receipt=receipt)


def test_three_fresh_current_responses_can_still_publish(reviewed_case, tmp_path):
    inputs, raw = reviewed_case
    calls = []

    def transport(request):
        calls.append(request)
        return fresh_response(request, raw)

    result = c3_processing.process_case(
        inputs, b"", output=tmp_path, transport=transport, analysis_policy=FINALS_I22_POLICY
    )
    assert [r["replica"] for r in calls] == [1, 2, 3]
    assert result["receipt"]["current_responses_bound_3_of_3"]
    assert result["receipt"]["public_auto_confirmed"]
    assert result["published"]
    assert result["receipt"]["engine_decision"]["evidence_grade"] == "E3"
    assert c3.replay(result["receipt"], **inputs).to_dict() == result["receipt"]


@pytest.mark.parametrize(
    "change",
    [
        "wire_sha256",
        "schema_sha256",
        "analysis_policy_sha256",
        "missing_cache_bindings",
        "model_sha256",
        "prompt_sha256",
        "packet_sha256",
        "request_sha256",
        "authenticated",
        "fresh_model_call",
        "replay",
        "missing_receipt",
        "saved_response",
        "cache_reuse",
    ],
)
def test_current_transport_or_response_binding_mismatch_cannot_publish(
    reviewed_case, tmp_path, change
):
    inputs, raw = reviewed_case

    def transport(request):
        response = fresh_response(request, raw)
        if request["replica"] != 2:
            return response
        receipt = response["transport_receipt"]
        if change in ("wire_sha256", "schema_sha256", "analysis_policy_sha256"):
            response["response_request"][change] = "0" * 64
        elif change == "missing_cache_bindings":
            for key in ("wire_sha256", "schema_sha256", "analysis_policy_sha256"):
                response["response_request"].pop(key)
        elif change in ("model_sha256", "prompt_sha256", "packet_sha256", "request_sha256"):
            receipt["binding"][change] = "0" * 64
        elif change in ("authenticated", "fresh_model_call", "replay"):
            receipt[change] = change == "replay"
        elif change == "missing_receipt":
            response.pop("transport_receipt")
        elif change == "saved_response":
            response["saved_response_origin"] = dict(replay=True, fresh_model_call=False)
        else:
            response["response_reuse"] = dict(source_request_id="historical")
        return response

    result = c3_processing.process_case(
        inputs, b"", output=tmp_path, transport=transport, analysis_policy=FINALS_I22_POLICY
    )
    receipt = result["receipt"]
    assert receipt["candidate_auto_confirmed"]
    assert not receipt["public_auto_confirmed"]
    assert not result["published"]
    assert "CURRENT_FRESH_RESPONSES_REQUIRED" in receipt["unresolved"]
    assert c3.replay(receipt, **inputs).to_dict() == receipt


def test_resealing_local_vote_cannot_replace_authenticated_response(reviewed_case, tmp_path):
    inputs, raw = reviewed_case
    receipt = c3_processing.process_case(
        inputs,
        b"",
        output=tmp_path,
        transport=lambda r: fresh_response(r, raw),
        analysis_policy=FINALS_I22_POLICY,
    )["receipt"]
    votes = deepcopy(receipt["raw_receipts"])
    votes[1]["raw"]["dimensions"]["activity"]["quote"] = "환경경영시스템"
    result = c3.assemble(
        [seal(v) for v in votes], analysis_policy=FINALS_I22_POLICY, **inputs
    ).to_dict()
    assert not result["public_auto_confirmed"]
    assert not result["current_responses_bound_3_of_3"]
