"""A busy writer is not a lost lease; waiting must not resurrect an expired one."""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from proofops.adapters.local import job_store
from proofops.application.ports.jobs import LeaseLost

from tests.acceptance.test_jobs import MESSAGE, RUN, TENANT, seeded


def blocked_heartbeat(tmp_path, *, lease_seconds, hold_seconds):
    path = tmp_path / "jobs.sqlite"
    store = seeded(path)
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=lease_seconds)
    started = Event()

    def renew():
        started.set()
        return store.heartbeat(lease, now=100, lease_seconds=lease_seconds)

    with sqlite3.connect(path, isolation_level=None) as writer, ThreadPoolExecutor(1) as pool:
        writer.execute("BEGIN IMMEDIATE")
        future = pool.submit(renew)
        assert started.wait(1)
        time.sleep(hold_seconds)
        writer.commit()
        return future.result(timeout=5)


def test_busy_writer_does_not_fail_a_still_valid_heartbeat(tmp_path):
    renewed = blocked_heartbeat(tmp_path, lease_seconds=300, hold_seconds=12)
    assert renewed.lease_until >= 412


def test_waiting_heartbeat_cannot_renew_an_expired_lease(tmp_path):
    with pytest.raises(LeaseLost):
        blocked_heartbeat(tmp_path, lease_seconds=1, hold_seconds=1.2)


@pytest.mark.parametrize("change", ["cancel", "owner", "fence", "attempt"])
def test_waiting_heartbeat_rechecks_persisted_authority(tmp_path, change):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)
    with ThreadPoolExecutor(1) as pool:
        with store._transaction() as db:
            future = pool.submit(store.heartbeat, lease, now=100, lease_seconds=300)
            # Keep the writer past the short renewal busy timeout.
            time.sleep(0.4)
            if change == "cancel":
                run = store._get(db, TENANT, RUN, "run", "META")
                run["cancellation_requested"] = True
                store._put(db, TENANT, RUN, "run", "META", run)
            else:
                job = store._job(db, MESSAGE)
                field = {"owner": "lease_owner", "fence": "fencing_token", "attempt": "attempt"}
                job[field[change]] = "replacement" if change == "owner" else 2
                store._save_job(db, MESSAGE, job)
        with pytest.raises(LeaseLost):
            future.result(timeout=3)
    assert not store.commit_job(lease, payload=b"stale", now=101)
    assert store.read_checkpoint(MESSAGE) is None


@pytest.mark.parametrize("code", [sqlite3.SQLITE_IOERR, sqlite3.SQLITE_LOCKED, None])
def test_non_busy_storage_errors_are_not_retried(tmp_path, monkeypatch, code):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)
    calls = []

    def fail(*args):
        calls.append(1)
        error = sqlite3.OperationalError("private error detail")
        if code is not None:
            error.sqlite_errorcode = code
        raise error

    monkeypatch.setattr(store, "_save_job", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.heartbeat(lease, now=101, lease_seconds=300)
    assert len(calls) == 1
    assert store.get_job(MESSAGE)["heartbeat_at"] == 100


def test_busy_retry_is_bounded_without_replaying_other_operations(tmp_path, monkeypatch):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)
    elapsed, attempts = [0.0], []

    def advance(seconds):
        elapsed[0] += seconds

    @contextmanager
    def busy(*, timeout):
        attempts.append(timeout)
        advance(timeout)
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr(store, "_transaction", busy)
    monkeypatch.setattr(
        job_store, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=advance)
    )
    with pytest.raises(sqlite3.OperationalError):
        store.heartbeat(lease, now=101, lease_seconds=300)
    assert len(attempts) > 1
    assert 30 <= elapsed[0] <= 30.25


def test_redundant_point_renewals_do_not_rewrite_identical_lease(tmp_path, monkeypatch):
    """SPT counts/reserves/invokes in parallel, often in the same clock second."""
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)
    writes = []
    save = store._save_job

    def recorded(db, message, job):
        writes.append((job["heartbeat_at"], job["lease_until"]))
        return save(db, message, job)

    monkeypatch.setattr(store, "_save_job", recorded)
    for _ in range(32):
        assert store.heartbeat(lease, now=101, lease_seconds=300).lease_until == 401
    assert writes == [(101, 401)]
    # A larger requested duration is a real renewal even in the same second.
    assert store.heartbeat(lease, now=101, lease_seconds=400).lease_until == 501
    assert writes == [(101, 401), (101, 501)]


def test_parallel_heartbeats_have_one_sqlite_waiter(tmp_path, monkeypatch):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)
    transaction = store._transaction
    counts = dict(active=0, peak=0)
    counter_lock = Lock()

    @contextmanager
    def observed(**kwargs):
        with counter_lock:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            # Represents a writer/commit delay; peers must queue before SQLite.
            time.sleep(0.02)
            with transaction(**kwargs) as db:
                yield db
        finally:
            with counter_lock:
                counts["active"] -= 1

    monkeypatch.setattr(store, "_transaction", observed)
    with ThreadPoolExecutor(16) as pool:
        renewed = list(
            pool.map(lambda _: store.heartbeat(lease, now=101, lease_seconds=300), range(32))
        )
    assert all(r.lease_until >= 401 for r in renewed)
    assert counts == dict(active=0, peak=1)


def test_heartbeat_queue_wait_counts_toward_expiry(tmp_path):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=1)
    with ThreadPoolExecutor(1) as pool:
        store._heartbeat_lock.acquire()
        try:
            future = pool.submit(store.heartbeat, lease, now=100, lease_seconds=300)
            time.sleep(1.2)
        finally:
            store._heartbeat_lock.release()
        with pytest.raises(LeaseLost):
            future.result(timeout=2)
    assert store.get_job(MESSAGE)["lease_until"] == 101


def test_heartbeat_queue_timeout_is_busy_without_entering_sqlite(tmp_path, monkeypatch):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)

    def denied(*, timeout):
        assert timeout == 30
        return False

    monkeypatch.setattr(store, "_heartbeat_lock", SimpleNamespace(acquire=denied))
    monkeypatch.setattr(store, "_transaction", lambda **_: pytest.fail("must not enter SQLite"))
    with pytest.raises(sqlite3.OperationalError) as raised:
        store.heartbeat(lease, now=101, lease_seconds=300)
    assert raised.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
