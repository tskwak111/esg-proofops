import pytest
from proofops.application.tagging.semantic_admission import guard_element

from tests.unit.test_q1_structural import tagged


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("G3", "2022년"),
        ("G4", "Scope 1, 2"),
        ("G4", "대기 및 수질 오염물질 원단위 배출량"),
        ("M4", "K-택소노미 등 녹색 분류체계와의 정합성을 확보하여 성과를 관리하고 있습니다."),
        ("M4", "감축 수단 확보를 지속 추진하고 있습니다."),
    ],
)
def test_k10_incomplete_literal_elements_are_reviewed(eid, quote):
    from proofops.application.tagging.k10_contract import SEMANTIC_POLICY

    raw = tagged(eid, quote)
    result = guard_element(raw, policy=SEMANTIC_POLICY)
    assert result.state == "unknown"
    assert result.evidence_refs == raw.evidence_refs
    assert raw.state == "present"
    for state in ("unknown", "conflict"):
        assert guard_element(tagged(eid, quote, state), policy=SEMANTIC_POLICY).state == state


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("G3", "2022년 배출량 100 tCO2e"),
        ("G4", "국내 전 생산 사업장의 Scope 1, 2"),
        ("M4", "2023년 2월 CCS 사업화 추진반을 구성했습니다."),
        ("M4", "문헌조사 및 현장실사를 실시하여 서식 현황을 파악했습니다."),
        ("M1", "총괄임원·대표이사·이사회로 이어지는 정기 보고체계"),
    ],
)
def test_k10_does_not_remove_sufficient_literal_candidates(eid, quote):
    from proofops.application.tagging.k10_contract import SEMANTIC_POLICY

    assert guard_element(tagged(eid, quote), policy=SEMANTIC_POLICY).state == "present"


def test_k10_new_pin_preserves_v11_and_three_replicas():
    from proofops.application.analysis_profile import (
        FINALS_I10_POLICY,
        FINALS_K10_POLICY,
        policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        canonical_hash(FINALS_I10_POLICY)
        == "bfdd5a95747fd3e3a0511419597c9f089406d6923bec43b0bc5e5790e9493cd6"
    )
    for policy in (FINALS_I10_POLICY, FINALS_K10_POLICY):
        assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(policy)) == policy


def test_k10_renderer_fits_contextless_evidence_without_raising_provider_limit(tmp_path):
    import json

    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.application.tagging.finals_i4 import elements_k4
    from proofops.application.tagging.k10_contract import elements

    schema = dict(type="object", properties={}, additionalProperties=False)
    classification = dict(track="management", safe_harbor_category=None)
    before = elements_k4(schema, classification)
    after = elements(schema, classification)
    evidence = json.dumps({"evidence_catalog": {"e0": {"quote": "x" * 9000}}})
    probe = OpenAIProbe("fake", tmp_path / "wire.sqlite3")
    with pytest.raises(ValueError, match="PROBE_REQUEST_TOO_LARGE"):
        probe.request_body(before, evidence, request_id="before", json_mode=True)
    result = probe.request_body(after, evidence, request_id="after", json_mode=True)
    assert result["messages"][1]["content"] == evidence
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) <= 16384
    assert "unknown/conflict/unreadable" in after and "credited_from=null" in after


def test_k10_v2_covers_original_scope_emissions_citation_and_retains_v1():
    from proofops.application.analysis_profile import (
        FINALS_K10_POLICY,
        FINALS_K10_V2_POLICY,
        policy_for,
        publication_policy_for,
    )
    from proofops.application.tagging.k10_contract import SEMANTIC_POLICY, SEMANTIC_V2_POLICY
    from proofops.domain.provenance import canonical_hash

    quote = "Scope 1 및 Scope 2 배출량"
    assert guard_element(tagged("G4", quote), policy=SEMANTIC_POLICY).state == "present"
    assert guard_element(tagged("G4", quote), policy=SEMANTIC_V2_POLICY).state == "unknown"
    assert (
        guard_element(tagged("G4", "국내 전 사업장의 " + quote), policy=SEMANTIC_V2_POLICY).state
        == "present"
    )
    assert (
        canonical_hash(FINALS_K10_POLICY)
        == "8cd3b260f15eafa139f5a053e84e531de5a696a638a81fe6b89e40944dbe4d3b"
    )
    for policy in (FINALS_K10_POLICY, FINALS_K10_V2_POLICY):
        digest = canonical_hash(policy)
        assert policy_for("finals-unattended-v2", pinned_hash=digest) == policy
        assert publication_policy_for("finals-unattended-v2", pinned_hash=digest) == policy
