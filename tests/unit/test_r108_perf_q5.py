"""Q5 synthetic controls for a free, opt-in saved-response experiment."""

from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import (
    ClaimContext,
    accept_binding,
    local_relation_tags,
    relation_tags_for,
)

from evaluation.r108_perf_q5 import diagnose, packet_admits, reuse_local_roles
from tests.acceptance.test_binding import DIMENSIONS, change_candidate, corpus, span, tags
from tests.acceptance.test_rules import pack
from tests.acceptance.test_tagging import execute, setup


def check(context, graph, ref, roles, element="P1"):
    return accept_binding(
        context,
        ref,
        roles,
        original=graph,
        tenant_id=graph.tenant_id,
        rulepack=pack(),
        element_id=element,
    )


def test_missing_local_map_reuses_only_claim_span_roles_without_mutation():
    graph, claim, refs = corpus()
    context = ClaimContext(claim, tags(refs[0]))
    original = {refs[1].source_id: tags(refs[1])}
    before = asdict(graph), asdict(claim), dict(original)
    reused = reuse_local_roles(context, original)
    assert reused == original | local_relation_tags(context)
    assert (asdict(graph), asdict(claim), original) == before


@pytest.mark.parametrize("entry", ["null", "empty", "malformed", "outside", "overlap"])
def test_explicit_or_ambiguous_source_mapping_is_never_replaced(entry):
    _, claim, refs = corpus()
    context = ClaimContext(claim, tags(refs[0]))
    sid = refs[0].source_id
    key = next(iter(local_relation_tags(context)))
    relations = {
        "null": {key: dict.fromkeys(DIMENSIONS)},
        "empty": {key: {}},
        "malformed": {sid + ":bad:range": tags(refs[0])},
        "outside": {f"{sid}:0:1": {}},
        "overlap": {key: tags(refs[0]), f"{sid}:0:1": {}},
    }[entry]
    assert reuse_local_roles(context, relations) == relations


def test_core_nulls_do_not_block_local_identity_but_optional_nulls_do():
    graph, claim, refs = corpus()
    context = ClaimContext(claim, dict.fromkeys(("entity", "metric", "reporting_period")))
    ref = span(refs[0], "40%")
    result = diagnose(context, ref, {}, graph=graph, rulepack=pack(), element_id="P1")
    assert result["binding"] == "accepted"
    assert result["categories"] == []
    context = ClaimContext(claim, dict(context.dimensions) | {"product": None})
    result = diagnose(context, ref, {}, graph=graph, rulepack=pack(), element_id="P1")
    assert result["binding"] == "undetermined"
    assert result["categories"] == ["e_local_explicit_optional_null"]
    assert result["unresolved_optional_axes"] == ["product"]


def test_external_axis_gaps_and_unlinked_metadata_are_overlapping_causes():
    graph, claim, refs = corpus()
    context = ClaimContext(claim, dict.fromkeys(("entity", "metric", "reporting_period")))
    result = diagnose(context, refs[1], {}, graph=graph, rulepack=pack(), element_id="P1")
    assert result["binding"] == "undetermined"
    assert result["categories"] == ["a_claim_axis_unresolved", "c_external_roles_unverified"]
    assert result["claim_missing_required"] == ["entity", "metric", "reporting_period"]
    assert result["report_period_unlinked"] is True


def test_existing_local_verified_axes_already_bind_without_repair():
    graph, claim, refs = corpus()
    context = ClaimContext(claim, tags(refs[0]))
    ref = span(refs[0], "40%")
    assert check(context, graph, ref, {}) == "accepted"
    result = diagnose(context, ref, {}, graph=graph, rulepack=pack(), element_id="P1")
    assert result["local_mapping_empty"] is True
    assert result["binding"] == "accepted"
    assert result["categories"] == []


