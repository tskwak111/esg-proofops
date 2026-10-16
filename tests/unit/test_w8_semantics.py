"""W8 admission regressions; no model, absence inference or grade overrides."""

from dataclasses import replace

import pytest
from proofops.domain.values import LlmElement

from tests.acceptance.test_binding import corpus


def element(eid, quote, state="present"):
    ref = corpus()[2][0]
    ref = replace(ref, quote=quote, char_start=0, char_end=len(quote))
    return LlmElement(eid, state, (ref,), None, None, None)


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("M1", "협력회사 및 지역사회의 환경안전보건 개선 적극 지원"),
        ("M1", "환경 개선을 위해 노력하고 있습니다."),
        ("M1", "환경 개선을 추진할 것입니다."),
        ("G6", "재생에너지 전환을 선언했습니다"),
        ("M2", "사업장별 영향을 선제적으로 파악·점검하고 있습니다."),
    ],
)
def test_intent_and_ambiguous_boundary_are_unresolved(eid, quote):
    from proofops.application.tagging.semantic_admission import guard_element

    raw = element(eid, quote)
    guarded = guard_element(raw)
    assert guarded.state == "unknown"
    assert guarded.evidence_refs == raw.evidence_refs
    assert guarded.reason_code.startswith("W8_")
    assert raw.state == "present"


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("M1", "전사 탄소 통합 관리 시스템(Net-Zero Portal)을 활용하여 관리하고 있습니다."),
        ("M1", "전사 차원의 관리·운영 체계를 구축하고 있습니다."),
        ("M1", "ISO 14001 인증을 통해 환경 개선을 적극 지원합니다."),
        ("M1", "주기적으로 모니터링하며"),
        ("G6", "자체발전과 PPA 중심으로 재생에너지 전환을 추진할 계획입니다."),
        ("G6", "태양광 설비 설치를 통해 전환할 것을 선언했습니다."),
        ("M2", "국내 모든 사업장별 영향을 점검합니다."),
        ("M2", "여수 사업장에 적용합니다."),
        ("M2", "글로벌 15개 사업장에서 인증 완료"),
    ],
)
def test_concrete_means_plans_and_boundaries_survive(eid, quote):
    from proofops.application.tagging.semantic_admission import guard_element

    raw = element(eid, quote)
    assert guard_element(raw) == raw


@pytest.mark.parametrize("state", ["unknown", "conflict", "absent", "not_applicable"])
def test_non_present_votes_are_never_reinterpreted(state):
    from proofops.application.tagging.semantic_admission import guard_element

    raw = element("M1", "적극 지원", state)
    assert guard_element(raw) == raw


def test_scope3_item_uses_only_its_own_table_not_other_table_or_tenant():
    from dataclasses import asdict
    from uuid import uuid4

    from proofops.application.tagging.semantic_admission import estimate_refs

    from tests.acceptance.test_citations import snapshot

    text = "Scope 3\n총 배출량 tCO2eq 100\n자본재 tCO2eq 10"
    graph, whole = snapshot(text)
    block = replace(graph.blocks[0], kind="table")
    graph = replace(graph, blocks=(block,))
    start = text.index("자본재")
    row = replace(whole, quote=text[start:], char_start=start)
    data = dict(
        track="performance",
        safe_harbor_category=None,
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        claim_source_refs=[asdict(row)],
        table_observation_evidence={"observation": "saved"},
    )
    assert estimate_refs(data, graph) == data["claim_source_refs"]
    assert not estimate_refs(data)
    assert not estimate_refs(data | dict(tenant_id=str(uuid4())), graph)
    assert not estimate_refs(data | dict(document_version_id=str(uuid4())), graph)
    foreign = asdict(replace(row, source_id=str(uuid4())))
    assert not estimate_refs(data | dict(claim_source_refs=[foreign]), graph)
    assert not estimate_refs(data | dict(track="management"), graph)
    mixed, _ = snapshot("Scope 1\nScope 3\n자본재 tCO2eq 10")
    mixed = replace(mixed, blocks=(replace(mixed.blocks[0], kind="table"),))
    assert not estimate_refs(data, mixed)


def test_new_policy_keeps_old_pins_and_prompt_bytes():
    from proofops.application.analysis_profile import (
        FINALS_I2_POLICY,
        FINALS_I3_POLICY,
        FINALS_I4_POLICY,
        K1_POLICY,
        V2_PRE_W8_POLICY,
        policy_for,
    )
    from proofops.application.analysis_profile import (
        FINALS_I9_POLICY as V2_POLICY,
    )
    from proofops.application.tagging.quality import ELEMENT_DEFINITIONS
    from proofops.application.tagging.semantic_admission import DEFINITIONS, POLICY_HASH
    from proofops.domain.provenance import canonical_hash

    from evaluation.local_upstage_pilot import live_tagging_settings

    assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PRE_W8_POLICY)) == (
        V2_PRE_W8_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I2_POLICY))[
            "semantic_admission_sha256"
        ]
        == POLICY_HASH
    )
    assert FINALS_I3_POLICY["semantic_admission_sha256"] == K1_POLICY["semantic_admission_sha256"]
    assert V2_POLICY["semantic_admission_sha256"] == FINALS_I4_POLICY["semantic_admission_sha256"]
    old = live_tagging_settings(10, model_id="gpt-6-luna", element_definition_profile="qi1-v1")
    new = live_tagging_settings(10, model_id="gpt-6-luna", element_definition_profile="w8-v1")
    assert ELEMENT_DEFINITIONS in old["tagging_settings"]["system_prompt"]
    assert DEFINITIONS not in old["tagging_settings"]["system_prompt"]
    assert DEFINITIONS in new["tagging_settings"]["system_prompt"]
    assert old["tagging_settings"] != new["tagging_settings"]
