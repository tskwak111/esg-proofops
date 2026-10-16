"""Three real service replicas over a new frozen QA2 packet; no API calls."""

import json
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext, local_relation_tags
from proofops.application.evidence.retrieval import (
    freeze_packet,
    freeze_track_packet,
    retrieve_evidence,
)
from proofops.application.tagging.q1_contract import QA2_ELEMENT_GUIDANCE, QA2_POLICY, R12_POLICY
from proofops.application.tagging.service import RawTagResponse, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_retrieval import SyntheticSearch
from tests.acceptance.test_tagging import setup
from tests.unit.test_k5_context import case


def inputs_for(tmp_path, quote, policy):
    inputs = setup(tmp_path)
    graph, claim = case([quote], (0, quote))
    context = ClaimContext(claim, dict(entity=None, metric=None, reporting_period=None))
    track = TrackCandidate(claim, "management", None)
    packet = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=claim.tenant_id,
        run_id=inputs["packet"].to_dict()["run_id"],
        index_generation="qa2-synthetic-v1",
        rulepack=inputs["rulepack"],
        document_context={},
        token_counter=lambda text: 1,
    )
    payload = {k: v for k, v in packet.to_dict().items() if k != "packet_sha256"}
    packet = freeze_track_packet(
        freeze_packet(payload | dict(structural_quality_policy=policy)),
        track=track,
        rulepack=inputs["rulepack"],
    )
    inputs.update(
        packet=packet,
        context=context,
        original=graph,
        track=track,
        relation_tags=local_relation_tags(context),
        settings=replace(
            inputs["settings"],
            system_prompt=inputs["settings"].system_prompt
            + (QA2_ELEMENT_GUIDANCE if policy == QA2_POLICY else ""),
        ),
    )
    return inputs


def responder(inputs, target="M4", *, states=None, quote=None):
    calls = []

    def invoke(request):
        calls.append(request)
        source = inputs["context"].claim.source_refs[0]
        if quote is not None:
            from tests.acceptance.test_binding import span

            source = span(source, quote)
        state = states[request["replicate_id"] - 1] if states else "present"
        raw = dict(
            claim_id=request["claim_id"],
            packet_sha256=request["packet_sha256"],
            replicate_id=request["replicate_id"],
            track="management",
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=f"M{i}",
                    state=state if f"M{i}" == target else "unknown",
                    evidence_refs=[asdict(source)] if f"M{i}" == target else [],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for i in range(1, 7)
            ],
            superlative_quote=None,
            warnings=[],
        )
        response = inputs["invoke"](request)
        return RawTagResponse(json.dumps(raw), response.usage, True)

    return invoke, calls


@pytest.mark.parametrize("eid", ["M3", "M4"])
@pytest.mark.parametrize(
    "quote",
    [
        "환경 실무자 교육을 다음 분기에 실시할 방침입니다.",
        "환경 교육을 실시할 예정입니다.",
        "ISO 14001 내부심사원 교육을 17명에게 실시할 예정입니다.",
    ],
)
def test_qa2_real_service_veto_and_new_revision_pins(tmp_path, eid, quote):
    results = []
    for policy in (R12_POLICY, QA2_POLICY):
        folder = tmp_path / policy["profile"]
        folder.mkdir()
        inputs = inputs_for(folder, quote, policy)
        invoke, calls = responder(inputs, eid)
        runs = tag_replicates(**(inputs | dict(invoke=invoke)))
        assert len(calls) == 3 and {r.replicate_id for r in runs} == {1, 2, 3}
        assert len({c["request_id"] for c in calls}) == 3
        results.append(runs)
    old, new = results
    for before, after in zip(old, new, strict=True):
        index = int(eid[1:]) - 1
        assert before.guarded.elements[index].state == "present"
        assert after.guarded.elements[index].state == "unknown"
        assert after.guarded.elements[index].reason_code == (
            "QA2_FUTURE_IMPLEMENTATION_REQUIRES_REVIEW"
        )
        assert after.status == "needs_review"
        assert json.loads(after.raw_response_json)["elements"][index]["state"] == "present"
        assert before.prompt_sha256 != after.prompt_sha256
        assert before.packet_sha256 != after.packet_sha256
        assert before.request.request_signature != after.request.request_signature


def test_qa2_two_present_one_unknown_remains_unresolved(tmp_path):
    inputs = inputs_for(tmp_path, "환경 교육을 실시했습니다.", QA2_POLICY)
    invoke, _ = responder(inputs, states=["present", "present", "unknown"])
    runs = tag_replicates(**(inputs | dict(invoke=invoke)))
    from proofops.application.tagging.consensus import form_consensus

    consensus = form_consensus(
        runs,
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=inputs["tenant_id"],
        tag_revision=2,
    )
    assert consensus.confirmed_tags is None
    assert consensus.review_status == "needs_review"


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("M4", "저탄소·순환 소재 제품 포트폴리오 확대"),
        ("M2", "유관부서의 환경경영 이행과 개선과제의 실행"),
    ],
)
def test_qa2_does_not_reapply_unselected_historical_q1_vetoes(tmp_path, eid, quote):
    for policy in (R12_POLICY, QA2_POLICY):
        folder = tmp_path / policy["profile"]
        folder.mkdir()
        inputs = inputs_for(folder, quote, policy)
        invoke, _ = responder(inputs, eid)
        runs = tag_replicates(**(inputs | dict(invoke=invoke)))
        assert all(r.guarded.elements[int(eid[1:]) - 1].state == "present" for r in runs)


def test_qa2_unreadable_graph_cannot_validate_present(tmp_path):
    inputs = inputs_for(tmp_path, "환경 교육을 실시했습니다.", QA2_POLICY)
    graph = inputs["original"]
    unreadable = replace(
        graph, blocks=tuple(replace(b, quality="unreadable") for b in graph.blocks)
    )
    invoke, calls = responder(inputs)
    with pytest.raises(ValueError, match="packet/claim/source identity mismatch"):
        tag_replicates(**(inputs | dict(invoke=invoke, original=unreadable)))
    assert not calls


def test_qa2_compiled_prompt_survives_transport_and_policy_projection(tmp_path, monkeypatch):
    from proofops.application.tagging.k10_contract import elements

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, calls, request = configured(tmp_path, monkeypatch)
    approval = adapter._authorize(adapter._settings, request)
    assert approval.ready
    prompt = elements(
        dict(type="object", properties={}, additionalProperties=False),
        dict(track="management", safe_harbor_category=None),
        quality_policy=QA2_POLICY,
    )
    adapter._settings = replace(adapter._settings, system_prompt=prompt)
    adapter._authorize = lambda settings, dispatched: approval
    request["system_prompt"] = adapter._settings.system_for_track("management", None)
    data = json.loads(request["user_json"])
    data["untrusted_document_data"]["structural_quality_policy"] = QA2_POLICY
    request["user_json"] = json.dumps(data)
    system, wire, _, _, _ = adapter._wire_request(request)
    assert QA2_ELEMENT_GUIDANCE in system
    assert "structural_quality_policy" not in json.loads(wire)["untrusted_document_data"]
    assert len((system + wire).encode()) < 16384
    assert canonical_hash(prompt) != canonical_hash(
        elements(
            dict(type="object", properties={}, additionalProperties=False),
            dict(track="management", safe_harbor_category=None),
            quality_policy=R12_POLICY,
        )
    )
    assert not calls
