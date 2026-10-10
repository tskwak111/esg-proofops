"""Registry-only explanation discovery and human difference linkage."""

from copy import deepcopy

import pytest
from proofops.application.reconciliation.explanation import (
    difference_binding,
    registered_explanation_search,
)

from tests.reconciliation.test_service import _call, _case


def _candidate(case, source_id="explanation"):
    packet, _, _, documents, coverage, _ = case
    source = dict(packet["sources"][0], source_id=source_id)
    documents[source["document_id"]]["source_bindings"][source_id] = {
        "locator": source["locator"],
        "quote": source["quote"],
        "roles": ["explanation"],
        "human_reviewed": True,
        "reviewed_by": "reviewer",
        "difference_binding": difference_binding(packet),
    }
    coverage["receipt"]["reviewed_source_ids"].append(source_id)
    return source


def _search(case):
    return lambda packet: registered_explanation_search(packet, case[3], case[4])


def test_registered_search_is_stable_and_requires_reviewed_role(tmp_path):
    case = _case(tmp_path)
    case[0]["financial"]["normalized"] = '["A"]'
    case[3]["fs-v1"]["fact_bindings"]["fs-scope"]["normalized"] = '["A"]'
    second, first = _candidate(case, "z"), _candidate(case, "a")
    _candidate(case, "unreviewed")
    case[4]["receipt"]["reviewed_source_ids"].remove("unreviewed")
    assert _search(case)(case[0]) == [first, second]
    result = _call(case, explanation_search=_search(case))
    assert result["execution_state"] == "completed"
    assert result["explanation_source_id"] == "a"


@pytest.mark.parametrize(
    "field,value",
    [
        ("human_reviewed", False),
        ("reviewed_by", ""),
        ("difference_binding", {}),
    ],
)
def test_unlinked_candidate_blocks_instead_of_proving_absence(tmp_path, field, value):
    case = _case(tmp_path)
    source = _candidate(case)
    case[3][source["document_id"]]["source_bindings"]["explanation"][field] = value
    result = _call(case, explanation_search=_search(case))
    assert result["reason_codes"] == ["explanation_difference_unverified"]


def test_unreadable_candidate_is_blocked(tmp_path):
    case = _case(tmp_path)
    _candidate(case)
    (tmp_path / "sr-v1.txt").unlink()
    assert _call(case, explanation_search=_search(case))["execution_state"] == "blocked"


def test_reviewed_candidate_already_in_packet_can_be_selected(tmp_path):
    case = _case(tmp_path)
    case[0]["financial"]["normalized"] = '["A"]'
    case[3]["fs-v1"]["fact_bindings"]["fs-scope"]["normalized"] = '["A"]'
    source = _candidate(case)
    case[0]["sources"].append(source)
    result = _call(case, explanation_search=_search(case))
    assert result["explanation_source_id"] == source["source_id"]


def test_duplicate_candidates_are_rejected(tmp_path):
    case = _case(tmp_path)
    source = _candidate(case)
    assert _call(case, explanation_search=lambda _: [source, source])["reason_codes"] == [
        "explanation_source_unverified"
    ]


def test_empty_search_and_incomplete_coverage_do_not_prove_absence(tmp_path):
    case = _case(tmp_path)
    case[0]["financial"]["normalized"] = '["A"]'
    case[3]["fs-v1"]["fact_bindings"]["fs-scope"]["normalized"] = '["A"]'
    case[4]["receipt"]["state"] = "incomplete"
    before = deepcopy(case[0])
    result = _call(case, explanation_search=_search(case))
    assert result["execution_state"] == "blocked"
    assert result["reason_codes"] == ["search_incomplete"]
    assert case[0] == before
