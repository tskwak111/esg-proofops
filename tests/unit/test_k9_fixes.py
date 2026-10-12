"""K9 source attribution and track disambiguation; no model votes fabricated."""

import pytest
from proofops.application.evidence.binding import ClaimContext, accept_binding, local_relation_tags

from tests.acceptance.test_binding import span
from tests.acceptance.test_rules import pack
from tests.unit.test_k5_context import case

TEXT = "가상기업은 2023년 2월 CCS 사업화 추진반을 구성하여 사업을 추진합니다."


def check(
    *, text=TEXT, citation=None, dimensions=None, policy=None, element_id="M4", quality="verified"
):
    graph, claim = case([text], (0, text), quality=quality)
    full = claim.source_refs[0]
    context = ClaimContext(
        claim,
        dimensions
        if dimensions is not None
        else {
            "entity": span(full, "가상기업"),
            "metric": None,
            "reporting_period": None,
            "scope": None,
        },
    )
    ref = span(full, citation) if citation else full
    relations = next(iter(local_relation_tags(context).values()))
    return accept_binding(
        context,
        ref,
        relations,
        original=graph,
        tenant_id=graph.tenant_id,
        rulepack=pack(),
        element_id=element_id,
        local_value_identity=True,
        local_binding_policy=policy,
    )


def test_k9_m4_local_actor_and_event_date_do_not_require_ghg_scope():
    from proofops.application.tagging.k9_contract import BINDING_POLICY

    assert check(policy=BINDING_POLICY) == "accepted"
    assert check() == "undetermined"  # old pins retain the old guard
    assert check(policy=BINDING_POLICY, element_id="M2") == "undetermined"
    assert check(policy=BINDING_POLICY, element_id="G4") == "undetermined"


@pytest.mark.parametrize(
    "change", ["no_actor", "no_date", "partial", "other_sentence", "unverified", "tampered"]
)
def test_k9_m4_does_not_borrow_missing_roles_or_source_authority(change):
    from proofops.application.tagging.k9_contract import BINDING_POLICY

    kwargs = dict(policy=BINDING_POLICY)
    if change == "no_actor":
        kwargs["dimensions"] = {"entity": None, "scope": None}
    elif change == "no_date":
        kwargs["text"] = TEXT.replace("2023년 2월 ", "")
    elif change == "partial":
        kwargs["citation"] = "2023년 2월 CCS 사업화 추진반을 구성"
    elif change == "other_sentence":
        kwargs["text"] = "가상기업은 CCS를 추진합니다. 2023년 2월 추진반을 구성했습니다."
    elif change == "unverified":
        kwargs["quality"] = "unverified"
    else:
        kwargs["policy"] = BINDING_POLICY | dict(profile="forged")
        with pytest.raises(ValueError, match="K9_BINDING_POLICY_MISMATCH"):
            check(**kwargs)
        return
    assert check(**kwargs) == "undetermined"


def test_k9_asserted_wrong_entity_is_still_rejected():
    from proofops.application.tagging.k9_contract import BINDING_POLICY

    graph, claim = case([TEXT], (0, TEXT))
    full = claim.source_refs[0]
    context = ClaimContext(claim, {"entity": span(full, "가상기업"), "scope": None})
    actual = {"entity": span(full, "사업"), "scope": None}
    assert (
        accept_binding(
            context,
            full,
            actual,
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="M4",
            local_value_identity=True,
            local_binding_policy=BINDING_POLICY,
        )
        == "rejected"
    )


def test_k9_policy_and_v7_hash_remain_readable_after_adoption():
    from proofops.application.analysis_profile import (
        FINALS_I7_POLICY,
        FINALS_K9_POLICY,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        canonical_hash(FINALS_I7_POLICY)
        == "0d10ccb21b953f5c29846438fb72538baf50ebd280c45d89b5adbf727c6c9efb"
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I7_POLICY))
        == FINALS_I7_POLICY
    )
    for policy in (FINALS_I7_POLICY, FINALS_K9_POLICY):
        assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(policy)) == policy
        assert (
            publication_policy_for("finals-unattended-v2", pinned_hash=canonical_hash(policy))
            == policy
        )


