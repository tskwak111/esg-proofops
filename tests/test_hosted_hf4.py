"""Hosted contention must not resurrect leases, serialize reads or lose counters."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from proofops_api.hosted_analysis import HostedOpenAILunaProbe
from proofops_api.hosted_store import HostedError

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def setup(tmp_path):
    return job_setup(_settings.__wrapped__(tmp_path))


def test_renewal_survives_writer_longer_than_normal_acquisition_budget(setup):
    store, _, job = setup
    started = time.time()
    with sqlite3.connect(store.path, isolation_level=None) as writer, ThreadPoolExecutor(1) as pool:
        writer.execute("BEGIN IMMEDIATE")
        future = pool.submit(store.renew_lease, job, now=started)
        time.sleep(11)
        writer.commit()
        future.result(timeout=5)
    assert job["lease_until"] >= started + 1900 + 11


def test_renewal_rechecks_expiry_after_acquiring_writer(setup):
    store, _, job = setup
    now = time.time()
    with store.transaction() as db:
        db.execute("UPDATE runs SET lease_until=? WHERE run_id=?", (now + 0.2, job["run_id"]))
    with sqlite3.connect(store.path, isolation_level=None) as writer, ThreadPoolExecutor(1) as pool:
        writer.execute("BEGIN IMMEDIATE")
        future = pool.submit(store.renew_lease, job, now=now)
        time.sleep(0.4)
        writer.commit()
        with pytest.raises(HostedError, match="LEASE_LOST"):
            future.result(timeout=2)


def test_dispatch_cannot_spend_a_lease_that_expired_while_waiting(setup):
    from decimal import Decimal

    store, _, job = setup
    now = time.time()
    calls = []
    with store.transaction() as db:
        db.execute("UPDATE runs SET lease_until=? WHERE run_id=?", (now + 0.2, job["run_id"]))
    with sqlite3.connect(store.path, isolation_level=None) as writer, ThreadPoolExecutor(1) as pool:
        writer.execute("BEGIN IMMEDIATE")
        future = pool.submit(
            store.dispatch,
            job,
            "fake",
            "expired",
            "a" * 64,
            Decimal(".01"),
            lambda request: calls.append(request),
            now=now,
        )
        time.sleep(0.4)
        writer.commit()
        with pytest.raises(HostedError, match="LEASE_LOST"):
            future.result(timeout=2)
    assert calls == []
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0


def test_inner_heartbeat_diagnostic_keeps_first_cause_without_private_error_text():
    from proofops_worker.consumer import LeaseHeartbeatState

    state = LeaseHeartbeatState(100)
    error = sqlite3.OperationalError("private SQL, path and credential")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    state.fail(error)
    state.fail(ValueError("later failure"))
    assert state.failure == dict(
        database="job_state", source="point", exception_type="OperationalError", sqlite_errorcode=5
    )


@pytest.mark.parametrize("change", ["cancel", "fence", "delete"])
def test_waiting_renewal_rechecks_authority(setup, change):
    store, _, job = setup
    with ThreadPoolExecutor(1) as pool:
        with store.transaction() as db:
            future = pool.submit(store.renew_lease, job, now=time.time())
            time.sleep(0.35)
            if change == "cancel":
                db.execute("UPDATE runs SET status='cancelled' WHERE run_id=?", (job["run_id"],))
            elif change == "fence":
                db.execute("UPDATE runs SET fence=fence+1 WHERE run_id=?", (job["run_id"],))
            else:
                db.execute("DELETE FROM documents WHERE document_id=?", (job["document_id"],))
        with pytest.raises(HostedError):
            future.result(timeout=2)


def test_response_authorization_does_not_acquire_a_writer(setup):
    store, _, job = setup
    probe = HostedOpenAILunaProbe.__new__(HostedOpenAILunaProbe)
    probe.store, probe.job = store, job
    with sqlite3.connect(store.path, isolation_level=None) as writer, ThreadPoolExecutor(1) as pool:
        writer.execute("BEGIN IMMEDIATE")
        future = pool.submit(probe._authorize_response_request)
        try:
            future.result(timeout=1)
        finally:
            writer.rollback()
    store.cancel(setup[1], job["run_id"], now=time.time())
    with pytest.raises(HostedError, match="LEASE_LOST"):
        probe._authorize_response_request()


def test_initial_snapshot_file_io_does_not_hold_writer(setup, tmp_path, monkeypatch):
    store, _, job = setup
    state = tmp_path / "state"
    state.mkdir()
    (state / "outcome.json").write_text("{}")
    from proofops_api import hosted_results

    monkeypatch.setattr(hosted_results, "result_snapshot", lambda *a: b'{"snapshot":true}')
    entered, release = threading.Event(), threading.Event()
    original = store._write

    def write(path, content):
        if path.name == "result-1.json":
            entered.set()
            assert release.wait(5)
        return original(path, content)

    monkeypatch.setattr(store, "_write", write)
    with ThreadPoolExecutor(2) as pool:
        publication = pool.submit(store.publish_analysis, job, state, "completed", None)
        try:
            assert entered.wait(2)
            pool.submit(store.renew_lease, job, now=time.time()).result(timeout=1)
        finally:
            release.set()
        publication.result(timeout=3)
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT count(*) FROM result_snapshots").fetchone()[0] == 1


def test_batched_claim_progress_is_exact_and_flushes_last_partial_batch(setup, monkeypatch):
    from proofops_api.hosted_progress import ClaimProgress

    store, auth, job = setup
    calls = []
    original = store.update_progress

    def observed(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "update_progress", observed)
    progress = ClaimProgress(store, job)
    with ThreadPoolExecutor(16) as pool:

        def complete(i):
            for stage in ("preliminary", "relation", "elements"):
                progress.stage(str(i), 136, stage)
            progress.claim(str(i), 136)

        list(pool.map(complete, range(136)))
    progress.flush()
    row = store.get_run(auth.tenant_id, job["run_id"])
    assert row["claims_extracted"] == row["claims_processed"] == 136
    assert row["claim_stage_counts"] == dict(preliminary=136, relation=136, elements=136)
    assert len(calls) < 20
    assert any(c.get("claims_processed") == 1 for c in calls)
    store.cancel(auth, job["run_id"], now=time.time())
    progress.stage("extra", 137, "preliminary")
    with pytest.raises(HostedError, match="LEASE_LOST"):
        progress.flush()
