"""DEC-15: two independent selections never manufacture source evidence."""

from copy import deepcopy

import pytest
from proofops.application.tagging.decisions import (
    AXES,
    POLICY,
    preliminary_questions,
    resolve_preliminary,
    resolve_relation,
    validate_answers,
)


def answer(choice, choices, probability=0.9):
    rest = (1 - probability) / (len(choices) - 1)
    return dict(
        type="choice",
        choice=choice,
        confidence=0.7,
        probabilities={c: probability if c == choice else rest for c in choices},
    )


def preliminary_answers(track="goal", probability=0.9):
    questions = preliminary_questions()
    return {
        k: answer(track if k == "track" else "present", q["criteria"], probability)
        for k, q in questions.items()
    }


def test_agreement_threshold_unknown_and_literal_quote_gate():
    a = preliminary_answers()
    b = deepcopy(a)
    fields = resolve_preliminary(a, b, {"metric": "literal"})
    assert fields["track"]["value"] == "goal"
    assert fields["metric"]["value"] == "literal"
    assert fields["entity"]["state"] == "unresolved"  # no quote from judgment
    b["track"] = answer("goal", preliminary_questions()["track"]["criteria"], 0.79)
    b["axis_metric"] = answer("unknown", ("present", "unknown"))
    fields = resolve_preliminary(a, b, {"metric": "literal"})
    assert fields["track"]["state"] == fields["metric"]["state"] == "unresolved"
    a["axis_entity"] = b["axis_entity"] = answer("unknown", ("present", "unknown"))
    assert resolve_preliminary(a, b, {})["entity"]["value"] is None
    assert "absent" not in str(resolve_preliminary(a, b, {}))
    assert set(fields) == {"track", *AXES}


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("supports", "supports", "supports"),
        ("supports", "partial", "partial"),
        ("supports", "unrelated", "unknown"),
        ("unknown", "unknown", "unknown"),
    ],
)
def test_relation_requires_both_supports(left, right, expected):
    assert resolve_relation(left, right) == expected


def test_choice_arrays_dicts_and_refusal_are_not_guessed():
    questions = preliminary_questions()
    raw = preliminary_answers()
    assert validate_answers({"answers": raw}, questions) == raw
    wire = [
        dict(
            a,
            name=k,
            probabilities=[dict(value=v, probability=p) for v, p in a["probabilities"].items()],
        )
        for k, a in raw.items()
    ]
    assert validate_answers({"answers": wire}, questions) == raw
    wire[0] = dict(type="refusal", name="track")
    assert validate_answers({"answers": wire}, questions)["track"] is None
    wire.append(wire[-1])
    with pytest.raises(ValueError, match="DECISION_ANSWERS_INVALID"):
        validate_answers({"answers": wire}, questions)


@pytest.mark.parametrize("bad", [True, float("nan"), -0.1, 1.1])
def test_invalid_probabilities_cannot_confirm(bad):
    raw = preliminary_answers()
    raw["track"]["probabilities"]["goal"] = bad
    with pytest.raises(ValueError):
        validate_answers({"answers": raw}, preliminary_questions())


def test_opt_in_policy_models_and_thresholds_are_pinned():
    from evaluation.local_upstage_pilot import live_tagging_settings

    old = live_tagging_settings(12, model_id="openai/gpt-6-luna")
    new = live_tagging_settings(
        12,
        model_id="openai/gpt-6-luna",
        preliminary_profile="decision-v1",
        relations=True,
        relation_profile="decision-gate-v1",
    )
    assert "decision_settings" not in old
    assert new["decision_settings"]["policy"] == POLICY
    assert new["preliminary_settings"]["model_profile"] == "preliminary-decision-v1"
    assert new["relation_settings"]["model_profile"] == "relation-decision-gate-v1"
