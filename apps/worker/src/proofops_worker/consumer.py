"""Fenced worker operations. The repository owns every atomic state transition."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from random import random
from threading import Event, Lock, Thread
from typing import Any

from proofops.application.ports.jobs import (
    JobControlSignal,
    JobLease,
    JobMessage,
    JobRepository,
    LeaseLost,
)
from proofops.domain.values import _require_strict_int


class StageFailure(Exception):
    """Adapter-classified failure, with usage retained even when publication is fenced."""

    def __init__(
        self, error_code: str, *, usage: dict[str, Any], retry_after: int | None = None
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.usage = usage
        self.retry_after = retry_after


class TagHeartbeatFailed(JobControlSignal):
    """Stop tagging outside provider-error handlers after a failed renewal."""


def heartbeat_failure(error, *, source):
    # Persist a cause even when the hosted subprocess's stderr is discarded.
    # Exception messages, SQL, paths, lease identifiers and credentials stay out.
    code = getattr(error, "sqlite_errorcode", None)
    return dict(
        database="job_state",
        source=source,
        exception_type=type(error).__name__,
        sqlite_errorcode=code if type(code) is int else None,
    )


@dataclass
class LeaseHeartbeatState:
    last_successful_at: int
    failed: Event = field(default_factory=Event)
    lock: Any = field(default_factory=Lock)
    failure: dict | None = None
    renewed_until: int = 0

    def fail(self, error=None):
        with self.lock:
            if not self.failed.is_set() and error is not None:
                self.failure = heartbeat_failure(error, source="point")
            self.failed.set()

    def check(self):
        if self.failed.is_set():
            raise TagHeartbeatFailed()


def point_heartbeat(store, lease, clock, *, state=None, lease_seconds=300):
    """Defer only an exhausted BUSY renewal while persisted authority is still valid.

    120 seconds leaves a 30s keepalive interval, a 30s renewal budget, a 30s
    ownership-read budget and 30s headroom. This is no lease extension: only
    an actual successful renewal advances the remembered expiry. Every fallback
    must freshly pass can_call, including owner/cancel/attempt/fence/expiry.
    """
    if state is not None:
        state.check()
    now = int(clock())
    try:
        renewed = store.heartbeat(lease, now=now, lease_seconds=lease_seconds)
    except sqlite3.OperationalError as error:
        code = getattr(error, "sqlite_errorcode", None)
        if type(code) is not int or code & 0xFF != sqlite3.SQLITE_BUSY:
            raise
        if not store.can_call(lease, now=int(clock())):
            raise LeaseLost("LEASE_LOST") from None
        if state is None:
            remaining = lease.lease_until - int(clock())
        else:
            with state.lock:
                state.check()
                remaining = max(lease.lease_until, state.renewed_until) - int(clock())
        if remaining < 120:
            raise
        return
    if state is not None:
        with state.lock:
            state.last_successful_at = max(state.last_successful_at, now)
            if isinstance(renewed, JobLease):
                state.renewed_until = max(state.renewed_until, renewed.lease_until)
            state.check()


def with_lease_heartbeat(store, lease, clock, operation, *, state=None):
    """Renew only this lease for the duration of a long operation.

    A single heartbeat taken before an expensive step (for example claim-span
    attestation growing with the run's accumulated processed count) does not
    cover work that outlives the lease window: the lease can expire while the
    step is still running, and the eventual commit is then silently discarded
    even though the operation itself succeeded. This starts a background
    keepalive that re-heartbeats on a short cadence for exactly the duration of
    ``operation``, so the lease stays valid until the caller's own commit-time
    fencing check runs. Any renewal failure (lease lost/fenced out) fails the
    operation closed instead of letting a stale lease publish.
    """
    lease_seconds = max(1, lease.lease_until - int(clock()))
    stopped = Event()
    state = state or LeaseHeartbeatState(int(clock()))

    def keepalive():
        while not stopped.wait(min(30, lease_seconds / 3)):
            with state.lock:
                if state.failed.is_set():
                    return
                try:
                    now = int(clock())
                    renewed = store.heartbeat(lease, now=now, lease_seconds=lease_seconds)
                except Exception as error:
                    # Background work may have no further admission boundary;
                    # unlike a point renewal, keepalive failures remain fatal.
                    state.failure = heartbeat_failure(error, source="background")
                    state.failed.set()
                    return
                state.last_successful_at = max(state.last_successful_at, now)
                if isinstance(renewed, JobLease):
                    state.renewed_until = max(state.renewed_until, renewed.lease_until)

    thread = Thread(target=keepalive, name=f"lease-heartbeat:{lease.message.job_id}")
    thread.start()
    try:
        payload, usage = operation(lease)
    finally:
        stopped.set()
        thread.join()
    # Join before checking, including a renewal racing with operation completion.
    # The consumer's commit still performs the final ownership/cancellation fence.
    if state.failed.is_set():
        raise StageFailure("LEASE_HEARTBEAT_FAILED", usage=usage)
    return payload, usage


def claim_job(
    store: JobRepository, message: JobMessage, *, owner: str, now: int, lease_seconds: int
) -> JobLease | None:
    return store.claim_job(message, owner=owner, now=now, lease_seconds=lease_seconds)


def commit_job(
    store: JobRepository,
    lease: JobLease,
    *,
    payload: bytes,
    now: int,
    next_job: JobMessage | None = None,
) -> bool:
    return store.commit_job(lease, payload=payload, now=now, next_job=next_job)


def consume_job(
    store: JobRepository,
    message: JobMessage,
    *,
    owner: str,
    clock: Callable[[], int],
    lease_seconds: int,
    operation: Callable[[JobLease], tuple[bytes, dict[str, Any]]],
    next_job: JobMessage | None = None,
    receive_count: int = 1,
    jitter: Callable[[], float] = random,
) -> str:
    """One delivery; each operation makes one authorized external call at most.

    Check cancellation immediately before starting. An in-flight cancellation
    cannot stop a provider, so retain usage and let the commit transaction reject
    publication. Unexpected exceptions propagate without acknowledgement; lease
    expiry allows recovery. Transport acknowledgement belongs to the caller:
    deferred deliveries MUST retain/redelay the message until lease recovery,
    while committed/ignored are safe to acknowledge. Retry is durably re-enqueued.
    """
    if _require_strict_int("receive_count", receive_count) < 1:
        raise ValueError("receive_count must be positive")
    lease = claim_job(store, message, owner=owner, now=clock(), lease_seconds=lease_seconds)
    if lease is None:
        return "deferred" if store.delivery_status(message) in {"pending", "leased"} else "ignored"
    if not store.can_call(lease, now=clock()):
        return "discarded"
    try:
        if receive_count > 5:
            raise StageFailure("SQS_RECEIVE_LIMIT", usage={})
        payload, usage = operation(lease)
    except StageFailure as failure:
        store.record_usage(lease, failure.usage)
        try:
            job = store.fail_job(
                lease,
                error_code=failure.error_code,
                now=clock(),
                jitter=jitter(),
                retry_after=failure.retry_after,
            )
        except LeaseLost:
            return "discarded"
        return "retry" if job["status"] == "pending" else "failed"
    store.record_usage(lease, usage)
    committed = commit_job(store, lease, payload=payload, now=clock(), next_job=next_job)
    return "committed" if committed else "discarded"
