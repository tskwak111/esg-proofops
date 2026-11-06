"""Local-synthetic-only durable jobs. Not a distributed AWS adapter.

SQLite schema v1 is additive and private to this adapter; unknown versions fail
closed. Rollback retains the DB and immutable artifacts with workers stopped.
"""

from __future__ import annotations

import hashlib as hashlib
import json as json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy as deepcopy
from dataclasses import asdict as asdict
from datetime import UTC as UTC
from datetime import datetime as datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL as NAMESPACE_URL
from uuid import uuid5 as uuid5

from proofops.adapters.local import job_store_actions as _job_store_actions
from proofops.adapters.local import job_store_checkpoint as _job_store_checkpoint
from proofops.adapters.local import job_store_parser as _job_store_parser
from proofops.adapters.local.audit_store import append_audit_transaction as append_audit_transaction
from proofops.adapters.local.audit_store import initialize_audit_schema
from proofops.adapters.local.audit_store import read_audit_head as read_audit_head
from proofops.adapters.local.sqlite_busy import connection
from proofops.application.ports.jobs import JobConflict as JobConflict
from proofops.application.ports.jobs import JobLease
from proofops.application.ports.jobs import JobMessage as JobMessage
from proofops.application.ports.jobs import LeaseLost as LeaseLost
from proofops.domain.audit import ChangeSet as ChangeSet
from proofops.domain.provenance import canonical_hash as canonical_hash
from proofops.domain.values import _require_strict_int as _require_strict_int
from proofops.domain.values import _require_uuid as _require_uuid


def version_is_deleted(db: sqlite3.Connection, tenant: str, version_id: str | None) -> bool:
    if (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='retention_tombstones'"
        ).fetchone()
        is None
    ):
        return False
    return (
        db.execute(
            "SELECT 1 FROM upload_records v JOIN retention_tombstones t "
            "ON t.tenant_id=v.tenant AND t.document_id=json_extract(v.data,'$.document_id') "
            "WHERE v.tenant=? AND v.kind='version' AND v.id=?",
            (tenant, version_id),
        ).fetchone()
        is not None
    )


def run_is_deleted(db: sqlite3.Connection, tenant: str, run_id: str) -> bool:
    row = db.execute(
        "SELECT value FROM job_records WHERE tenant_id=? AND run_id=? "
        "AND kind='run' AND record_id='META'",
        (tenant, run_id),
    ).fetchone()
    return row is not None and version_is_deleted(
        db, tenant, json.loads(row[0])["document_version_id"]
    )


