from copy import deepcopy
from dataclasses import replace

import pytest
from proofops.domain.values import LlmElement

from tests.acceptance.test_binding import corpus
from tests.unit.test_pb2_table_evidence import observation_case


def test_response_identity_is_owned_by_dispatch_and_legacy_is_unchanged():
    from proofops.application.tagging.k4_contract import RESPONSE_POLICY, bind_response

    request = dict(claim_id="trusted", packet_sha256="packet", replicate_id=2)
    payload = dict(claim_id="model-typo", packet_sha256="wrong", replicate_id=1, elements=[])
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="K4_MODEL_IDENTITY_FIELDS_PROHIBITED"):
        bind_response(payload, request, policy=RESPONSE_POLICY)
    assert bind_response(dict(elements=[]), request, policy=RESPONSE_POLICY) == request | dict(
        elements=[]
    )
    assert payload == before
    with pytest.raises(ValueError):
        bind_response(payload, request, policy=RESPONSE_POLICY | dict(profile="forged"))


def test_connected_clause_gets_complete_literal_context_without_new_vote():
    from proofops.application.ingest.j7_split import goal_requires_retag, sentence_context

    graph, claim = prose_case()
    context = sentence_context(claim, graph)
    assert context["text"] == "효율을 설계에 반영하고 에너지 절감 기술 개발에 선제적으로 투자"
    assert context["rule_credit"] is False
    assert goal_requires_retag(claim, graph)
    # Its neighbouring bullet's future goal must not leak into this sentence.
    assert "2030" not in context["text"]


def prose_case():
    from tests.acceptance.test_binding import span

    graph, claim, _ = corpus()
    block = graph.blocks[0]
    text = (
        "효율을 설계에 반영하고 에너지 절감 기술 개발에 선제적으로 투자"
        "\n• 2030년까지 전환할 목표입니다."
    )
    candidate = replace(
        block.candidates[0],
        kind="paragraph",
        source=replace(block.candidates[0].source, raw_text=text, char_end=len(text)),
    )
    block = replace(block, kind="paragraph", candidates=(candidate,), winner=0)
    graph = replace(
        graph,
        blocks=(block,),
        edges=(),
        candidates=tuple(replace(batch, blocks=(candidate,)) for batch in graph.candidates),
    )
    ref = span(block.source_ref(), "에너지 절감 기술 개발에 선제적으로 투자")
    return graph, replace(claim, quote=ref.quote, source_refs=(ref,))


def test_p1_recovers_two_selected_local_quantities_without_inventing_votes():
    from proofops.application.tagging.k4_contract import recover_selected_quantities

    from tests.acceptance.test_binding import span

    graph, claim, _ = corpus()
    block = graph.blocks[0]
    text = "약 2,944 tCO₂를 저장, 연간 약 156 tCO₂ 흡수"
    # Use the canonical fixture's immutable graph machinery with fresh literal text.
    candidate = replace(
        block.candidates[block.winner],
        source=replace(block.candidates[block.winner].source, raw_text=text, char_end=len(text)),
    )
    block = replace(block, candidates=(candidate,), winner=0)
    graph = replace(
        graph,
        blocks=(block,),
        edges=(),
        candidates=tuple(replace(batch, blocks=(candidate,)) for batch in graph.candidates),
    )
    row = block.source_ref()
    claim = replace(claim, quote=text, source_refs=(row,), source_quality="verified")
    refs = (span(row, "약 2,944 tCO₂를 저장"), span(row, "연간 약 156 tCO₂ 흡수"))
    element = LlmElement("P1", "present", refs, None, None, None)
    new, checked = recover_selected_quantities(
        element, list(refs), claim, graph, tenant_id=graph.tenant_id
    )
    assert new.normalized_value == text
    assert checked[-1].quote == text
    unknown = replace(element, state="unknown", evidence_refs=())
    assert (
        recover_selected_quantities(unknown, [], claim, graph, tenant_id=graph.tenant_id)[0]
        == unknown
    )


def test_estimate_category_requires_local_explicit_calculation_marker():
    from dataclasses import asdict

    from proofops.application.tagging.k4_contract import estimate_evidence

    graph, source, claim = observation_case()
    data = dict(
        tenant_id=source.tenant_id,
        document_version_id=graph.document_version_id,
        track="performance",
        safe_harbor_category="emissions_estimate",
        claim_source_refs=[asdict(claim.source_refs[0])],
    )
    assert estimate_evidence(data, graph) == []
