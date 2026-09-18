"""Fenced worker operations. The repository owns every atomic state transition."""

from __future__ import annotations

from collections.abc import Callable
from random import random
from typing import Any

from proofops.application.ports.jobs import JobLease, JobMessage, JobRepository, LeaseLost
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
