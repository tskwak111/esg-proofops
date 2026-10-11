import json
from dataclasses import asdict

import pytest
from jsonschema import Draft202012Validator
from proofops.application.analysis_profile import (
    FINALS_I3_POLICY,
    FINALS_K4_POLICY,
    apply_pilot_profile,
    publication_policy_for,
)
from proofops.application.tagging.k4_contract import RESPONSE_POLICY
from proofops.domain.provenance import canonical_hash

from tests.integration.test_upstage_tagging_v4 import configured


def test_dispatch_owned_identity_survives_actual_transport_and_keeps_raw_receipt(
    tmp_path, monkeypatch
):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["tagging_response_policy"] = RESPONSE_POLICY
    request["user_json"] = json.dumps(user)
    _, _, _, _, schema = adapter._wire_request(request)
    payload = dict(
        track="performance",
        safe_harbor_category=None,
        superlative_quote=None,
        warnings=[],
        elements=[
            dict(
                element_id=e,
                state="unknown",
                evidence_refs=[],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            )
            for e in ("G1", "P2")
        ],
    )
    Draft202012Validator(json.loads(schema)).validate(payload)
    assert not {"claim_id", "packet_sha256", "replicate_id"} & set(json.loads(schema)["properties"])

    def post(body):
        calls.append(body)
        return dict(
            id="fixture-provider",
            model=probe.model,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(payload)))],
        )

    monkeypatch.setattr(probe, "_post", post)
    response = adapter.invoke(request)
    assert len(calls) == 1
    decoded = json.loads(response.raw_response_json)
    for key in ("claim_id", "packet_sha256", "replicate_id"):
        assert decoded[key] == request[key]
    receipt = json.loads(response.provider_response_json)
    assert json.loads(receipt["content"]) == payload
    user["untrusted_document_data"]["tagging_response_policy"] = RESPONSE_POLICY | dict(
        profile="tampered"
    )
    request["user_json"] = json.dumps(user)
    with pytest.raises(ValueError, match="K4_RESPONSE_POLICY_MISMATCH"):
        adapter._wire_request(request)
    assert len(calls) == 1


def test_k4_is_explicit_and_i3_extraction_pins_remain_identical():
    from argparse import Namespace

    assert publication_policy_for("finals-unattended-v2") == FINALS_I3_POLICY
    assert (
        publication_policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_K4_POLICY))
        == FINALS_K4_POLICY
    )
    options = []
    for policy in (FINALS_I3_POLICY, FINALS_K4_POLICY):
        args = Namespace(
            analysis_profile="finals-unattended-v2", analysis_policy_sha256=canonical_hash(policy)
        )
        apply_pilot_profile(args)
        options.append({k: v for k, v in vars(args).items() if k.startswith("extraction_")})
    assert options[0] == options[1]
    assert (
        canonical_hash(FINALS_I3_POLICY)
        == "830ce06b7dec224b15be7a60d9813bd08038e5a229709193e6c621a9e18f92e3"
    )


def test_unlocated_unit_is_recovered_from_verified_parent_row_only():
    from dataclasses import replace

    from proofops.application.evidence.span_citations import span_verified_graph
    from proofops.application.tagging.pb2_table_evidence import (
        ROW_UNIT_POLICY,
        augment_packet,
        observation_sources,
    )

    from tests.unit.test_pb2_table_evidence import observation_case

    graph, source, claim = observation_case()
    old = observation_sources(claim, graph, tenant_id=graph.tenant_id)
    unit_id = old["unit"]["ref"].source_id
    graph = replace(
        graph, verified_spans=tuple(r for r in graph.verified_spans if r.source_id != unit_id)
    )
    assert observation_sources(claim, graph, tenant_id=graph.tenant_id) is None
    fixed = observation_sources(claim, graph, tenant_id=graph.tenant_id, recover_row_unit=True)
    assert fixed["unit"]["ref"].source_id == claim.source_refs[0].source_id
    assert fixed["unit"]["ref"].quote == "tCO2eq"
    data = augment_packet(
        dict(
            allowed_elements=["P1"],
            evidence_candidates=[
                dict(
                    source_id=claim.source_refs[0].source_id,
                    source_scope="local_claim",
                    allowed_elements=["P1"],
                    source_refs=[asdict(claim.source_refs[0])],
                )
            ],
        ),
        claim,
        graph,
        tenant_id=graph.tenant_id,
        policy=ROW_UNIT_POLICY,
    )
    assert data["table_observation_evidence"]["unit"] == asdict(fixed["unit"]["ref"])
    rejected = span_verified_graph(graph, (), "0" * 64)
    assert (
        observation_sources(claim, rejected, tenant_id=graph.tenant_id, recover_row_unit=True)
        is None
    )


def test_k4_context_policy_reaches_preliminary_replicas(tmp_path, monkeypatch):
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.integration.test_live_tagging_worker import configured as runtime_fixture

    old, claim, graph, _, _, usage = runtime_fixture(tmp_path, monkeypatch, context=True)
    snapshot = {k: v for k, v in old.snapshot.items() if k != "input_hash"}
    snapshot.update(
        analysis_profile_policy=FINALS_K4_POLICY, pipeline_profile="finals-unattended-v2"
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    runtime = LiveTaggingRuntime(
        old.runner,
        snapshot,
        graph,
        old.lease,
        usage,
        probe=old.preliminary_transport._probe,
        ledger=old.ledger,
        receipts=old.receipts,
    )
    dispatched = []

    def replicas(*args, **kwargs):
        dispatched.append(args[0])
        return None

    monkeypatch.setattr(runtime, "_source_replicas", replicas)
    assert runtime.preliminary(claim, graph) is None
    assert dispatched == ["preliminary"]
