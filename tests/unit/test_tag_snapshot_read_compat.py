"""Only the named optional TagRun field has absent/null read equivalence."""

from copy import deepcopy

import pytest
from proofops.adapters.local.tag_store import TAG_RUN_READ_COMPAT_NULL_FIELDS, _tag_replay_hash


def _snapshot():
    return {
        "tag_runs": [{"replicate_id": n, "diagnostic_detail": None} for n in (1, 2, 3)],
        "claim": {"diagnostic_detail": None, "quote": "source"},
    }


def test_only_named_tag_run_null_fields_are_compatible_without_mutation():
    assert TAG_RUN_READ_COMPAT_NULL_FIELDS == frozenset({"diagnostic_detail"})
    current = _snapshot()
    historical = deepcopy(current)
    for entry in historical["tag_runs"]:
        del entry["diagnostic_detail"]
    before = deepcopy(historical)
    assert _tag_replay_hash(current) == _tag_replay_hash(historical)
    assert historical == before
    assert _tag_replay_hash(historical) == _tag_replay_hash(current)


@pytest.mark.parametrize(
    "change", ["value", "added_key", "removed_key", "other_value", "outside_tag_runs", "order"]
)
def test_other_tag_snapshot_differences_still_fail(change):
    current = _snapshot()
    changed = deepcopy(current)
    entry = changed["tag_runs"][0]
    if change == "value":
        entry["diagnostic_detail"] = "diagnostic"
    elif change == "added_key":
        entry["other_optional"] = None
    elif change == "removed_key":
        del entry["replicate_id"]
    elif change == "other_value":
        entry["replicate_id"] = 4
    elif change == "outside_tag_runs":
        del changed["claim"]["diagnostic_detail"]
    else:
        changed["tag_runs"].reverse()
    assert _tag_replay_hash(current) != _tag_replay_hash(changed)


@pytest.mark.parametrize("value", ["", False, 0, [], {}, "null"])
def test_missing_diagnostic_is_not_equivalent_to_non_null_values(value):
    historical = _snapshot()
    del historical["tag_runs"][0]["diagnostic_detail"]
    changed = _snapshot()
    changed["tag_runs"][0]["diagnostic_detail"] = value
    assert _tag_replay_hash(historical) != _tag_replay_hash(changed)
