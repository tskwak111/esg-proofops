from dataclasses import replace
from itertools import permutations

import pytest
from proofops.application.tagging.consensus import PARTIAL_FACTS_PROFILES, form_consensus
from proofops.domain.rules.engine import RuleContext, evaluate

from tests.acceptance.test_tagging import TENANT, execute, setup

PROFILE = "grade-relevant-unanimity-v1"


def test_f5_v3_has_a_distinct_hash_and_preserves_v1_v2_hashes():
    assert PARTIAL_FACTS_PROFILES[PROFILE] == (
        "703602eeae123967e341d30be1e8bddfb385e0e90329253a196c613573b1d4bc"
    )
    assert PARTIAL_FACTS_PROFILES["grade-relevant-unanimity-v2"] == (
        "bc76ec9df9b341059e1d68ed65ff5ab3dc57ce02991807778bb18fc3f40e0e9f"
    )
    assert len(set(PARTIAL_FACTS_PROFILES.values())) == len(PARTIAL_FACTS_PROFILES)


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize(
    "case,states,expected",
    [
        ("two_conflict_one_missing", ("conflict", "conflict", None), "conflict"),
        ("one_conflict_two_missing", ("conflict", None, None), "conflict"),
        ("two_conflict_one_unknown", ("conflict", "conflict", "unknown"), "conflict"),
        ("two_conflict_one_present", ("conflict", "conflict", "present"), "conflict"),
        ("three_conflict_different_values", ("conflict",) * 3, "conflict"),
        ("three_absent", ("absent",) * 3, "unknown"),
        ("three_unknown", ("unknown",) * 3, "unknown"),
        ("two_present_one_missing", ("present", "present", None), "unknown"),
        ("one_present_two_missing", ("present", None, None), "unknown"),
        ("two_absent_one_missing", ("absent", "absent", None), "unknown"),
        ("two_unknown_one_missing", ("unknown", "unknown", None), "unknown"),
    ],
)
def test_f5_partial_failure_and_r16b_cases_preserve_historical_replay(
    tmp_path, version, case, states, expected
):
    inputs = setup(tmp_path)
    runs = execute(inputs)
    # A surviving conflict must be independent of which replica failed.
    for ordered_states in dict.fromkeys(permutations(states)):
        changed = []
        for index, (run, state) in enumerate(zip(runs, ordered_states, strict=True)):
            if state is None:
                changed.append(
                    replace(
                        run,
                        product_variant=False,
                        guarded=None,
                        status="model_failed",
                        errors=("MODEL_UNAVAILABLE",),
                    )
                )
                continue
            elements = tuple(
                replace(
                    e,
                    state=state,
                    evidence_refs=e.evidence_refs if state == "present" else (),
                    normalized_value=(
                        str(index)
                        if case == "three_conflict_different_values"
                        else e.normalized_value
                        if state == "present"
                        else None
                    ),
                )
                if e.element_id == "P1"
                else e
                for e in run.guarded.elements
            )
            changed.append(
                replace(run, product_variant=False, guarded=replace(run.guarded, elements=elements))
            )
        result = form_consensus(
            tuple(changed),
            packet=inputs["packet"],
            rulepack=inputs["rulepack"],
            tenant_id=TENANT,
            tag_revision=1,
            profile=f"grade-relevant-unanimity-v{version}",
        )
        historical_missing_conflict = version < 3 and None in states and "conflict" in states
        state = "unknown" if historical_missing_conflict else expected
        candidate = next(e for e in result.candidate_elements if e.element_id == "P1")
        assert candidate.state == state
        assert candidate.evidence_refs == ()
        assert candidate.normalized_value is None and candidate.credited_from is None
        assert result.review_status == "needs_review"
        assert "REVIEW:P1" in result.reasons
        assert result.confirmed_tags is not None
        facts = {f.name: f.state for f in result.confirmed_tags.facts}
        assert facts["quantitative_or_qualified_ordinal"] == state
        decision = evaluate(
            result.confirmed_tags,
            RuleContext(
                TENANT,
                inputs["context"].claim.document_version_id,
                inputs["context"].claim.claim_id,
                inputs["packet"].packet_sha256,
                local_synthetic=True,
            ),
            inputs["rulepack"],
        )
        assert decision.decision_status == "blocked_evidence"
        assert decision.evidence_grade is None and decision.label is None


@pytest.mark.parametrize("unsafe", ["MODEL_PROVENANCE_INVALID", "provider_replay"])
def test_f5_v3_surviving_conflict_does_not_bypass_safety_checks(tmp_path, unsafe):
    inputs = setup(tmp_path)
    runs = list(execute(inputs))
    first = runs[0]
    elements = tuple(
        replace(e, state="conflict", evidence_refs=(), normalized_value=None)
        for e in first.guarded.elements
    )
    runs[0] = replace(first, guarded=replace(first.guarded, elements=elements))
    runs[1] = replace(runs[1], guarded=None, status="model_failed", errors=("MODEL_UNAVAILABLE",))
    if unsafe == "provider_replay":
        runs[2] = replace(
            runs[2],
            usage=replace(runs[2].usage, provider_request_id=first.usage.provider_request_id),
        )
    else:
        runs[1] = replace(runs[1], errors=runs[1].errors + (unsafe,))
    result = form_consensus(
        tuple(runs),
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=TENANT,
        tag_revision=1,
        profile="grade-relevant-unanimity-v3",
    )
    assert result.candidate_elements == ()
    assert result.confirmed_tags is None
    assert result.review_status == "needs_review"
    assert result.reasons == ("PARTIAL_FACTS_UNSAFE",)


