"""F7: real preliminary, binding, element guard and consensus; no providers."""

from copy import deepcopy

import pytest
from proofops.application.evidence.binding import accept_binding, relation_tags_for
from proofops.application.tagging.decisions import AXES
from proofops.application.tagging.preliminary import preliminary_request, validate_preliminary
from proofops_worker.live_tagging import LiveTaggingRuntime

from tests.acceptance.test_tagging import consensus, execute, setup
from tests.unit.test_decision_profiles import answer, preliminary_answers


def decide(inputs, dimensions, pair=None, categories=(None, None, None)):
    claim, graph = inputs["context"].claim, inputs["original"]
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.decision_records = {}
    pair = pair or [preliminary_answers(track="performance")] * 2
    runtime._decision_pair = lambda *a, **kw: (pair, [])
    results = [
        validate_preliminary(
            claim,
            graph,
            dict(
                claim_id=claim.claim_id,
                track="performance",
                track_confidence=0.9,
                safe_harbor_category=category,
                dimensions=values,
            ),
            tenant_id=claim.tenant_id,
        )
        for values, category in zip(dimensions, categories, strict=True)
    ]
    packet = preliminary_request(claim, graph, tenant_id=claim.tenant_id)
    return runtime, runtime._decision_preliminary(claim, packet, results)


@pytest.mark.parametrize(
    "optional,expected",
    [
        ({}, "accepted"),
        (dict.fromkeys(AXES[3:]), "undetermined"),
        ({"product": None}, "undetermined"),
    ],
)
def test_decision_context_reaches_binding_guarded_element_and_consensus(
    tmp_path, optional, expected
):
    # A-03 synthetic fixture: omission tests representation, not semantic applicability.
    inputs = setup(tmp_path)
    values = dict(entity=None, metric=None, reporting_period=None) | optional
    runtime, result = decide(inputs, [values] * 3)
    assert result is not None
    track, context, relations = result
    assert dict(context.dimensions) == values
    source = inputs["invoke"].source
    assert (
        accept_binding(
            context,
            source,
            relation_tags_for(source, relations),
            original=inputs["original"],
            tenant_id=inputs["tenant_id"],
            rulepack=inputs["rulepack"],
            element_id="P1",
        )
        == expected
    )
    inputs.update(track=track, context=context, relation_tags=relations)
    runs = execute(inputs)
    guarded = "present" if expected == "accepted" else "unknown"
    assert len(runs) == 3
    assert all(run.status == "needs_review" for run in runs)  # P2-P6 remain unknown.
    assert all(run.guarded.elements[0].state == guarded for run in runs)
    assert consensus(runs, inputs).candidate_elements[0].state == guarded
    fields = runtime.decision_records[context.claim.claim_id]["fields"]
    assert set(fields) == {"track", *AXES}
    assert fields["product"]["diagnostic_code"] == "DECISION_NO_USABLE_QUOTE"


@pytest.mark.parametrize("axis", AXES[3:])
@pytest.mark.parametrize(
    "kind", ["explicit_null", "missing_key", "different_quote", "unknown", "low_probability"]
)
def test_applicable_optional_axis_remains_unresolved(tmp_path, axis, kind):
    inputs = setup(tmp_path)
    values = dict(entity=None, metric=None, reporting_period=None)
    quote = {"source_index": 0, "quote": inputs["context"].dimensions[axis].quote}
    dimensions = [values | {axis: quote} for _ in range(3)]
    pair = [preliminary_answers(track="performance"), preliminary_answers(track="performance")]
    if kind == "explicit_null":
        dimensions = [values | {axis: None} for _ in range(3)]
    elif kind == "missing_key":
        dimensions[1] = values
    elif kind == "different_quote":
        dimensions[1] = values | {axis: {"source_index": 0, "quote": "40%"}}
    elif kind == "unknown":
        for response in pair:
            response["axis_" + axis] = answer("unknown", ("present", "unknown"))
    else:
        pair[1]["axis_" + axis] = answer("present", ("present", "unknown"), 0.79)
    _, result = decide(inputs, dimensions, pair)
    assert result is not None
    _, context, relations = result
    assert set(context.dimensions) == {*values, axis}
    assert context.dimensions[axis] is None
    source = inputs["invoke"].source
    assert (
        accept_binding(
            context,
            source,
            relation_tags_for(source, relations),
            original=inputs["original"],
            tenant_id=inputs["tenant_id"],
            rulepack=inputs["rulepack"],
            element_id="P1",
        )
        == "undetermined"
    )


