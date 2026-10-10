from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.application.evidence.span_citations import span_verified_graph
from proofops.domain.values import LlmElement

from tests.unit.test_pb1_source import fixture


def observation_case():
    from proofops.adapters.local.upstage_ocr_profile_v7 import cell_proof

    graph, source, ref = fixture()
    proof = cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    refs = [replace(ref, verification_state="verified")]
    refs += [
        replace(type(ref)(**p["source_ref"]), verification_state="verified")
        for p in proof["cell_proofs"]
    ]
    graph = span_verified_graph(graph, refs, "0" * 64)
    claim = SimpleNamespace(
        tenant_id=source.tenant_id, source_refs=(refs[0],), source_quality="verified"
    )
    return graph, source, claim


def test_p1_selected_full_row_maps_to_exact_current_value_and_unit():
    from proofops.application.tagging.pb2_table_evidence import prepare_element

    graph, source, claim = observation_case()
    row = claim.source_refs[0]
    element = LlmElement("P1", "present", (row,), row.quote, None, None)
    new, accepted = prepare_element(element, claim, graph, tenant_id=source.tenant_id)
    assert accepted
    assert new.normalized_value == "15"
    assert {r.quote for r in new.evidence_refs} == {"15", "tCO2eq"}


@pytest.mark.parametrize(
    "state,value", [("unknown", None), ("present", "10"), ("present", "tCO2eq")]
)
def test_no_present_inference_or_previous_year_unit_only_credit(state, value):
    from proofops.application.tagging.pb2_table_evidence import prepare_element

    graph, source, claim = observation_case()
    element = LlmElement("P1", state, claim.source_refs, value, None, None)
    assert prepare_element(element, claim, graph, tenant_id=source.tenant_id)[1] is False


def test_unverified_cells_and_wrong_tenant_stay_unresolved():
    from proofops.application.tagging.pb2_table_evidence import prepare_element

    graph, source, claim = observation_case()
    element = LlmElement("P1", "present", claim.source_refs, claim.source_refs[0].quote, None, None)
    assert not prepare_element(element, claim, graph, tenant_id=str(uuid4()))[1]
    graph = replace(graph, verified_spans=claim.source_refs)
    assert not prepare_element(element, claim, graph, tenant_id=source.tenant_id)[1]


def test_table_separator_recovery_keeps_numeric_boundaries_and_raw_offsets():
    from proofops.application.tagging.pb2_citation_restore import restore_table

    ref = dict(quote="Scope 1\ttCO2eq\t10\t15", char_start=23)
    out = restore_table("tCO2eq | 10 | 15", ref)
    assert out["quote"] == "tCO2eq\t10\t15"
    assert out["char_start"] == 31
    for selection in ("t CO2eq | 10 | 15", "tCO2eq | 1015", "tCO2eq | 10 | 16"):
        with pytest.raises(ValueError):
            restore_table(selection, ref)


def test_comparison_value_needs_its_verified_year_in_same_table():
    from proofops.adapters.local.upstage_ocr_profile_v8 import cell_proof
    from proofops.application.tagging.pb2_table_evidence import prepare_element
    from proofops.domain.values import SourceRef

    graph, source, ref = fixture()
    proof = cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    refs = [replace(ref, verification_state="verified")]
    refs += [
        replace(SourceRef(**p["source_ref"]), verification_state="verified")
        for p in proof["cell_proofs"]
    ]
    graph = span_verified_graph(graph, refs, "0" * 64)
    claim = SimpleNamespace(
        tenant_id=source.tenant_id, source_refs=(refs[0],), source_quality="verified"
    )
    value = next(r for r in refs if r.quote == "10")
    year = next(r for r in refs if r.quote == "2023")
    element = LlmElement("P2", "present", (value, year), "10", None, None)
    assert prepare_element(element, claim, graph, tenant_id=source.tenant_id)[1]
    current = next(r for r in refs if r.quote == "2024")
    assert not prepare_element(
        replace(element, evidence_refs=(value, current)), claim, graph, tenant_id=source.tenant_id
    )[1]
    assert not prepare_element(
        replace(element, evidence_refs=(value,)), claim, graph, tenant_id=source.tenant_id
    )[1]


