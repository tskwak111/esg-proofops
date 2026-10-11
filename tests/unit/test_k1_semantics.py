"""K1 negative admission and literal boundary regressions; no paid calls."""

from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from proofops.application.tagging.semantic_admission import estimate_refs, guard_element

from tests.acceptance.test_citations import snapshot
from tests.unit.test_w8_semantics import element


def test_scope3_exclusion_description_does_not_hide_estimate_items():
    from proofops.application.tagging.k1_semantics import POLICY

    text = (
        "총 배출량(Scope 3)\t천tCO2eq\t100\n"
        "Scope 1 & 2에 포함되지 않은 연료 및 에너지 관련 활동3\t천tCO2eq\t10\n"
        "출장6\t천tCO2eq\t23.5"
    )
    graph, whole = snapshot(text)
    graph = replace(graph, blocks=(replace(graph.blocks[0], kind="table"),))
    start = text.index("출장")
    row = replace(whole, quote=text[start:], char_start=start)
    data = dict(
        track="performance",
        safe_harbor_category=None,
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        claim_source_refs=[asdict(row)],
        table_observation_evidence={"observation": "saved"},
    )
    assert not estimate_refs(data, graph)  # historical W8 remains exact
    assert estimate_refs(data, graph, policy=POLICY) == data["claim_source_refs"]
    mixed, _ = snapshot(text + "\nScope 1\t천tCO2eq\t20")
    mixed = replace(mixed, blocks=(replace(mixed.blocks[0], kind="table"),))
    assert not estimate_refs(data, mixed, policy=POLICY)
    assert not estimate_refs(data | dict(tenant_id="foreign"), graph, policy=POLICY)
    assert not estimate_refs(data | dict(document_version_id="foreign"), graph, policy=POLICY)
    bad = asdict(replace(row, source_id=str(uuid4())))
    assert not estimate_refs(data | dict(claim_source_refs=[bad]), graph, policy=POLICY)


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("M1", "PUE(전력사용효율지수)"),
        ("M2", "기아는 RE100 이행을 위해"),
        ("P1", "PUE(전력사용효율지수) 1.1x 유지"),
    ],
)
def test_metric_range_and_actor_purpose_do_not_supply_missing_semantics(eid, quote):
    from proofops.application.tagging.k1_semantics import POLICY

    raw = element(eid, quote)
    assert guard_element(raw) == raw
    new = guard_element(raw, policy=POLICY)
    assert new.state == "unknown" and new.reason_code.startswith("K1_")
    assert new.evidence_refs == raw.evidence_refs


@pytest.mark.parametrize(
    "eid,quote",
    [
        ("M1", "PUE 모니터링 시스템을 운영한다"),
        ("M2", "기아 국내 생산 사업장의 RE100 이행을 위해"),
        ("M2", "기아 전사 RE100 이행을 위해"),
        ("P1", "PUE 1.12 유지"),
    ],
)
def test_concrete_means_boundaries_and_exact_values_survive(eid, quote):
    from proofops.application.tagging.k1_semantics import POLICY

    raw = element(eid, quote)
    assert guard_element(raw, policy=POLICY) == raw


def test_table_tail_label_is_retained_as_context_without_value_reassignment():
    from proofops.application.ingest.k1_boundaries import trim_table_labels

    text = "• 태양광: 2025년 전력 발전량 21.3 MWh 커넥트원 \n• 태양광: 2025년 전력 발전량 111.6MWh"
    end = text.index(" \n")
    spans = [dict(char_start=0, char_end=end, quote=text[:end], kind="claim")]
    new, records = trim_table_labels(spans, text, kind="table")
    assert new[0]["quote"] == "• 태양광: 2025년 전력 발전량 21.3 MWh"
    assert text[new[0]["char_start"] : new[0]["char_end"]] == new[0]["quote"]
    assert records[0]["excluded_quote"] == "커넥트원"
    assert trim_table_labels(spans, text, kind="paragraph") == (spans, [])
    other = text.replace("\n• 태양광:", "\n• 풍력:")
    assert trim_table_labels(spans, other, kind="table") == (spans, [])


def test_k1_policy_is_new_and_old_analysis_pin_still_resolves():
    from proofops.application.analysis_profile import FINALS_I1_POLICY, K1_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(FINALS_I1_POLICY) == (
        "df58e8330bb2dbb46cc6b3f3690ca6a44d0c31f2cdc20a4c387569ebd131f37c"
    )
    assert canonical_hash(K1_POLICY) != canonical_hash(FINALS_I1_POLICY)
    for policy in (FINALS_I1_POLICY, K1_POLICY):
        assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(policy)) == policy


def test_k1_reason_is_retained_without_echoing_arbitrary_errors():
    from proofops_worker.live_tagging import _local_stop_code

    code = "K1_PUE_PERFORMANCE_RETAG_REQUIRED"
    assert _local_stop_code("preliminary", ValueError(code)) == code
    assert "untrusted" not in _local_stop_code("preliminary", ValueError("untrusted source"))


@pytest.mark.parametrize("state", ["unknown", "conflict", "absent", "not_applicable"])
def test_k1_keeps_non_present_states(state):
    from proofops.application.tagging.k1_semantics import POLICY

    raw = element("M1", "PUE(전력사용효율지수)", state)
    assert guard_element(raw, policy=POLICY) == raw


def test_masked_pue_cannot_be_credited_through_an_exact_looking_subquote():
    from proofops.application.tagging.k1_semantics import POLICY

    raw = replace(element("P1", "1.1"), normalized_value="1.1")
    new = guard_element(raw, policy=POLICY, claim_quote="PUE 1.1x 유지")
    assert new.state == "unknown" and new.normalized_value is None
    assert new.reason_code == "K1_MASKED_VALUE_REQUIRES_REVIEW"


def test_label_after_another_table_column_is_not_appended_to_a_value():
    from proofops.application.ingest.k1_boundaries import trim_table_labels

    text = (
        "• 단열 성능 개선\t• 태양광: 2025년 전력 발전량 21.3 MWh 커넥트원 \n"
        "• 태양광: 2025년 전력 발전량 111.6MWh"
    )
    start, end = text.index("• 태양광"), text.index(" \n")
    spans = [dict(char_start=start, char_end=end, quote=text[start:end])]
    new, records = trim_table_labels(spans, text, kind="table")
    assert new[0]["quote"] == "• 태양광: 2025년 전력 발전량 21.3 MWh"
    assert records[0]["excluded_quote"] == "커넥트원"
    assert records[0]["excluded_start"] > new[0]["char_end"]
