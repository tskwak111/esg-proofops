from dataclasses import replace

import pytest
from proofops.application.tagging.consensus import form_consensus
from proofops.domain.rules.engine import RuleContext, evaluate

from tests.acceptance.test_tagging import TENANT, execute, setup

PROFILE = "grade-relevant-unanimity-v1"


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