def test_agreed_applicable_quote_is_preserved_and_unknown_cannot_create_keys(tmp_path):
    inputs = setup(tmp_path)
    values = dict(entity=None, metric=None, reporting_period=None)
    values["scope"] = {"source_index": 0, "quote": "Scope 1"}
    pair = [preliminary_answers(track="performance"), preliminary_answers(track="performance")]
    for response in pair:
        response["axis_product"] = answer("unknown", ("present", "unknown"))
    _, result = decide(inputs, [values] * 3, pair)
    assert result is not None
    assert set(result[1].dimensions) == set(values)
    assert result[1].dimensions["scope"].quote == "Scope 1"
    inputs.update(track=result[0], context=result[1], relation_tags=result[2])
    assert consensus(execute(inputs), inputs).candidate_elements[0].state == "present"


def test_simple_claim_with_no_optional_roles_keeps_direct_evidence_accepted():
    from proofops.application.evidence.binding import ClaimContext

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_preliminary import context_corpus
    from tests.acceptance.test_rules import pack

    graph, claim, _ = context_corpus()
    inputs = dict(context=ClaimContext(claim, {}), original=graph)
    values = dict(entity=None, metric=None, reporting_period=None)
    pair = [preliminary_answers(track="performance"), preliminary_answers(track="performance")]
    for response in pair:
        for axis in AXES[3:]:
            response["axis_" + axis] = answer("unknown", ("present", "unknown"))
    _, result = decide(inputs, [values] * 3, pair)
    assert result is not None
    _, context, relations = result
    assert dict(context.dimensions) == values
    source = span(claim.source_refs[0], "40%")
    assert (
        accept_binding(
            context,
            source,
            relation_tags_for(source, relations),
            original=graph,
            tenant_id=claim.tenant_id,
            rulepack=pack(),
            element_id="P1",
        )
        == "accepted"
    )


def test_offline_context_blockers_match_the_worker_path(tmp_path):
    from evaluation.decision_profile_replay import context_binding_comparison

    inputs = setup(tmp_path)
    values = dict(entity=None, metric=None, reporting_period=None)
    replicas = [values, values | {"product": None}, values]
    runtime, result = decide(inputs, replicas)
    fields = runtime.decision_records[inputs["context"].claim.claim_id]["fields"]
    comparison = context_binding_comparison(fields, replicas)
    assert comparison["after"] == dict(result[1].dimensions)
    assert comparison["before_unresolved_optional"] == list(AXES[3:])
    assert comparison["after_unresolved_optional"] == ["product"]
    assert comparison["omitted_optional_axes"] == ["facility", "scope", "material", "boundary"]


def test_track_and_category_gates_still_block(tmp_path):
    inputs = setup(tmp_path)
    values = dict(entity=None, metric=None, reporting_period=None)
    pair = [preliminary_answers(track="performance"), preliminary_answers(track="goal")]
    assert decide(inputs, [values] * 3, pair)[1] is None
    assert decide(inputs, [values] * 3, categories=(None, "forward_looking", None))[1] is None
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.decision_records = {}
    runtime._decision_pair = lambda *a, **kw: ([preliminary_answers()] * 2, [])
    claim = inputs["context"].claim
    packet = preliminary_request(claim, inputs["original"], tenant_id=claim.tenant_id)
    assert runtime._decision_preliminary(claim, packet, None) is None


def test_context_policy_has_a_new_pin_and_old_snapshot_is_not_reinterpreted(tmp_path):
    from uuid import uuid4

    from proofops.application.tagging.decisions import POLICY, validate_decision_snapshot

    from tests.acceptance.test_preflight import AUTH
    from tests.integration.test_decision_profile_wiring import run_setup

    service, body = run_setup(tmp_path)
    result = service.create(AUTH, body, str(uuid4()))
    snapshot = service.store.snapshot(AUTH.tenant_id, result["run_id"])
    assert POLICY["preliminary_context"]["schema"] == "luna-axis-presence-v1"
    assert (
        snapshot["decision_settings"]["policy"]["preliminary_context"]
        == POLICY["preliminary_context"]
    )
    old = deepcopy(snapshot)
    old["decision_settings"]["policy"].pop("preliminary_context")
    with pytest.raises(ValueError, match="DECISION_SETTINGS_INVALID"):
        validate_decision_snapshot(old)