def test_k9_prompt_settings_and_identity_free_wire_share_guidance():
    from proofops.application.tagging.k9_contract import PRELIMINARY, PROFILE, preliminary

    from evaluation.local_upstage_pilot import live_tagging_settings

    settings = live_tagging_settings(
        600, prompt_profile=PROFILE, preliminary_pb1=True, compact_element_wire=True
    )
    assert settings["preliminary_settings"]["system_prompt"] == PRELIMINARY
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    wire = preliminary(schema)
    assert "복사냉방" in wire and "정량" in wire and "management" in wire
    assert "PUE" in wire and "performance" in wire
    assert "Never rewrite" in wire


def test_k9_targeted_renderer_keeps_unaffected_v7_wire():
    from proofops.application.tagging.finals_i4 import preliminary_k4
    from proofops.application.tagging.k9_contract import element_guidance_target, preliminary

    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    board = "현대자동차의 이사회는 환경투자 안건을 검토·승인합니다."
    assert preliminary(schema, quote=board) == preliminary_k4(schema)
    assert not element_guidance_target(board)
    assert "복사냉방" in preliminary(schema, quote="복사냉방·수축열·고효율 조명 시스템 적용")
    assert element_guidance_target("또한 CEO가 참석하는 ESG경영위원회에서 기후 안건을 검토한다.")
    assert not element_guidance_target("SBTi 가이드라인에 따라 목표를 수립했습니다.")


def test_k9_g6_and_m5_local_identity_without_borrowing_scope():
    from proofops.application.tagging.k9_contract import BINDING_POLICY

    for element in ("G6", "M5"):
        assert check(policy=BINDING_POLICY, element_id=element) == "accepted"
        assert check(element_id=element) == "undetermined"


def test_k9_dated_m5_guidance_preserves_historical_renderers_and_pins():
    from proofops.application.analysis_profile import (
        FINALS_K9_INITIAL_POLICY,
        FINALS_K9_POLICY,
        FINALS_K9_V2_POLICY,
        FINALS_K9_V3_POLICY,
        FINALS_K9_V4_POLICY,
        policy_for,
    )
    from proofops.application.tagging.k9_contract import (
        BINDING_POLICY,
        BINDING_V3_POLICY,
        BINDING_V4_POLICY,
        element_guidance_for,
    )
    from proofops.domain.provenance import canonical_hash

    quote = "가상기업은 2022년부터 탄소관리위원회를 운영하며 실행 과제를 추진합니다."
    assert "M5는 M4와 독립적" in element_guidance_for(BINDING_POLICY, quote)
    assert "M5는 M4와 독립적" not in element_guidance_for(BINDING_V4_POLICY, quote)
    board = "이사회는 환경 투자 안건을 검토·승인합니다."
    assert element_guidance_for(BINDING_V4_POLICY, board) == ""
    assert element_guidance_for(BINDING_POLICY, board) == ""
    assert element_guidance_for(BINDING_V3_POLICY, board)
    assert (
        canonical_hash(FINALS_K9_V4_POLICY)
        == "4dab6ab751144f07152f1557ea51584585394f57102ecfb6c0f8e28d34842a55"
    )
    for policy in (
        FINALS_K9_INITIAL_POLICY,
        FINALS_K9_V2_POLICY,
        FINALS_K9_V3_POLICY,
        FINALS_K9_V4_POLICY,
        FINALS_K9_POLICY,
    ):
        assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(policy)) == policy