def test_opt_in_exposes_only_python_lower_bound_and_preserves_unknowns(tmp_path):
    inputs = setup(tmp_path)
    runs = tuple(replace(run, product_variant=False) for run in execute(inputs))
    options = dict(
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=TENANT,
        tag_revision=1,
    )

    legacy = form_consensus(runs, **options)
    selected = form_consensus(runs, profile=PROFILE, **options)

    assert legacy.confirmed_tags is None
    assert selected.confirmed_tags is not None
    assert selected.review_status == "needs_review"
    facts = {fact.name: fact.state for fact in selected.confirmed_tags.facts}
    assert facts["quantitative_or_qualified_ordinal"] == "present"
    assert facts["comparison_baseline"] == "unknown"

    decision = evaluate(
        selected.confirmed_tags,
        RuleContext(
            TENANT,
            inputs["context"].claim.document_version_id,
            inputs["context"].claim.claim_id,
            inputs["packet"].packet_sha256,
            local_synthetic=True,
        ),
        inputs["rulepack"],
    )
    assert decision.decision_status == "blocked_evidence"
    assert decision.evidence_grade is None
    assert decision.label is None
    assert (decision.grade_floor, decision.grade_ceiling) == ("E1", "E3")
    assert decision.grade_open_elements == ("P2", "P3", "P4")


def test_two_of_three_vote_on_grade_relevant_fact_remains_conflicted(tmp_path):
    inputs = setup(tmp_path)
    runs = tuple(replace(run, product_variant=False) for run in execute(inputs))
    changed = []
    for index, run in enumerate(runs):
        if index != 0:
            changed.append(run)
            continue
        guarded = run.guarded
        assert guarded is not None
        elements = tuple(
            replace(element, state="unknown", evidence_refs=(), normalized_value=None)
            if element.element_id == "P1"
            else element
            for element in guarded.elements
        )
        changed.append(replace(run, guarded=replace(guarded, elements=elements)))

    result = form_consensus(
        tuple(changed),
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=TENANT,
        tag_revision=1,
        profile=PROFILE,
    )

    assert result.confirmed_tags is not None
    facts = {fact.name: fact.state for fact in result.confirmed_tags.facts}
    assert facts["quantitative_or_qualified_ordinal"] == "conflict"
    assert result.review_status == "needs_review"


def test_new_f5_policy_preserves_unanimous_conflict_and_historical_replay(tmp_path):
    inputs = setup(tmp_path)
    runs = []
    for run in execute(inputs):
        elements = tuple(
            replace(e, state="conflict", evidence_refs=(), normalized_value=None)
            if e.element_id == "P1"
            else e
            for e in run.guarded.elements
        )
        runs.append(
            replace(run, product_variant=False, guarded=replace(run.guarded, elements=elements))
        )
    options = dict(
        packet=inputs["packet"], rulepack=inputs["rulepack"], tenant_id=TENANT, tag_revision=1
    )
    historical = form_consensus(tuple(runs), profile=PROFILE, **options)
    assert historical.candidate_elements[0].state == "unknown"
    current = form_consensus(tuple(runs), profile="grade-relevant-unanimity-v2", **options)
    assert current.candidate_elements[0].state == "conflict"
    assert current.review_status == "needs_review"
    facts = {f.name: f.state for f in current.confirmed_tags.facts}
    assert facts["quantitative_or_qualified_ordinal"] == "conflict"
    decision = evaluate(
        current.confirmed_tags,
        RuleContext(
            TENANT,
            inputs["context"].claim.document_version_id,
            inputs["context"].claim.claim_id,
            inputs["packet"].packet_sha256,
            local_synthetic=True,
        ),
        inputs["rulepack"],
    )
    assert decision.evidence_grade is None and decision.label is None


@pytest.mark.parametrize("element_id", ["P2", "P4"])
def test_two_of_three_baseline_or_assurance_votes_cannot_publish_higher_grade(tmp_path, element_id):
    inputs = setup(tmp_path)
    runs = tuple(replace(run, product_variant=False) for run in execute(inputs))
    changed = []
    for index, run in enumerate(runs):
        if index == 0:
            changed.append(run)
            continue
        assert run.guarded is not None
        # The synthetic fixture has a verified P1 span only; reuse it solely to
        # exercise vote aggregation. The disputed P2/P4 remains a conflict.
        elements = tuple(
            replace(
                element,
                state="present",
                evidence_refs=run.guarded.elements[0].evidence_refs,
                normalized_value="40%",
            )
            if element.element_id == element_id
            else element
            for element in run.guarded.elements
        )
        binding_hashes = dict(run.binding_hashes)
        binding_hashes[element_id] = binding_hashes["P1"]
        source_scopes = dict(run.source_scopes)
        source_scopes[element_id] = source_scopes["P1"]
        changed.append(
            replace(
                run,
                guarded=replace(run.guarded, elements=elements),
                binding_hashes=tuple(sorted(binding_hashes.items())),
                source_scopes=tuple(sorted(source_scopes.items())),
            )
        )

    result = form_consensus(
        tuple(changed),
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=TENANT,
        tag_revision=1,
        profile=PROFILE,
    )

    assert result.confirmed_tags is not None
    facts = {fact.name: fact.state for fact in result.confirmed_tags.facts}
    expected_fact = "comparison_baseline" if element_id == "P2" else "assurance_covered"
    assert facts[expected_fact] == "conflict"
    assert result.review_status == "needs_review"
    decision = evaluate(
        result.confirmed_tags,
        RuleContext(
            TENANT,
            inputs["context"].claim.document_version_id,
            inputs["context"].claim.claim_id,
            inputs["packet"].packet_sha256,
            local_synthetic=True,
        ),
        inputs["rulepack"],
    )
    assert decision.decision_status == "blocked_evidence"
    assert decision.evidence_grade is None
