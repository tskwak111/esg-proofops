"""Frozen SQLite bytes and call boundaries before the S_ADA store extraction."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from proofops.adapters.local import job_store
from proofops.application.ports.jobs import JobConflict, LeaseLost

from tests.acceptance.test_jobs import MESSAGE, RUN, TENANT, VERSION, seeded


def record_digest(path: Path) -> str:
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT tenant_id,run_id,kind,record_id,hex(value) FROM job_records "
            "ORDER BY tenant_id,run_id,kind,record_id"
        ).fetchall()
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def test_checkpoint_bytes_fence_and_atomic_enqueue(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    store = seeded(path)
    old = store.claim_job(MESSAGE, owner="old", now=0, lease_seconds=10)
    assert old is not None
    lease = store.claim_job(MESSAGE, owner="new", now=10, lease_seconds=10)
    assert lease is not None
    next_job = replace(MESSAGE, job_id="00000000-0000-0000-0000-000000000006", stage="TAG")
    assert not store.commit_job(old, payload=b"stale", now=11)
    assert store.commit_job(lease, payload=b' {"result": "synthetic"}\n', now=11, next_job=next_job)
    assert store.read_checkpoint(MESSAGE) == b' {"result": "synthetic"}\n'
    assert len(store.pending_outbox(TENANT, RUN, now=11)) == 2
    assert record_digest(path) == "763b71e36cc35b51e13332f9d1428a80e958375ea4ca9b098029e910c9c4dfea"


def test_cancel_audit_failure_rolls_back_and_replay_keeps_bytes(tmp_path, monkeypatch):
    path = tmp_path / "jobs.sqlite"
    store = seeded(path)
    before = record_digest(path)
    append = job_store.append_audit_transaction
    calls = []

    def fail_audit(**kwargs):
        db = kwargs["connection"]
        assert db.in_transaction
        assert store._get(db, TENANT, RUN, "run", "META")["status"] == "cancelled"
        calls.append("audit-after-action")
        raise RuntimeError("synthetic audit failure")

    request = dict(
        expected_revision=1,
        idempotency_key="cancel-key-000001",
        reason="synthetic",
        actor_sub="test-actor",
        now=1,
    )
    monkeypatch.setattr(job_store, "append_audit_transaction", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        store.cancel_run(TENANT, RUN, **request)
    assert record_digest(path) == before
    assert calls == ["audit-after-action"]
    monkeypatch.setattr(job_store, "append_audit_transaction", append)
    response = store.cancel_run(TENANT, RUN, **request)
    after = record_digest(path)
    assert store.cancel_run(TENANT, RUN, **request) == response
    assert (
        record_digest(path)
        == after
        == "ba996037d88a0c7e6385f458959b9726dd350c2525accde02351cfd74b6c293e"
    )
    with pytest.raises(JobConflict, match="idempotency key reused"):
        store.cancel_run(TENANT, RUN, **(request | {"reason": "different"}))


def test_parser_binding_usage_and_error_boundaries(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = job_store.LocalSQLiteJobStore(path)
    store.create_run(TENANT, RUN, VERSION)
    message = replace(MESSAGE, stage="parse")
    store.enqueue(message, now=0)
    lease = store.claim_job(message, owner="parser", now=0, lease_seconds=10)
    assert lease is not None
    policy = {"mode": "synthetic", "nested": {"version": 1}}
    store.bind_parser_note_policy(lease, policy, now=1)
    assert store.bind_parser_note_reviews(lease, ("note A",), now=1) == ("note A",)
    assert store.bind_parser_note_reviews(lease, (), now=1) == ("note A",)
    assert store.parser_note_policy(message) == policy
    assert store.parser_note_reviews(message) == ("note A",)
    with pytest.raises(ValueError, match="NOTE_REVIEW_POLICY_MISMATCH"):
        store.bind_parser_note_policy(lease, {"mode": "other"}, now=1)
    request_id = "00000000-0000-0000-0000-000000000007"
    store.register_parser_note_request(lease, request_id, now=1)
    store.finish_parser_note_request(lease, request_id)
    store.record_usage(lease, {"note_request_ids": [request_id], "cost": "0.01"})
    assert store.parser_note_requests(message, returned=True) == (request_id,)
    before = record_digest(path)
    with pytest.raises(ValueError, match="NOTE_REVIEW_POLICY_MISMATCH"):
        store.commit_job(lease, payload=b"{}", now=2)
    with pytest.raises(LeaseLost, match="LEASE_LOST"):
        store.bind_parser_note_policy(lease, policy, now=10)
    assert (
        record_digest(path)
        == before
        == "3904dede115ba15c5b8d207036526686e66e8e7a794b765f53e5d008830e4661"
    )


def test_schema_and_caller_owned_transaction_are_preserved(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = job_store.LocalSQLiteJobStore(path)
    with sqlite3.connect(path, isolation_level=None) as db:
        assert db.execute("SELECT version FROM job_schema").fetchall() == [(1,)]
        with pytest.raises(ValueError, match="active transaction required"):
            store.create_run_transaction(db, TENANT, RUN, VERSION)
        db.execute("BEGIN IMMEDIATE")
        store.create_run_transaction(db, TENANT, RUN, VERSION)
        store.enqueue_transaction(db, MESSAGE, now=0)
        assert db.in_transaction
        db.rollback()
        assert db.execute("SELECT count(*) FROM job_records").fetchone() == (0,)
        db.execute("UPDATE job_schema SET version=2")
    with pytest.raises(JobConflict, match="unsupported job schema version"):
        job_store.LocalSQLiteJobStore(path)