def test_k9_prompt_requires_separately_pinned_preflight_authority():
    from dataclasses import asdict, replace

    from proofops.application.tagging.k9_contract import PRELIMINARY
    from proofops.domain.provenance import canonical_hash

    from tests.integration.test_upstage_tagger_preflight import check, configured

    args = configured()
    args["settings"] = replace(
        args["settings"],
        model_profile="upstage-preliminary-source-quotes-pb1-compact-v1",
        system_prompt=PRELIMINARY,
    )
    assert not check(**args).ready
    args["binding"]["tagging_settings_sha256"] = canonical_hash(asdict(args["settings"]))
    assert check(**args).ready


def test_k9_g4_requires_verified_scope_definition_and_local_facility():
    from proofops.application.tagging.k9_contract import (
        BINDING_POLICY,
        g4_complete,
        scope_definition_refs,
    )
    from proofops.domain.values import LlmElement

    text = (
        "감축 방안은 직접 감축(Scope 1)과 간접 감축(Scope 2)입니다. "
        "직접 감축은 가상기업의 공장A를 수소로 전환할 계획입니다."
    )
    quote = "직접 감축은 가상기업의 공장A를 수소로 전환할 계획입니다."
    graph, claim = case([text], (0, quote))
    full = claim.source_refs[0]
    context = ClaimContext(claim, {"facility": span(full, "공장A"), "scope": None})
    (definition,) = scope_definition_refs(claim, graph)
    element = LlmElement("G4", "present", (span(full, "공장A"), definition), None, None, None)
    assert g4_complete(element, context, graph)
    assert (
        accept_binding(
            context,
            definition,
            None,
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="G4",
            local_binding_policy=BINDING_POLICY,
        )
        == "accepted"
    )
    from dataclasses import replace

    assert not g4_complete(replace(element, evidence_refs=(span(full, "공장A"),)), context, graph)
    assert not g4_complete(replace(element, evidence_refs=(definition,)), context, graph)
    other = replace(
        definition,
        quote="간접 감축(Scope 2)",
        char_start=text.index("간접 감축"),
        char_end=text.index("간접 감축") + len("간접 감축(Scope 2)"),
    )
    assert not g4_complete(
        replace(element, evidence_refs=(span(full, "공장A"), other)), context, graph
    )
    unresolved = ClaimContext(claim, {"facility": None, "scope": None})
    assert g4_complete(element, unresolved, graph)
    from proofops.application.tagging.k9_contract import BINDING_V1_POLICY

    assert not g4_complete(element, unresolved, graph, policy=BINDING_V1_POLICY)
    conflicting = ClaimContext(claim, {"facility": span(full, "공장A"), "scope": other})
    assert (
        accept_binding(
            conflicting,
            definition,
            None,
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="G4",
            local_binding_policy=BINDING_POLICY,
        )
        == "rejected"
    )


@pytest.mark.parametrize("separator", ["\n\n", "\n• "])
def test_k9_scope_definition_cannot_cross_paragraphs_or_bullets(separator):
    from proofops.application.tagging.k9_contract import scope_definition_refs

    quote = "직접 감축은 가상기업의 공장A를 수소로 전환할 계획입니다."
    text = "직접 감축(Scope 1)을 정의합니다." + separator + quote
    graph, claim = case([text], (0, quote))
    assert scope_definition_refs(claim, graph) == ()


def test_k9_scope_adapter_rejects_foreign_claim_before_source_reader():
    from dataclasses import replace

    from proofops.adapters.local.k9_scope_sources import scope_graph
    from proofops.application.analysis_profile import FINALS_K9_POLICY

    graph, claim = case([TEXT], (0, TEXT))
    from hashlib import sha256

    source = b"synthetic source for identity check only"
    graph = replace(graph, source_sha256=sha256(source).hexdigest())
    claim = replace(claim, source_sha256=graph.source_sha256, tenant_id=graph.document_version_id)
    # A matching source hash does not permit a foreign claim to reach the reader.
    with pytest.raises(ValueError, match="K9_SCOPE_SOURCE_MISMATCH"):
        scope_graph(
            graph,
            source,
            [claim],
            tenant_id=graph.tenant_id,
            run_id=claim.claim_id,
            policy=FINALS_K9_POLICY,
        )