@pytest.mark.parametrize("case", ["other_product", "other_period", "forged", "unverified"])
def test_reuse_does_not_admit_synthetic_negative(case):
    changes = {"product": "제품B"} if case == "other_product" else {}
    if case == "other_period":
        changes = {"reporting_period": "2024"}
    graph, claim, refs = corpus(**changes)
    context = ClaimContext(claim, tags(refs[0]))
    roles = {refs[1].source_id: tags(refs[1], DIMENSIONS | changes)}
    reused = reuse_local_roles(context, roles)
    if case in ("other_product", "other_period"):
        ref = span(refs[1], "40%")
    else:
        ref = span(refs[0], "40%")
        if case == "forged":
            ref = replace(ref, quote="41%")
        else:
            graph = replace(
                graph, blocks=tuple(replace(b, quality="unverified") for b in graph.blocks)
            )
    assert check(context, graph, ref, relation_tags_for(ref, reused)) != "accepted"


@pytest.mark.parametrize("optional", [None, "product", "material", "facility", "scope", "boundary"])
def test_opt_in_reaches_real_element_guard_without_lifting_optional_unknowns(tmp_path, optional):
    inputs = setup(tmp_path)
    context = inputs["context"]
    if optional:
        context = ClaimContext(context.claim, dict(context.dimensions) | {optional: None})
    inputs.update(context=context, relation_tags=reuse_local_roles(context, {}))
    runs = execute(inputs)
    assert len(inputs["invoke"].requests) == 3
    assert [r.guarded.elements[0].state for r in runs] == ["unknown" if optional else "present"] * 3


def test_missing_response_is_not_a_vote():
    from evaluation.r108_perf_q5 import state_summary

    assert state_summary([None, None, None]) == dict(
        present_votes=0, unanimous_present=0, unanimous_unknown=0
    )


@pytest.mark.parametrize("element", ["G1", "G2", "G3", "G5", "P1", "P2"])
def test_global_numbers_and_years_still_rejected_with_opt_in(element):
    graph, claim, refs = corpus()
    graph = change_candidate(graph, refs[1].source_id, kind="paragraph", table_native_id=None)
    context = ClaimContext(claim, tags(refs[0]))
    relations = reuse_local_roles(context, {refs[1].source_id: tags(refs[1])})
    assert (
        check(context, graph, refs[1], relation_tags_for(refs[1], relations), element) == "rejected"
    )


@pytest.mark.parametrize("scope,expected", [("local_claim", True), ("global_bound", False)])
def test_earlier_packet_scope_gate_is_distinct_from_binding(scope, expected):
    _, _, refs = corpus()
    packet = dict(
        evidence_candidates=[
            dict(
                source_id=refs[0].source_id,
                source_scope=scope,
                allowed_elements=["P1"],
                source_refs=[asdict(refs[0])],
            )
        ]
    )
    assert packet_admits(packet, asdict(span(refs[0], "40%")), "P1", ["local_claim"]) == expected


def test_unavailable_converted_response_is_carried_without_inventing_a_vote(tmp_path):
    from proofops.adapters.aws.usage import LocalSQLiteUsageStore
    from proofops.application.budget import BudgetLimits, RoleLimit

    from evaluation.r108_perf_q5 import replay_votes

    inputs = setup(tmp_path)
    saved = [asdict(r) for r in execute(inputs)]
    saved[0].update(
        raw_response_json=None,
        guarded=None,
        errors=["TAGGING_EVIDENCE_ID_INVALID"],
        status="citation_unresolved",
    )
    usage = LocalSQLiteUsageStore(tmp_path / "replay.sqlite3")
    usage.create_budget(
        inputs["tenant_id"],
        inputs["packet"].to_dict()["run_id"],
        inputs["context"].claim.document_version_id,
        BudgetLimits(1_000_000, 1_000_000, (RoleLimit("tagger", 10, 50000, 1000, 51000),)),
    )
    result = replay_votes(
        dict(tag_runs=saved),
        inputs["context"],
        inputs["relation_tags"],
        inputs["packet"],
        inputs["rulepack"],
        inputs["original"],
        inputs["settings"],
        usage,
    )
    assert result[0] is None
    assert [v["elements"][0]["state"] for v in result[1:]] == ["present", "present"]