class LocalSQLiteJobStore:
    kind = "local-synthetic-only"

    def __init__(self, path: str | Path) -> None:
        if str(path) == ":memory:":
            raise ValueError("durable jobs require a file-backed database")
        self.path = str(path)
        self._heartbeat_lock = threading.Lock()
        with self._transaction() as db:
            initialize_audit_schema(db)
            db.execute("CREATE TABLE IF NOT EXISTS job_schema (version INTEGER PRIMARY KEY)")
            versions = db.execute("SELECT version FROM job_schema").fetchall()
            if versions and versions != [(1,)]:
                raise JobConflict("unsupported job schema version")
            db.execute("INSERT OR IGNORE INTO job_schema VALUES (1)")
            db.execute("""CREATE TABLE IF NOT EXISTS job_records (
                tenant_id TEXT NOT NULL, run_id TEXT NOT NULL, kind TEXT NOT NULL,
                record_id TEXT NOT NULL, value BLOB NOT NULL,
                PRIMARY KEY (tenant_id, run_id, kind, record_id))""")

    @contextmanager
    def _transaction(self, *, timeout: float = 10) -> Iterator[sqlite3.Connection]:
        # ponytail: one SQLite writer; use DynamoDB transactions for distributed workers.
        if timeout == 10:
            with connection(self.path) as db:
                yield db
            return
        db = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _scope(tenant: str, run: str) -> None:
        _require_uuid("tenant_id", tenant)
        _require_uuid("run_id", run)

    @staticmethod
    def _time(now: int, duration: int = 1) -> None:
        if _require_strict_int("now", now) < 0:
            raise ValueError("now must be non-negative")
        if _require_strict_int("duration", duration) < 1:
            raise ValueError("duration must be positive")

    @staticmethod
    def _raw(db: sqlite3.Connection, tenant: str, run: str, kind: str, key: str) -> bytes | None:
        row = db.execute(
            """SELECT value FROM job_records
            WHERE tenant_id=? AND run_id=? AND kind=? AND record_id=?""",
            (tenant, run, kind, key),
        ).fetchone()
        return None if row is None else row[0]

    def _get(
        self, db: sqlite3.Connection, tenant: str, run: str, kind: str, key: str
    ) -> dict[str, Any]:
        if kind == "run" and run_is_deleted(db, tenant, run):
            raise KeyError("resource not found")
        raw = self._raw(db, tenant, run, kind, key)
        if raw is None:
            raise KeyError("resource not found")
        return_value: dict[str, Any] = json.loads(raw)
        return return_value

    @staticmethod
    def _put(
        db: sqlite3.Connection,
        tenant: str,
        run: str,
        kind: str,
        key: str,
        value: object,
        *,
        immutable: bool = False,
    ) -> None:
        encoded = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        )
        sql = "INSERT" if immutable else "INSERT OR REPLACE"
        db.execute(
            f"{sql} INTO job_records VALUES (?, ?, ?, ?, ?)",
            (tenant, run, kind, key, encoded),
        )

    @staticmethod
    def _all(db: sqlite3.Connection, tenant: str, run: str, kind: str) -> list[dict[str, Any]]:
        return [
            json.loads(row[0])
            for row in db.execute(
                "SELECT value FROM job_records WHERE tenant_id=? AND run_id=? AND kind=?",
                (tenant, run, kind),
            )
        ]

    def create_run(self, tenant_id: str, run_id: str, document_version_id: str) -> None:
        with self._transaction() as db:
            self.create_run_transaction(db, tenant_id, run_id, document_version_id)

    def create_run_transaction(
        self, db: sqlite3.Connection, tenant_id: str, run_id: str, document_version_id: str
    ) -> None:
        """Compose initial job state in a caller-owned transaction; never commit."""
        if not db.in_transaction:
            raise ValueError("active transaction required")
        self._scope(tenant_id, run_id)
        _require_uuid("document_version_id", document_version_id)
        self._put(
            db,
            tenant_id,
            run_id,
            "run",
            "META",
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "document_version_id": document_version_id,
                "status": "queued",
                "revision": 1,
                "mutation_epoch": 0,
                "cancellation_requested": False,
                "execution_profile": self.kind,
            },
            immutable=True,
        )

    def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        self._scope(tenant_id, run_id)
        with self._transaction() as db:
            return self._get(db, tenant_id, run_id, "run", "META")

    def _bump_run(
        self,
        db: sqlite3.Connection,
        run: dict[str, Any],
        status: str | None = None,
        *,
        refresh_claim_counts: bool = False,
    ) -> None:
        if refresh_claim_counts and "coverage" in run:
            coverage = run["coverage"]
            # Keep blocked records without heads and unprocessed work as published.
            processed = coverage["claims_decided"] + coverage["claims_needs_review"]
            decided = db.execute(
                """SELECT count(*) FROM job_records AS head
                JOIN job_records AS decision ON decision.tenant_id=head.tenant_id
                  AND decision.run_id=head.run_id AND decision.kind='decision_revision'
                  AND decision.record_id=head.record_id || ':' || printf('%010d',
                    json_extract(CAST(head.value AS TEXT), '$.decision_revision'))
                WHERE head.tenant_id=? AND head.run_id=? AND head.kind='claim_head'
                  AND json_extract(CAST(decision.value AS TEXT),
                    '$.decision.decision_status')='decided'""",
                (run["tenant_id"], run["run_id"]),
            ).fetchone()[0]
            if decided > processed:
                raise ValueError("decided claims exceed processed coverage")
            coverage.update(claims_decided=decided, claims_needs_review=processed - decided)
        run["revision"] += 1
        run["mutation_epoch"] += 1
        if status is not None:
            run["status"] = status
        self._put(db, run["tenant_id"], run["run_id"], "run", "META", run)

    @staticmethod
    def active_run_count(db: sqlite3.Connection, tenant_id: str) -> int:
        return sum(
            not run_is_deleted(db, tenant_id, row[0])
            for row in db.execute(
                """SELECT run_id FROM job_records WHERE tenant_id=? AND kind='run'
                   AND json_extract(CAST(value AS TEXT), '$.status') IN ('queued', 'running')""",
                (tenant_id,),
            )
        )

    def _job(self, db: sqlite3.Connection, message: JobMessage) -> dict[str, Any]:
        job = self._get(db, message.tenant_id, message.run_id, "job", message.job_id)
        if job["message"] != asdict(message):
            raise KeyError("resource not found")
        return job

    def get_job(self, message: JobMessage) -> dict[str, Any]:
        with self._transaction() as db:
            return self._job(db, message)

    def delivery_status(self, message: JobMessage) -> str:
        try:
            return_value: str = self.get_job(message)["status"]
            return return_value
        except KeyError:
            return "not_found"

    def _save_job(self, db: sqlite3.Connection, message: JobMessage, job: dict[str, Any]) -> None:
        self._put(db, message.tenant_id, message.run_id, "job", message.job_id, job)

    def _enqueue(self, db: sqlite3.Connection, message: JobMessage, now: int) -> None:
        tenant, run_id = message.tenant_id, message.run_id
        run = self._get(db, tenant, run_id, "run", "META")
        if (
            run["cancellation_requested"]
            or run["document_version_id"] != message.document_version_id
        ):
            raise JobConflict("run is cancelled or document version differs")
        for existing in self._all(db, tenant, run_id, "job"):
            previous = existing["message"]
            if previous["job_id"] == message.job_id or (previous["stage"], previous["shard"]) == (
                message.stage,
                message.shard,
            ):
                if previous != asdict(message):
                    raise JobConflict("immutable stage/shard/input identity conflict")
                return
        self._save_job(
            db,
            message,
            {
                "message": asdict(message),
                "status": "pending",
                "attempt": 0,
                "retry_attempt": 0,
                "fencing_token": 0,
                "lease_owner": None,
                "lease_until": None,
                "heartbeat_at": None,
                "artifact_ref": None,
                "error_code": None,
                "next_attempt_at": now,
            },
        )
        self._event(db, message, now, "initial")

    def enqueue(self, message: JobMessage, *, now: int) -> None:
        self._time(now)
        with self._transaction() as db:
            self._enqueue(db, message, now)

    def enqueue_transaction(self, db: sqlite3.Connection, message: JobMessage, *, now: int) -> None:
        """Same engine and connection as enqueue(), without opening a transaction."""
        if not db.in_transaction:
            raise ValueError("active transaction required")
        self._time(now)
        self._enqueue(db, message, now)

    def _event(self, db: sqlite3.Connection, message: JobMessage, now: float, cause: str) -> None:
        event_id = str(uuid5(NAMESPACE_URL, canonical_hash([asdict(message), cause])))
        self._put(
            db,
            message.tenant_id,
            message.run_id,
            "outbox",
            event_id,
            {
                "event_id": event_id,
                "event_type": "stage_ready",
                "job_id": message.job_id,
                "message": asdict(message),
                "status": "pending",
                "next_attempt_at": now,
                "attempts": 0,
            },
            immutable=True,
        )

    def claim_job(
        self, message: JobMessage, *, owner: str, now: int, lease_seconds: int
    ) -> JobLease | None:
        self._time(now, lease_seconds)
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner must be non-empty")
        with self._transaction() as db:
            try:
                job = self._job(db, message)
                run = self._get(db, message.tenant_id, message.run_id, "run", "META")
            except KeyError:
                return None
            if run["cancellation_requested"] or job["next_attempt_at"] > now:
                return None
            if not (
                job["status"] == "pending"
                or (job["status"] == "leased" and job["lease_until"] <= now)
            ):
                return None
            if message.stage == "extract" and "extract_job" in run:
                from proofops.adapters.local.claim_store import guard_extract_continuation

                try:
                    guard_extract_continuation(db, self, run, now=now, supersede=True)
                except ValueError:
                    return None
            job.update(
                status="leased",
                lease_owner=owner,
                lease_until=now + lease_seconds,
                heartbeat_at=now,
                attempt=job["attempt"] + 1,
                fencing_token=job["fencing_token"] + 1,
                retry_attempt=job["retry_attempt"] + 1,
            )
            lease = JobLease(
                message, owner, job["fencing_token"], job["attempt"], job["lease_until"]
            )
            self._save_job(db, message, job)
            self._put(
                db,
                message.tenant_id,
                message.run_id,
                "lease",
                str(lease.fencing_token) + ":" + message.job_id,
                asdict(lease),
                immutable=True,
            )
            self._bump_run(db, run, "running")
            return lease

    def _owned(
        self, db: sqlite3.Connection, lease: JobLease, now: int
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        now += int(getattr(db, "acquire_wait_seconds", 0))
        message = lease.message
        try:
            job = self._job(db, message)
            run = self._get(db, message.tenant_id, message.run_id, "run", "META")
        except KeyError:
            return None
        if (
            run["cancellation_requested"]
            or job["status"] != "leased"
            or job["fencing_token"] != lease.fencing_token
            or job["lease_owner"] != lease.owner
            or job["attempt"] != lease.attempt
            or job["lease_until"] <= now
        ):
            return None
        return job, run

    def can_call(self, lease: JobLease, *, now: int) -> bool:
        self._time(now)
        with self._transaction() as db:
            return self._owned(db, lease, now) is not None

    def heartbeat(self, lease: JobLease, *, now: int, lease_seconds: int) -> JobLease:
        self._time(now, lease_seconds)
        started = time.monotonic()
        # SPT's sibling claims otherwise compete with one another as SQLite
        # writers, repeatedly timing out and retrying the same renewal. Queue
        # them in this worker only; every call still enters SQLite and rechecks
        # persisted authority. Queue time counts toward both expiry and budget.
        if not self._heartbeat_lock.acquire(timeout=30):
            error = sqlite3.OperationalError("heartbeat writer queue busy")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error
        try:
            return self._renew_heartbeat(
                lease, now=now, lease_seconds=lease_seconds, started=started
            )
        finally:
            self._heartbeat_lock.release()

    def _renew_heartbeat(
        self, lease: JobLease, *, now: int, lease_seconds: int, started: float
    ) -> JobLease:
        # Renewal has its own bounded busy path. SPT's ready claims can keep
        # SQLite's single writer busy beyond a normal transaction's ten-second
        # wait without losing the five-minute job lease. Retry only this
        # idempotent renewal, never a provider call or a transaction with usage.
        deadline = started + 30
        while True:
            try:
                with self._transaction(timeout=0.25) as db:
                    # The caller sampled `now` BEFORE waiting for the writer.
                    # Recheck the persisted fence at acquisition time; neither
                    # retries nor a stale JobLease may resurrect an expired job.
                    current = now + int(time.monotonic() - started)
                    owned = self._owned(db, lease, current)
                    if owned is None:
                        raise LeaseLost("LEASE_LOST")
                    job, _ = owned
                    heartbeat_at = max(job["heartbeat_at"], current)
                    lease_until = max(job["lease_until"], current + lease_seconds)
                    # Parallel tag preflight/reserve/invoke boundaries often
                    # renew the same lease in the same second. Keep the writer
                    # fence and fresh _owned check, but do not dirty pages/fsync
                    # an identical record at every boundary. A later timestamp
                    # or longer requested duration still performs the renewal.
                    if (heartbeat_at, lease_until) != (job["heartbeat_at"], job["lease_until"]):
                        job.update(heartbeat_at=heartbeat_at, lease_until=lease_until)
                        self._save_job(db, lease.message, job)
                    return JobLease(
                        lease.message,
                        lease.owner,
                        lease.fencing_token,
                        lease.attempt,
                        job["lease_until"],
                    )
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", None)
                if (
                    code is None
                    or code & 0xFF != sqlite3.SQLITE_BUSY
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))

    def bind_parser_note_policy(
        self, lease: JobLease, policy: dict[str, Any] | None, *, now: int
    ) -> None:
        return _job_store_parser.bind_parser_note_policy(self, lease, policy, now=now)

    def parser_note_policy(self, message: JobMessage) -> dict[str, Any] | None:
        return _job_store_parser.parser_note_policy(self, message)

    def bind_parser_native_policy(
        self, lease: JobLease, policy: dict[str, Any] | None, *, now: int
    ) -> None:
        return _job_store_parser.bind_parser_native_policy(self, lease, policy, now=now)

    def parser_native_policy(self, message: JobMessage) -> dict[str, Any] | None:
        return _job_store_parser.parser_native_policy(self, message)

    def register_parser_note_request(self, lease: JobLease, request_id: str, *, now: int) -> None:
        return _job_store_parser.register_parser_note_request(self, lease, request_id, now=now)

    def finish_parser_note_request(self, lease: JobLease, request_id: str) -> None:
        """Retain return evidence even if ownership expired during the HTTP call."""
        return _job_store_parser.finish_parser_note_request(self, lease, request_id)

    def parser_note_requests(
        self, message: JobMessage, *, returned: bool = False
    ) -> tuple[str, ...]:
        return _job_store_parser.parser_note_requests(self, message, returned=returned)

    def bind_parser_note_reviews(
        self, lease: JobLease, artifacts: tuple[str, ...], *, now: int
    ) -> tuple[str, ...]:
        return _job_store_parser.bind_parser_note_reviews(self, lease, artifacts, now=now)

    def parser_note_reviews(self, message: JobMessage) -> tuple[str, ...] | None:
        return _job_store_parser.parser_note_reviews(self, message)

    def commit_job(
        self,
        lease: JobLease,
        *,
        payload: bytes,
        now: int,
        next_job: JobMessage | None = None,
        publish: Callable[[sqlite3.Connection], None] | None = None,
    ) -> bool:
        return _job_store_checkpoint.commit_job(
            self, lease, payload=payload, now=now, next_job=next_job, publish=publish
        )

    def read_checkpoint(self, message: JobMessage) -> bytes | None:
        with self._transaction() as db:
            ref = self._job(db, message)["artifact_ref"]
            if ref is None:
                return None
            payload = self._raw(db, message.tenant_id, message.run_id, "artifact", ref["key"])
            if (
                payload is None
                or hashlib.sha256(payload).hexdigest() != ref["sha256"]
                or len(payload) != ref["byte_size"]
            ):
                raise JobConflict("checkpoint corruption")
            return payload

    def record_usage(self, lease: JobLease, usage: dict[str, Any]) -> None:
        message = lease.message
        key = str(lease.fencing_token) + ":" + message.job_id
        with self._transaction() as db:
            recorded = self._get(db, message.tenant_id, message.run_id, "lease", key)
            # A renewed lease keeps the original immutable attempt identity.
            candidate = asdict(lease)
            candidate["lease_until"] = recorded["lease_until"]
            if candidate != recorded:
                raise LeaseLost("unknown attempt identity")
            if self._raw(db, message.tenant_id, message.run_id, "usage", key) is not None:
                if self._get(db, message.tenant_id, message.run_id, "usage", key) != usage:
                    raise JobConflict("immutable usage conflict")
                return
            note_ids = usage.get("note_request_ids", [])
            if note_ids:
                if message.stage != "parse" or len(set(note_ids)) != len(note_ids):
                    raise JobConflict("invalid note usage IDs")
                for identifier in note_ids:
                    _require_uuid("request_id", identifier)
                    if (
                        self._raw(
                            db,
                            message.tenant_id,
                            message.run_id,
                            "parser_note_request",
                            message.job_id + ":" + identifier,
                        )
                        is None
                    ):
                        raise JobConflict("note request not registered to job")
                for row in db.execute(
                    "SELECT value FROM job_records WHERE tenant_id=? AND run_id=? AND kind='usage'",
                    (message.tenant_id, message.run_id),
                ):
                    if set(note_ids) & set(json.loads(row[0]).get("note_request_ids", [])):
                        raise JobConflict("note request usage already recorded")
            self._put(db, message.tenant_id, message.run_id, "usage", key, usage, immutable=True)

    def list_usage(self, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        with self._transaction() as db:
            self._get(db, tenant_id, run_id, "run", "META")
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT value FROM job_records WHERE tenant_id=? AND run_id=? AND kind='usage'",
                    (tenant_id, run_id),
                )
            ]

    def get_usage(self, message: JobMessage, *, fencing_token: int) -> dict[str, Any]:
        with self._transaction() as db:
            self._job(db, message)
            return self._get(
                db,
                message.tenant_id,
                message.run_id,
                "usage",
                str(fencing_token) + ":" + message.job_id,
            )

    def fail_job(
        self,
        lease: JobLease,
        *,
        error_code: str,
        now: int,
        jitter: float = 0.5,
        retry_after: int | None = None,
    ) -> dict[str, Any]:
        self._time(now)
        if not isinstance(jitter, int | float) or isinstance(jitter, bool) or not 0 <= jitter <= 1:
            raise ValueError("jitter must be in [0, 1]")
        if not isinstance(error_code, str) or not error_code:
            raise ValueError("error_code required")
        if retry_after is not None:
            self._time(retry_after)
        with self._transaction() as db:
            owned = self._owned(db, lease, now)
            if owned is None:
                raise LeaseLost("LEASE_LOST")
            job, run = owned
            transient = error_code in {
                "MODEL_THROTTLED",
                "PROVIDER_5XX",
                "MODEL_TIMEOUT",
                "NOTE_ACCOUNTING_PENDING",
            }
            retry = transient and job["retry_attempt"] < 3
            delay = (
                min(60, retry_after)
                if retry_after is not None
                else (2 ** job["retry_attempt"] * jitter)
            )
            job.update(
                status="pending" if retry else "failed",
                error_code=error_code,
                next_attempt_at=now + delay,
            )
            self._save_job(db, lease.message, job)
            if retry:
                self._event(db, lease.message, now + delay, f"retry:{lease.fencing_token}")
            self._bump_run(
                db,
                run,
                "running"
                if retry
                else "partial"
                if any(
                    item["status"] == "succeeded"
                    for item in self._all(db, lease.message.tenant_id, lease.message.run_id, "job")
                )
                else "failed",
            )
            return job

    def _action(
        self,
        tenant: str,
        run_id: str,
        *,
        action: str,
        expected_revision: int,
        idempotency_key: str,
        reason: str,
        now: int,
        actor_sub: str,
    ) -> dict[str, Any]:
        return _job_store_actions._action(
            self,
            tenant,
            run_id,
            action=action,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            reason=reason,
            now=now,
            actor_sub=actor_sub,
        )

    def cancel_run(
        self,
        tenant_id: str,
        run_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        reason: str,
        actor_sub: str,
        now: int,
    ) -> dict[str, Any]:
        return self._action(
            tenant_id,
            run_id,
            action="cancel",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            reason=reason,
            now=now,
            actor_sub=actor_sub,
        )

    def retry_run(
        self,
        tenant_id: str,
        run_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        reason: str,
        now: int,
        actor_sub: str,
    ) -> dict[str, Any]:
        return self._action(
            tenant_id,
            run_id,
            action="retry",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            reason=reason,
            now=now,
            actor_sub=actor_sub,
        )

    def get_action(self, tenant_id: str, run_id: str, *, revision: int) -> dict[str, Any]:
        """Full immutable action envelope committed with its canonical audit event."""
        self._scope(tenant_id, run_id)
        with self._transaction() as db:
            return self._get(db, tenant_id, run_id, "action", str(revision))

    def pending_outbox(self, tenant_id: str, run_id: str, *, now: int) -> list[dict[str, Any]]:
        self._scope(tenant_id, run_id)
        self._time(now)
        with self._transaction() as db:
            run = self._get(db, tenant_id, run_id, "run", "META")
            if run["cancellation_requested"]:
                return []
            return sorted(
                (
                    event
                    for event in self._all(db, tenant_id, run_id, "outbox")
                    if event["status"] == "pending" and event["next_attempt_at"] <= now
                ),
                key=lambda event: (event["next_attempt_at"], event["event_id"]),
            )

    def mark_outbox(
        self,
        tenant_id: str,
        run_id: str,
        event_id: str,
        *,
        now: int,
        sent: bool,
        expected_attempts: int,
    ) -> bool:
        self._scope(tenant_id, run_id)
        self._time(now)
        with self._transaction() as db:
            event = self._get(db, tenant_id, run_id, "outbox", event_id)
            if event["status"] != "pending" or event["attempts"] != expected_attempts:
                return False
            event.update(
                status="sent" if sent else "pending",
                attempts=expected_attempts + 1,
                next_attempt_at=now + min(60, 2 ** min(expected_attempts + 1, 6)),
            )
            self._put(db, tenant_id, run_id, "outbox", event_id, event)
            return True
