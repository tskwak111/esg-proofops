"""Immutable parser inputs and note request lifecycle for local jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType
    from typing import Any

    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.application.ports.jobs import JobLease, JobMessage


def bind_parser_note_policy(
    self: LocalSQLiteJobStore, lease: JobLease, policy: dict[str, Any] | None, *, now: int
) -> None:
    from proofops.adapters.local import job_store as _job_store

    self._time(now)
    message = lease.message
    if message.stage != "parse":
        raise ValueError("parser policy requires parse stage")
    with self._transaction() as db:
        if self._owned(db, lease, now) is None:
            raise _job_store.LeaseLost("LEASE_LOST")
        raw = self._raw(db, message.tenant_id, message.run_id, "parser_note_policy", message.job_id)
        if raw is not None:
            if _job_store.json.loads(raw) != policy:
                raise ValueError("NOTE_REVIEW_POLICY_MISMATCH")
        else:
            self._put(
                db,
                message.tenant_id,
                message.run_id,
                "parser_note_policy",
                message.job_id,
                policy,
                immutable=True,
            )


def parser_note_policy(self: LocalSQLiteJobStore, message: JobMessage) -> dict[str, Any] | None:
    from proofops.adapters.local import job_store as _job_store

    with self._transaction() as db:
        self._job(db, message)
        raw = self._raw(db, message.tenant_id, message.run_id, "parser_note_policy", message.job_id)
        return None if raw is None else _job_store.json.loads(raw)


def bind_parser_native_policy(
    self: LocalSQLiteJobStore, lease: JobLease, policy: dict[str, Any] | None, *, now: int
) -> None:
    from proofops.adapters.local import job_store as _job_store

    self._time(now)
    message = lease.message
    if message.stage != "parse":
        raise ValueError("parser policy requires parse stage")
    from proofops.adapters.local.run_artifacts import native_paragraph_policy

    if policy is not None and policy != native_paragraph_policy():
        from proofops.adapters.local.claim_source_policies import (
            page_ocr_profile as _page_ocr_profile,
        )

        page_ocr_profile: Callable[..., ModuleType] = _page_ocr_profile

        mode = policy.get("mode") if isinstance(policy, dict) else None
        try:
            expected = page_ocr_profile(mode, policy=policy, native=True).native_policy()
        except ValueError:
            raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH") from None
        if policy != expected:
            raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
    with self._transaction() as db:
        if self._owned(db, lease, now) is None:
            raise _job_store.LeaseLost("LEASE_LOST")
        raw = self._raw(
            db, message.tenant_id, message.run_id, "parser_native_policy", message.job_id
        )
        if raw is not None:
            if _job_store.json.loads(raw) != policy:
                raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
        else:
            self._put(
                db,
                message.tenant_id,
                message.run_id,
                "parser_native_policy",
                message.job_id,
                policy,
                immutable=True,
            )


def parser_native_policy(self: LocalSQLiteJobStore, message: JobMessage) -> dict[str, Any] | None:
    from proofops.adapters.local import job_store as _job_store

    with self._transaction() as db:
        self._job(db, message)
        raw = self._raw(
            db, message.tenant_id, message.run_id, "parser_native_policy", message.job_id
        )
        return None if raw is None else _job_store.json.loads(raw)


def register_parser_note_request(
    self: LocalSQLiteJobStore, lease: JobLease, request_id: str, *, now: int
) -> None:
    from proofops.adapters.local import job_store as _job_store

    self._time(now)
    _job_store._require_uuid("request_id", request_id)
    message = lease.message
    with self._transaction() as db:
        if message.stage != "parse" or self._owned(db, lease, now) is None:
            raise _job_store.LeaseLost("LEASE_LOST")
        self._put(
            db,
            message.tenant_id,
            message.run_id,
            "parser_note_request",
            message.job_id + ":" + request_id,
            dict(request_id=request_id, fencing_token=lease.fencing_token, owner=lease.owner),
            immutable=True,
        )


def finish_parser_note_request(self: LocalSQLiteJobStore, lease: JobLease, request_id: str) -> None:
    """Retain return evidence even if ownership expired during the HTTP call."""
    from proofops.adapters.local import job_store as _job_store

    message = lease.message
    key = message.job_id + ":" + request_id
    with self._transaction() as db:
        registered = self._get(db, message.tenant_id, message.run_id, "parser_note_request", key)
        if registered != dict(
            request_id=request_id, fencing_token=lease.fencing_token, owner=lease.owner
        ):
            raise _job_store.LeaseLost("unknown note request owner")
        if self._raw(db, message.tenant_id, message.run_id, "parser_note_return", key) is None:
            self._put(
                db,
                message.tenant_id,
                message.run_id,
                "parser_note_return",
                key,
                registered,
                immutable=True,
            )


def parser_note_requests(
    self: LocalSQLiteJobStore, message: JobMessage, *, returned: bool = False
) -> tuple[str, ...]:
    from proofops.adapters.local import job_store as _job_store

    with self._transaction() as db:
        self._job(db, message)
        return tuple(
            _job_store.json.loads(row[0])["request_id"]
            for row in db.execute(
                "SELECT value FROM job_records WHERE tenant_id=? AND run_id=? "
                "AND kind=? AND record_id LIKE ? ORDER BY record_id",
                (
                    message.tenant_id,
                    message.run_id,
                    "parser_note_return" if returned else "parser_note_request",
                    message.job_id + ":%",
                ),
            )
        )


def bind_parser_note_reviews(
    self: LocalSQLiteJobStore, lease: JobLease, artifacts: tuple[str, ...], *, now: int
) -> tuple[str, ...]:
    from proofops.adapters.local import job_store as _job_store

    self._time(now)
    message = lease.message
    if message.stage != "parse" or not isinstance(artifacts, tuple):
        raise ValueError("invalid parser note input")
    if any(
        not isinstance(item, str) or len(item.encode("utf-8")) > 16 * 1024 * 1024
        for item in artifacts
    ):
        raise ValueError("invalid parser note input")
    with self._transaction() as db:
        if self._owned(db, lease, now) is None:
            raise _job_store.LeaseLost("LEASE_LOST")
        raw = self._raw(db, message.tenant_id, message.run_id, "parser_note_input", message.job_id)
        if raw is not None:
            pinned = tuple(_job_store.json.loads(raw))
            if artifacts and artifacts != pinned:
                raise ValueError("NOTE_REVIEW_INPUT_ALREADY_BOUND")
            return pinned
        self._put(
            db,
            message.tenant_id,
            message.run_id,
            "parser_note_input",
            message.job_id,
            list(artifacts),
            immutable=True,
        )
        return artifacts


def parser_note_reviews(self: LocalSQLiteJobStore, message: JobMessage) -> tuple[str, ...] | None:
    from proofops.adapters.local import job_store as _job_store

    with self._transaction() as db:
        self._job(db, message)
        raw = self._raw(db, message.tenant_id, message.run_id, "parser_note_input", message.job_id)
        return None if raw is None else tuple(_job_store.json.loads(raw))