def test_p1_row_quote_with_exact_normalized_value_is_narrowed():
    from proofops.application.tagging.pb2_table_evidence import prepare_element

    graph, source, claim = observation_case()
    element = LlmElement("P1", "present", claim.source_refs, "15", None, None)
    new, accepted = prepare_element(element, claim, graph, tenant_id=source.tenant_id)
    assert accepted and new.normalized_value == "15"


def test_v8_keeps_v7_proof_and_wrong_quantity_guard():
    from proofops.adapters.local.upstage_ocr_profile_v7 import claim_source_policy as old_policy
    from proofops.adapters.local.upstage_ocr_profile_v8 import cell_proof, claim_source_policy

    before = old_policy()
    for quantity, expected in [("15", "verified"), ("16", "unresolved"), ("151", "unresolved")]:
        graph, source, ref = fixture(quantity, raised=quantity == "151")
        assert (
            cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
            == expected
        )
    assert old_policy() == before and claim_source_policy() != before


def test_auxiliary_unit_does_not_erase_valid_track_or_become_a_fact():
    from proofops.application.tagging.pb2_preliminary import validate_preliminary
    from proofops.application.tagging.preliminary import validate_preliminary_table_sources
    from proofops.domain.errors import DomainValidationError

    graph, source, simple = observation_case()
    from proofops.application.claims import Claim

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
        None,
    )
    response = dict(
        claim_id=claim.claim_id,
        track="performance",
        safe_harbor_category=None,
        track_confidence=0.9,
        dimensions=dict(
            entity=None,
            metric=None,
            reporting_period=None,
            unit=dict(source_index=0, quote="tCO2eq"),
        ),
    )
    with pytest.raises(DomainValidationError):
        validate_preliminary_table_sources(claim, graph, response, tenant_id=source.tenant_id)
    result, aux = validate_preliminary(claim, graph, response, tenant_id=source.tenant_id)
    assert result.track.track == "performance"
    assert "unit" not in result.context.dimensions
    assert aux[0]["field"] == "unit" and aux[0]["credit"] == "none"
    response["dimensions"]["evidence_grade"] = None
    with pytest.raises(DomainValidationError):
        validate_preliminary(claim, graph, response, tenant_id=source.tenant_id)


