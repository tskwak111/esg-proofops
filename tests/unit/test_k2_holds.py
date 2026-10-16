"""K2: partial display recovery and exact local facts, never source promotion."""

from copy import deepcopy
from dataclasses import replace

import pytest
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.quality import hold_projection

from tests.acceptance.test_binding import corpus, span, tags
from tests.acceptance.test_tagging import execute, setup
from tests.integration.test_glyph_display_text import fixture_catalog


def test_ambiguous_dimension_does_not_discard_header():
    from proofops.application.tagging.k2_recovery import POLICY

    graph, claim, _ = corpus()
    catalog = fixture_catalog(graph, {})
    packet = dict(untrusted_document_data=dict(sources=[dict(text="RE100 이행 RE100 분석")]))
    packet["display_text"] = dict(sources=[dict(deleted_offsets=[])])
    packet["preliminary_recovery_policy"] = POLICY
    response = dict(track="management", dimensions=dict(metric=dict(source_index=0, quote="RE100")))
    before = deepcopy(response)
    restored = catalog.restore_preliminary(response, packet)
    assert restored["track"] == "management"
    assert restored["dimensions"]["metric"] is None
    assert restored["dimension_restore_errors"] == {"metric": "DISPLAY_QUOTE_UNRESOLVED"}
    assert response == before
    packet.pop("preliminary_recovery_policy")
    with pytest.raises(ValueError, match="display quote"):
        catalog.restore_preliminary(response, packet)


def test_unique_whitespace_recovery_keeps_raw_offsets():
    from proofops.application.tagging.k2_recovery import POLICY

    graph, _, _ = corpus()
    catalog = fixture_catalog(graph, {})
    packet = dict(
        untrusted_document_data=dict(sources=[dict(text="• 네 이버는 기후 위험을 관리한다")]),
        display_text=dict(sources=[dict(deleted_offsets=[])]),
        preliminary_recovery_policy=POLICY,
    )
    response = dict(dimensions=dict(entity=dict(source_index=0, quote="네이버")))
    restored = catalog.restore_preliminary(response, packet)
    assert restored["dimensions"]["entity"] == dict(source_index=0, quote="네 이버", start=2, end=6)


@pytest.mark.parametrize("null_value", [False, True])
def test_verified_local_numeric_ignores_unresolved_optional_axes(tmp_path, null_value):
    from proofops.application.evidence.binding import ClaimContext, local_relation_tags
    from proofops.application.tagging.k2_recovery import POLICY

    inputs = setup(tmp_path)
    context = ClaimContext(inputs["context"].claim, dict(facility=None, metric=None))
    inputs.update(context=context, relation_tags=local_relation_tags(context))
    if null_value:
        inputs["invoke"].changes = {i: dict(element=dict(normalized_value=None)) for i in (1, 2, 3)}
    old = execute(inputs)
    assert all(r.guarded.elements[0].state == "unknown" for r in old)
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    data["local_element_recovery_policy"] = POLICY
    inputs["packet"] = freeze_packet(data)
    new = execute(inputs)
    assert all(r.guarded.elements[0].state == "present" for r in new)
    assert all(r.guarded.elements[0].normalized_value == "40%" for r in new)


def test_local_recovery_cannot_promote_unverified_or_fabricated_value(tmp_path):
    from proofops.application.tagging.k2_recovery import POLICY

    inputs = setup(tmp_path)
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    data["local_element_recovery_policy"] = POLICY
    inputs["packet"] = freeze_packet(data)
    inputs["invoke"].changes = {i: dict(element=dict(normalized_value="100%")) for i in (1, 2, 3)}
    assert all(r.guarded.elements[0].state == "unknown" for r in execute(inputs))
    inputs["context"] = replace(
        inputs["context"], claim=replace(inputs["context"].claim, source_quality="unverified")
    )
    with pytest.raises(ValueError):
        execute(inputs)


