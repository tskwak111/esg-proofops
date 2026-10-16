from copy import deepcopy

import pytest
from proofops.application.tagging.grade_required_agreement_policy import (
    GradeRequiredAgreementPolicy,
    assess_grade_required_facts,
)


def replicas(states):
    return [
        dict(
            replicate_id=i,
            request_id=f"request-{i}",
            provider_request_id=f"provider-{i}",
            current_response_bound=True,
            context_sha256="a" * 64,
            elements={
                "M1": dict(
                    state=state,
                    normalized_value="EMS" if state == "present" else None,
                    binding="accepted" if state == "present" else None,
                    binding_sha256="b" * 64 if state == "present" else None,
                    source_refs=[dict(verification_state="verified")] if state == "present" else [],
                )
            },
        )
        for i, state in enumerate(states, 1)
    ]


def assess(votes, threshold=3, **kwargs):
    return assess_grade_required_facts(
        votes,
        required_element_ids=("M1",),
        claim_source_verified=True,
        policy=GradeRequiredAgreementPolicy(threshold),
        **kwargs,
    )


@pytest.mark.parametrize("present_count", [1, 2, 3])
@pytest.mark.parametrize("threshold", [1, 2, 3])
def test_threshold_only_relaxes_unknown_votes(present_count, threshold):
    votes = replicas(["present"] * present_count + ["unknown"] * (3 - present_count))
    receipt = assess(votes, threshold)
    assert receipt["grade_facts_satisfied"] == (present_count >= threshold)
    assert receipt["minimum_present_replicas"] == threshold
    assert receipt["public_auto_confirmed"] is False


@pytest.mark.parametrize("state", ["absent", "conflict", "unreadable", "missing"])
@pytest.mark.parametrize("threshold", [1, 2, 3])
def test_any_contrary_or_unreadable_vote_blocks(state, threshold):
    assert not assess(replicas(["present", "present", state]), threshold)["grade_facts_satisfied"]


@pytest.mark.parametrize(
    "mutation",
    [
        "citation",
        "binding",
        "value",
        "binding_hash",
        "fresh",
        "replay",
        "context",
        "missing",
    ],
)
def test_relaxation_keeps_source_identity_freshness_and_value_guards(mutation):
    votes = replicas(["present"] * 3)
    element = votes[1]["elements"]["M1"]
    if mutation == "citation":
        element["source_refs"][0]["verification_state"] = "unverified"
    elif mutation == "binding":
        element["binding"] = "rejected"
    elif mutation == "value":
        element["normalized_value"] = "different activity"
    elif mutation == "binding_hash":
        element["binding_sha256"] = "c" * 64
    elif mutation == "fresh":
        votes[1]["current_response_bound"] = False
    elif mutation == "replay":
        votes[1]["provider_request_id"] = votes[0]["provider_request_id"]
    elif mutation == "context":
        votes[1]["context_sha256"] = "c" * 64
    else:
        votes.pop()
    assert not assess(votes, 1)["grade_facts_satisfied"]


def test_default_hash_immutability_and_no_source_bypass():
    default = GradeRequiredAgreementPolicy()
    assert default.minimum_present_replicas == 3
    assert len({GradeRequiredAgreementPolicy(n).sha256 for n in (1, 2, 3)}) == 3
    votes = replicas(["present"] * 3)
    original = deepcopy(votes)
    result = assess_grade_required_facts(
        votes,
        required_element_ids=("M1",),
        claim_source_verified=False,
    )
    assert not result["grade_facts_satisfied"]
    assert votes == original
    assert default.sha256 == GradeRequiredAgreementPolicy(3).sha256


@pytest.mark.parametrize("threshold", [0, 4, True, 2.0, "2"])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        GradeRequiredAgreementPolicy(threshold)