def test_multiline_cell_recovers_only_selected_literal_and_not_whole_cell():
    from proofops.adapters.local.upstage_ocr_profile_v7 import cell_proof as legacy
    from proofops.adapters.local.upstage_ocr_profile_v8 import cell_proof
    from proofops.adapters.parsing.upstage_document import candidate_batch
    from proofops.application.ingest.graph_fusion import ParserProfile, fuse_candidates

    _, source, _ = fixture()
    profile = ParserProfile(str(uuid4()), parser_mode="upstage", table_claims_profile="pb1-v1")
    html = (
        "<table><tr><td>Metric</td><td>Unit</td></tr>"
        "<tr><td>Scope 1\nunreadable tail</td><td>tCO2eq</td></tr></table>"
    )
    batch, _ = candidate_batch(
        source,
        profile,
        (1,),
        [
            dict(
                model="document-parse-260128",
                usage=dict(pages=1, standard=[1]),
                elements=[
                    dict(
                        id=0,
                        page=1,
                        category="table",
                        content=dict(html=html),
                        coordinates=[
                            dict(x=0.02, y=0.15),
                            dict(x=0.85, y=0.15),
                            dict(x=0.85, y=0.45),
                            dict(x=0.02, y=0.45),
                        ],
                    )
                ],
            )
        ],
        mode="standard",
        config_hash=profile.config_hash(),
    )
    graph = fuse_candidates((batch,), tenant_id=source.tenant_id)
    table = next(b for b in graph.blocks if b.kind == "table")
    start = table.normalized_text.index("Scope 1")
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len("Scope 1"))
    assert (
        legacy(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )
    proof = cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "verified"
    assert proof["cell_proofs"][0]["recovered_selection"]
    assert proof["cell_proofs"][0]["source_ref"]["quote"] == "Scope 1"
    tail = table.source_ref(
        normalized_char_start=start, normalized_char_end=start + len("Scope 1\nunreadable tail")
    )
    assert (
        cell_proof(graph, source.content, [tail], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )


def test_frozen_cell_metadata_revalidates_after_json_and_rejects_tampering():
    from proofops.application.evidence.retrieval import freeze_packet
    from proofops.application.tagging.pb2_table_evidence import (
        augment_packet,
        validated_observation,
    )
    from proofops.domain.errors import DomainValidationError

    graph, source, claim = observation_case()
    packet = freeze_packet(
        augment_packet(
            dict(evidence_candidates=[], allowed_elements=["P1", "P2"]),
            claim,
            graph,
            tenant_id=source.tenant_id,
        )
    )
    data = packet.to_dict()
    assert validated_observation(data, claim, graph, tenant_id=source.tenant_id)
    data["table_observation_evidence"]["value"]["quote"] = "999"
    with pytest.raises(DomainValidationError):
        validated_observation(data, claim, graph, tenant_id=source.tenant_id)


def test_pb1_and_initial_pb2_policy_hashes_remain_readable():
    from proofops.application.analysis_profile import (
        V2_PB1_POLICY,
        V2_PB2_INITIAL_POLICY,
        V2_POLICY,
        policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        canonical_hash(V2_PB1_POLICY)
        == "a54e4d8ee846212aa69ed83430bc157837975c9507b1750093b0af9409cab2c1"
    )
    assert (
        canonical_hash(V2_PB2_INITIAL_POLICY)
        == "de8e156a804c27f5ec9197332273e1245f14cd92e2a6e113c923dfb563b9aef7"
    )
    for policy in (V2_PB1_POLICY, V2_PB2_INITIAL_POLICY):
        assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(policy)) == policy
    assert canonical_hash(V2_POLICY) != canonical_hash(V2_PB2_INITIAL_POLICY)


def test_fact_field_fix_is_scoped_to_tables_and_old_policy_is_preserved():
    from proofops.application.analysis_profile import V2_PB2_ALL_CLAIMS_POLICY, V2_POLICY
    from proofops.application.tagging.pb2_preliminary import enabled
    from proofops.domain.provenance import canonical_hash

    graph, _, claim = observation_case()
    assert enabled(claim, graph, V2_POLICY)
    prose = replace(graph, blocks=tuple(replace(b, kind="paragraph") for b in graph.blocks))
    assert not enabled(claim, prose, V2_POLICY)
    assert enabled(claim, prose, V2_PB2_ALL_CLAIMS_POLICY)
    assert (
        canonical_hash(V2_PB2_ALL_CLAIMS_POLICY)
        == "d2bb24cc356e25029b384a5fe926866594e002b67a128c8a442f8ff498336f15"
    )


def test_structural_relation_skip_is_only_verified_p1_p2_cells():
    from copy import deepcopy

    from proofops.application.tagging.pb2_table_evidence import (
        augment_packet,
        structural_relation_ids,
    )
    from proofops.domain.errors import DomainValidationError

    graph, source, claim = observation_case()
    data = augment_packet(
        dict(evidence_candidates=[], allowed_elements=["P1", "P2", "P3"]),
        claim,
        graph,
        tenant_id=source.tenant_id,
    )
    ids = structural_relation_ids(data, claim, graph, tenant_id=source.tenant_id)
    assert ids and claim.source_refs[0].source_id not in ids
    changed = deepcopy(data)
    changed["evidence_candidates"][0]["allowed_elements"].append("P3")
    assert changed["evidence_candidates"][0]["source_id"] not in structural_relation_ids(
        changed, claim, graph, tenant_id=source.tenant_id
    )
    data["table_observation_evidence"]["unit"]["quote"] = "forged"
    with pytest.raises(DomainValidationError):
        structural_relation_ids(data, claim, graph, tenant_id=source.tenant_id)
