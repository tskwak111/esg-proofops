"""TB1 composition, cold replay and real tagging admission without provider calls."""

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, replace

import pytest


@pytest.mark.parametrize("module", ["tb1_claim_source", "i31_claim_source"])
def test_source_composition_cold_replay_and_tamper(tmp_path, monkeypatch, module):
    from importlib import import_module

    reader = import_module("proofops.adapters.local." + module)
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.application.evidence.span_citations import verify_source_ref
    from proofops.domain.provenance import canonical_hash
    from proofops.domain.values import SourceRef

    from tests.unit.test_pb1_source import fixture

    graph, source, ref = fixture()
    from tests.integration.test_upstage_ocr_page import store

    db = store(tmp_path, transport=lambda *_: pytest.fail("unexpected provider call"))
    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: db)
    instance = reader.for_run("tb1-native-test")
    receipt = instance.attest_claim_spans(graph, source.content, [ref], tenant_id=graph.tenant_id)
    assert receipt["previous_receipt"]["policy"] == reader.previous.claim_source_policy()
    assert receipt["tb1_header_proofs"][0]["status"] == "verified"
    assert publication_reader(receipt["policy"]) is reader
    assert (
        instance.recompute_claim_receipt(
            receipt, graph, source.content, [ref], tenant_id=graph.tenant_id
        )
        == receipt
    )

    @dataclass(frozen=True)
    class Claim:
        source_refs: tuple = (ref,)
        source_quality: str = "unverified"

    @dataclass(frozen=True)
    class Discovery:
        claims: tuple = (Claim(),)

    discovery, projected = reader.replay_claim_spans(
        receipt, graph, source.content, Discovery(), tenant_id=graph.tenant_id
    )
    assert discovery.claims[0].source_quality == "verified"
    header = SourceRef(**receipt["tb1_header_proofs"][0]["ref"])
    assert (
        verify_source_ref(header, projected, tenant_id=graph.tenant_id).verification_state
        == "verified"
    )
    assert all(b.quality != "verified" for b in projected.blocks if b.kind == "table")
    bad = deepcopy(receipt)
    bad["tb1_header_proofs"][0]["ref"]["quote"] = "2025"
    bad["artifact_sha256"] = canonical_hash(
        {k: v for k, v in bad.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="MISMATCH"):
        instance.recompute_claim_receipt(
            bad, graph, source.content, [ref], tenant_id=graph.tenant_id
        )
    with pytest.raises(ValueError, match="MISMATCH"):
        instance.recompute_claim_receipt(
            receipt, graph, source.content + b"\n", [ref], tenant_id=graph.tenant_id
        )


def test_wire_projects_complete_bundle_and_rejects_missing_catalog(tmp_path, monkeypatch):
    from proofops.application.tagging.qt1_tuples import POLICY as QT1_POLICY
    from proofops.application.tagging.tb1_table_bundles import augment_packet

    from tests.integration.test_upstage_tagging_v4 import configured
    from tests.unit.test_tb1_table_bundles import table_case

    graph, claim = table_case()
    adapter, _, calls, request = configured(tmp_path, monkeypatch)
    user = json.loads(request["user_json"])
    data = user["untrusted_document_data"]
    data.update(
        allowed_elements=["P1", "P2"],
        evidence_candidates=[],
        qt1_tuple_policy=QT1_POLICY,
        qt1_table_tuples=[{"legacy": "not forwarded"}],
    )
    augment_packet(data, claim, graph, tenant_id=graph.tenant_id)
    request["user_json"] = json.dumps(user)
    system, wire, catalog, *_ = adapter._wire_request(request)
    compact = json.loads(wire)["untrusted_document_data"]["tb1_table_bundles"]
    assert "TB1:" in system and not calls
    assert "QT1 V25:" not in system
    assert json.loads(wire)["untrusted_document_data"]["qt1_table_tuples"] == []
    for bundle in compact:
        assert all(key in catalog for key in bundle["required_ids"])
        assert catalog[bundle["period_id"]]["quote"] == "2025년"
        assert set(bundle["row_labels_ids"]).issubset(bundle["required_ids"])
    data["evidence_candidates"] = []
    request["user_json"] = json.dumps(user)
    with pytest.raises(ValueError, match="TB1_EVIDENCE_CATALOG_MISMATCH"):
        adapter._wire_request(request)


def test_new_profile_create_resume_and_tamper(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import TB1_POLICY

    from tests.integration import test_qt1_pipeline

    monkeypatch.setattr(test_qt1_pipeline, "QT1_POLICY", TB1_POLICY)
    test_qt1_pipeline.test_new_profile_create_resume_and_tamper_guard(tmp_path, monkeypatch)


@pytest.mark.parametrize("partial", [False, True])
def test_numeric_bundle_survives_legacy_preparation_but_partial_does_not(tmp_path, partial):
    from uuid import uuid4

    from proofops.application.analysis_profile import TB1_POLICY
    from proofops.application.budget import BudgetLimits, RoleLimit
    from proofops.application.claims import Claim
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.evidence.retrieval import (
        freeze_packet,
        freeze_track_packet,
        retrieve_evidence,
    )
    from proofops.application.tagging.pb2_table_evidence import augment_packet as pb2_augment
    from proofops.application.tagging.qt1_tuples import augment_packet as qt1_augment
    from proofops.application.tagging.tb1_table_bundles import augment_packet, bundle_refs
    from proofops.application.tagging.tracks import TrackCandidate
    from proofops.domain.values import SourceRef

    from tests.acceptance.test_citations import RUN
    from tests.acceptance.test_retrieval import SyntheticSearch
    from tests.acceptance.test_tagging import SyntheticResponder, execute, setup
    from tests.unit.test_pb2_table_evidence import observation_case

    graph, source, simple = observation_case()
    inputs = setup(tmp_path)
    claim = Claim(
        str(uuid4()),
        source.tenant_id,
        source.document_version_id,
        graph.parse_manifest_id,
        source.sha256,
        simple.source_refs[0].quote,
        simple.source_refs,
        "verified",
        ("environment",),
        replace(inputs["context"].claim.receipt, source_id=simple.source_refs[0].source_id),
    )
    rulepack = replace(inputs["rulepack"], tenant_id=source.tenant_id)
    track = TrackCandidate(claim, "performance", None)
    packet = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=source.tenant_id,
        run_id=RUN,
        index_generation="synthetic-v1",
        rulepack=rulepack,
        document_context={},
        token_counter=lambda _: 1,
    )
    data = freeze_track_packet(packet, track=track, rulepack=rulepack).to_dict()
    data.pop("packet_sha256")
    for augment in (pb2_augment, qt1_augment, augment_packet):
        augment(data, claim, graph, tenant_id=source.tenant_id)
    selected = bundle_refs(next(i for i in data["tb1_table_bundles"] if i["year"] == "2024"))
    inputs["usage_store"].create_budget(
        source.tenant_id,
        RUN,
        claim.document_version_id,
        BudgetLimits(10000, 10000, (RoleLimit("tagger", 3, 10000, 1000, 11000),)),
    )
    inputs.update(
        packet=freeze_packet(data),
        context=ClaimContext(claim, {}),
        track=track,
        original=graph,
        rulepack=rulepack,
        tenant_id=source.tenant_id,
        relation_tags={},
        semantic_policy=TB1_POLICY["semantic_admission"],
        invoke=SyntheticResponder(
            SourceRef(**selected[0]),
            changes={
                i: dict(
                    element=dict(
                        evidence_refs=selected[:2] if partial else selected, normalized_value="15"
                    )
                )
                for i in (1, 2, 3)
            },
        ),
    )
    runs = execute(inputs)
    assert len(runs) == 3
    for run in runs:
        assert run.guarded.elements[0].state == ("unknown" if partial else "present"), run.errors
        if not partial:
            assert [asdict(r) for r in run.guarded.elements[0].evidence_refs] == selected
