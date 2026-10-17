"""A skipped point renewal cannot extend a lease or bypass persisted ownership."""

import sqlite3
from threading import Event

import pytest
from proofops.application.ports.jobs import LeaseLost
from proofops_worker.consumer import (
    LeaseHeartbeatState,
    StageFailure,
    TagHeartbeatFailed,
    point_heartbeat,
    with_lease_heartbeat,
)

from tests.acceptance.test_jobs import MESSAGE, RUN, TENANT, seeded


def busy():
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


def fixture(tmp_path, monkeypatch):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=300)
    state = LeaseHeartbeatState(100)
    clock = [101]
    heartbeat = store.heartbeat

    def fail(*args, **kwargs):
        raise busy()

    monkeypatch.setattr(store, "heartbeat", fail)
    return store, lease, state, clock, heartbeat


def test_busy_points_do_not_advance_success_or_expiry_and_next_renewal_recovers(
    tmp_path, monkeypatch
):
    store, lease, state, clock, heartbeat = fixture(tmp_path, monkeypatch)
    for _ in range(3):
        point_heartbeat(store, lease, lambda: clock[0], state=state)
    assert not state.failed.is_set()
    assert (state.last_successful_at, state.renewed_until) == (100, 0)
    assert store.get_job(MESSAGE)["lease_until"] == 400
    monkeypatch.setattr(store, "heartbeat", heartbeat)
    point_heartbeat(store, lease, lambda: clock[0], state=state)
    assert (state.last_successful_at, state.renewed_until) == (101, 401)


@pytest.mark.parametrize("remaining", [120, 119, 0])
def test_busy_requires_full_remaining_margin(tmp_path, monkeypatch, remaining):
    store, lease, state, clock, _ = fixture(tmp_path, monkeypatch)
    clock[0] = 400 - remaining
    if remaining == 120:
        point_heartbeat(store, lease, lambda: clock[0], state=state)
    else:
        with pytest.raises(LeaseLost if remaining == 0 else sqlite3.OperationalError):
            point_heartbeat(store, lease, lambda: clock[0], state=state)


@pytest.mark.parametrize("change", ["cancel", "owner", "fence", "attempt", "status", "expiry"])
def test_busy_fallback_rechecks_all_persisted_guards(tmp_path, monkeypatch, change):
    store, lease, state, clock, _ = fixture(tmp_path, monkeypatch)
    with store._transaction() as db:
        if change == "cancel":
            run = store._get(db, TENANT, RUN, "run", "META")
            run["cancellation_requested"] = True
            store._put(db, TENANT, RUN, "run", "META", run)
        else:
            job = store._job(db, MESSAGE)
            field, value = {
                "owner": ("lease_owner", "replacement"),
                "fence": ("fencing_token", 2),
                "attempt": ("attempt", 2),
                "status": ("status", "completed"),
                "expiry": ("lease_until", 101),
            }[change]
            job[field] = value
            store._save_job(db, MESSAGE, job)
    with pytest.raises(LeaseLost):
        point_heartbeat(store, lease, lambda: clock[0], state=state)
    assert not store.commit_job(lease, payload=b"stale", now=clock[0])
    assert store.read_checkpoint(MESSAGE) is None


def test_margin_accounts_for_time_spent_in_can_call(tmp_path, monkeypatch):
    store, lease, state, clock, _ = fixture(tmp_path, monkeypatch)
    can_call = store.can_call

    def slow_check(*args, **kwargs):
        result = can_call(*args, **kwargs)
        clock[0] = 281
        return result

    monkeypatch.setattr(store, "can_call", slow_check)
    with pytest.raises(sqlite3.OperationalError):
        point_heartbeat(store, lease, lambda: clock[0], state=state)


def test_successful_renewal_uses_confirmed_expiry_not_completion_clock(tmp_path, monkeypatch):
    store, lease, state, clock, heartbeat = fixture(tmp_path, monkeypatch)

    def slow_success(*args, **kwargs):
        renewed = heartbeat(*args, **kwargs)
        clock[0] += 40
        return renewed

    monkeypatch.setattr(store, "heartbeat", slow_success)
    point_heartbeat(store, lease, lambda: clock[0], state=state)
    assert state.last_successful_at == 101
    assert state.renewed_until == 401


def test_busy_cannot_clear_a_racing_fatal_stop(tmp_path, monkeypatch):
    store, lease, state, clock, _ = fixture(tmp_path, monkeypatch)
    can_call = store.can_call

    def fail_during_check(*args, **kwargs):
        result = can_call(*args, **kwargs)
        state.fail(LeaseLost())
        return result

    monkeypatch.setattr(store, "can_call", fail_during_check)
    with pytest.raises(TagHeartbeatFailed):
        point_heartbeat(store, lease, lambda: clock[0], state=state)


@pytest.mark.parametrize("code", [sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR, None])
def test_non_busy_is_never_deferred(tmp_path, monkeypatch, code):
    store, lease, state, clock, _ = fixture(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        error = busy()
        error.sqlite_errorcode = code
        raise error

    monkeypatch.setattr(store, "heartbeat", fail)
    with pytest.raises(sqlite3.OperationalError):
        point_heartbeat(store, lease, lambda: clock[0], state=state)


def test_busy_ownership_read_is_not_permission_to_continue(tmp_path, monkeypatch):
    store, lease, state, clock, _ = fixture(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise busy()

    monkeypatch.setattr(store, "can_call", fail)
    with pytest.raises(sqlite3.OperationalError):
        point_heartbeat(store, lease, lambda: clock[0], state=state)


def test_background_busy_still_fails_closed(tmp_path, monkeypatch):
    store = seeded(tmp_path / "jobs.sqlite")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=3)
    state = LeaseHeartbeatState(100)
    attempted = Event()

    def fail(*args, **kwargs):
        attempted.set()
        raise busy()

    def operation(_lease):
        assert attempted.wait(3)
        return b"unpublished", {}

    monkeypatch.setattr(store, "heartbeat", fail)
    with pytest.raises(StageFailure, match="LEASE_HEARTBEAT_FAILED"):
        with_lease_heartbeat(store, lease, lambda: 100, operation, state=state)
    assert state.failed.is_set()
    assert state.failure["source"] == "background"
    assert state.failure["sqlite_errorcode"] == sqlite3.SQLITE_BUSY