def item(*, present=False, code=None):
    return dict(
        source_status=dict(status="verified"),
        frozen_packet=dict(track="goal"),
        preliminary_records=[dict(stable_reason=dict(error_code=code))] if code else [],
        tag_runs=[],
        provisional_grade=dict(
            evidence_grade=None,
            reason="blocked_evidence",
            gap_ids=[],
            grade_range=dict(floor="E0", ceiling="E3", rule_gap=True),
            elements=[dict(element_id="G1", state="present")] if present else [],
            unresolved_elements=["G2", "G3", "G5", "G6"],
        ),
    )


def test_hold_reason_distinguishes_display_and_unknown_even_with_present():
    for value in (item(code="DISPLAY_QUOTE_UNRESOLVED"), item(present=True)):
        new = hold_projection(value, profile="k2-v1")
        assert new["hold_reasons"]
        assert "근거 없음" not in new["hold_reasons"]
        assert "문서 전체의 근거 부재" in new["evidence_note"]
    assert (
        "원문 위치 확인 필요"
        in hold_projection(item(code="DISPLAY_QUOTE_UNRESOLVED"), profile="k2-v1")["hold_reasons"]
    )
    assert (
        "미확인 요소: G2, G3, G5, G6"
        in hold_projection(item(present=True), profile="k2-v1")["hold_reasons"]
    )


def test_historical_hold_and_policy_pin_remain_available():
    from proofops.application.analysis_profile import FINALS_I1_POLICY, FINALS_K2_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(FINALS_I1_POLICY) != canonical_hash(FINALS_K2_POLICY)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I1_POLICY))
        == FINALS_I1_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_K2_POLICY))
        == FINALS_K2_POLICY
    )
    assert "근거 없음" in hold_projection(item(), profile="dec24-v1")["hold_reasons"]


def test_k2_pin_is_usable_for_new_runs_and_default_is_integrated():
    from proofops.application.analysis_profile import (
        FINALS_I3_POLICY,
        FINALS_K2_POLICY,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        publication_policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I3_POLICY))
        == FINALS_I3_POLICY
    )
    assert (
        publication_policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_K2_POLICY))
        == FINALS_K2_POLICY
    )


def test_model_cannot_inject_restoration_diagnostics():
    graph, _, _ = corpus()
    catalog = fixture_catalog(graph, {})
    packet = dict(untrusted_document_data=dict(sources=[]), display_text=dict(sources=[]))
    with pytest.raises(ValueError):
        catalog.restore_preliminary(dict(dimensions={}, dimension_restore_errors={}), packet)


@pytest.mark.parametrize("case", ["forged", "other_source", "contradiction", "bad_period"])
def test_new_local_identity_preserves_asserted_role_validation(case):
    from proofops.application.evidence.binding import ClaimContext, accept_binding

    from tests.acceptance.test_rules import pack

    graph, claim, refs = corpus()
    dimensions = {}
    expected = "rejected"
    role = "entity"
    if case == "forged":
        actual = replace(span(refs[0], "회사A"), quote="forged")
    elif case == "other_source":
        actual = span(refs[1], "회사A")
    elif case == "contradiction":
        dimensions = dict(entity=span(refs[0], "회사A"))
        actual = span(refs[0], "제품A")
    else:
        role, actual, expected = "reporting_period", span(refs[0], "함유비율"), "undetermined"
    assert (
        accept_binding(
            ClaimContext(claim, dimensions),
            span(refs[0], "40%"),
            {role: actual},
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="P1",
            local_value_identity=True,
        )
        == expected
    )


@pytest.mark.parametrize("element_id", ["P1", "G1", "G2", "M1", "G4", "M2"])
def test_new_local_identity_does_not_fill_cross_source_null_axes(element_id):
    from proofops.application.evidence.binding import ClaimContext, accept_binding

    from tests.acceptance.test_rules import pack

    graph, claim, refs = corpus()
    dimensions = tags(refs[0]) | dict(facility=None)
    assert (
        accept_binding(
            ClaimContext(claim, dimensions),
            span(refs[1], "40%"),
            tags(refs[1]),
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id=element_id,
            local_value_identity=True,
        )
        != "accepted"
    )
