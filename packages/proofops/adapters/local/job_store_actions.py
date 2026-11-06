"""Atomic cancellation/retry with immutable audit and idempotency records."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from proofops.adapters.local.job_store import LocalSQLiteJobStore


def _action(
    self: LocalSQLiteJobStore,
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
    from proofops.adapters.local import job_store as _job_store

    self._scope(tenant, run_id)
    self._time(now)
    if _job_store._require_strict_int("expected_revision", expected_revision) < 1:
        raise _job_store.JobConflict("revision must be positive")
    if not isinstance(idempotency_key, str) or not 16 <= len(idempotency_key) <= 128:
        raise ValueError("invalid idempotency key")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason required")
    if not isinstance(actor_sub, str) or not actor_sub.strip():
        raise ValueError("server actor_sub required")
    timestamp = (
        _job_store.datetime.fromtimestamp(now, _job_store.UTC).isoformat().replace("+00:00", "Z")
    )
    key = _job_store.canonical_hash([action, idempotency_key])
    request_hash = _job_store.canonical_hash([action, expected_revision, reason])
    with self._transaction() as db:
        run = self._get(db, tenant, run_id, "run", "META")
        if self._raw(db, tenant, run_id, "idempotency", key) is not None:
            previous = self._get(db, tenant, run_id, "idempotency", key)
            if now < previous.get("expires_at", 0):
                if previous["request_hash"] != request_hash:
                    raise _job_store.JobConflict("idempotency key reused with different request")
                return_value: dict[str, Any] = previous["response"]
                return return_value
        if run["revision"] != expected_revision:
            raise _job_store.JobConflict("stale revision")
        jobs = self._all(db, tenant, run_id, "job")
        before = _job_store.deepcopy({"run": run, "jobs": jobs})
        if action == "cancel":
            if run["status"] == "completed":
                raise _job_store.JobConflict("completed run cannot be cancelled")
            run["cancellation_requested"] = True
            for job in jobs:
                if job["status"] in {"pending", "leased", "failed"}:
                    job["status"] = "cancelled"
                    self._save_job(db, _job_store.JobMessage(**job["message"]), job)
            self._bump_run(db, run, "cancelled")
        else:
            if run["status"] not in {"partial", "failed"} or run["cancellation_requested"]:
                raise _job_store.JobConflict("run is not retryable")
            if self.active_run_count(db, tenant) >= 2:
                raise _job_store.JobConflict("tenant run limit")
            for job in jobs:
                if job["status"] == "failed":
                    job.update(status="pending", next_attempt_at=now, retry_attempt=0)
                    message = _job_store.JobMessage(**job["message"])
                    self._save_job(db, message, job)
                    self._event(db, message, now, f"manual:{expected_revision}")
            self._bump_run(db, run, "running")
        self._put(
            db,
            tenant,
            run_id,
            "idempotency",
            key,
            {"request_hash": request_hash, "response": run, "expires_at": now + 86400},
        )
        after = {"run": run, "jobs": self._all(db, tenant, run_id, "job")}
        before_hash = _job_store.canonical_hash(before)
        after_hash = _job_store.canonical_hash(after)
        event_id = str(
            _job_store.uuid5(
                _job_store.NAMESPACE_URL,
                _job_store.canonical_hash([tenant, run_id, run["revision"]]),
            )
        )
        self._put(
            db,
            tenant,
            run_id,
            "action",
            str(run["revision"]),
            {
                "schema_version": 1,
                "tenant_id": tenant,
                "run_id": run_id,
                "event_id": event_id,
                "actor_sub": actor_sub,
                "timestamp": timestamp,
                "target_id": run_id,
                "action": action,
                "reason": reason,
                "revision": run["revision"],
                "before": before,
                "after": after,
                "before_hash": before_hash,
                "after_hash": after_hash,
            },
            immutable=True,
        )
        _job_store.append_audit_transaction(
            connection=db,
            change=_job_store.ChangeSet(
                tenant_id=tenant,
                run_id=run_id,
                actor_sub=actor_sub,
                action=action,
                target_id=run_id,
                before_hash=before_hash,
                after_hash=after_hash,
                revision=run["revision"],
                reason=reason,
            ),
            expected_head=_job_store.read_audit_head(db, tenant, run_id),
            event_id=event_id,
            timestamp=timestamp,
        )
        return run
