"""Behavioral contracts for the private main APIs reconciliation consumes."""

from __future__ import annotations

import json
import sqlite3

import pytest
from proofops.adapters.local.job_store import LocalSQLiteJobStore
from proofops.domain.rules.engine import MAPPINGS

from tests.integration.test_local_parser_runner import TENANT
from tests.integration.test_reviewed_tag_head_consumers import (
    _store,
    _track_changing_review,
)


def test_jobs_reads_are_scoped_and_transaction_rolls_back(tmp_path):
    jobs = LocalSQLiteJobStore(tmp_path / "jobs.sqlite")
    with jobs._transaction() as db:
        assert isinstance(db, sqlite3.Connection), "jobs transaction must yield SQLite connection"
        jobs._put(db, "tenant", "run", "claim_head", "claim", {"tag_revision": 2})
        raw = jobs._raw(db, "tenant", "run", "claim_head", "claim")
        assert isinstance(raw, bytes), "jobs._raw must retain serialized bytes for hash checks"
        assert json.loads(raw) == jobs._get(db, "tenant", "run", "claim_head", "claim")
        for scope in [("foreign", "run"), ("tenant", "other-run")]:
            assert jobs._raw(db, *scope, "claim_head", "claim") is None
            with pytest.raises(KeyError, match="resource not found"):
                jobs._get(db, *scope, "claim_head", "claim")
    with pytest.raises(RuntimeError, match="abort"):
        with jobs._transaction() as db:
            jobs._put(db, "tenant", "run", "claim_head", "claim", {"tag_revision": 3})
            raise RuntimeError("abort")
    with jobs._transaction() as db:
        assert jobs._get(db, "tenant", "run", "claim_head", "claim") == {
            "tag_revision": 2
        }, "jobs._transaction must roll back failed anchor reads/writes"


def test_current_tag_and_reconciliation_share_the_accepted_head(tmp_path, monkeypatch):
    run_root = tmp_path / "run"
    run_root.mkdir()
    reviewed = _track_changing_review(run_root, monkeypatch)
    store = _store(reviewed, tmp_path)
    jobs = reviewed["service"].store.jobs
    run_id, claim_id = reviewed["run_id"], reviewed["claim_id"]
    with jobs._transaction() as db:
        current = reviewed["claims"].current_tag(TENANT, run_id, claim_id, connection=db)
        assert set(current) == {"tag", "decision", "epoch"}, "current_tag contract drift"
        assert current["epoch"] == jobs._get(db, TENANT, run_id, "run", "META")["mutation_epoch"]
        head = jobs._get(db, TENANT, run_id, "claim_head", claim_id)
        assert current["tag"]["tag_revision"] == head["tag_revision"] == 2
        assert current["tag"]["confirmed_tags"]["track"] == "management"
        original = json.loads(
            jobs._raw(db, TENANT, run_id, "tag_revision", f"{claim_id}:0000000001")
        )
        assert original["inputs"]["packet"]["track"] == "performance"
        assert store._reviewed_head(db, TENANT, run_id, reviewed["claim"]) == {
            "tag_revision": 2,
            "track": "management",
        }, "reconciliation must consume atomic reviewed head, never preliminary inputs"
        decision = jobs._get(
            db, TENANT, run_id, "decision_revision", f"{claim_id}:{head['decision_revision']:010}"
        )
        assert current["decision"] == decision["api"], "current_tag must expose API decision"
        assert reviewed["claims"].current_tag(TENANT, run_id, "missing", connection=db) is None


@pytest.mark.parametrize(
    "track,element,fact",
    [
        ("goal", "G4", "org_boundary"),
        ("management", "M2", "org_boundary"),
        ("performance", "P1", "quantitative_or_qualified_ordinal"),
    ],
)
def test_mapping_facts_still_feed_reconciliation_triggers(track, element, fact):
    from proofops.application.linkage_exchange import TRIGGER_TAG_MAP

    assert set(MAPPINGS) == {"goal", "performance", "management"}, "known track contract drift"
    assert fact in MAPPINGS[track][element], f"{track}.{element} lost reconciliation fact {fact}"
    expected = "quantitative_value" if track == "performance" else "organizational_boundary"
    assert TRIGGER_TAG_MAP[fact] == expected, "rubric fact no longer maps to C-item trigger"
