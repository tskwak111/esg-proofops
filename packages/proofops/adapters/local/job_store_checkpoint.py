"""Fenced checkpoint validation, publication, audit and next-stage enqueue."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.application.ports.jobs import JobLease, JobMessage


def commit_job(
    self: LocalSQLiteJobStore,
    lease: JobLease,
    *,
    payload: bytes,
    now: int,
    next_job: JobMessage | None = None,
    publish: Callable[[sqlite3.Connection], None] | None = None,
) -> bool:
    from proofops.adapters.local import job_store as _job_store

    self._time(now)
    if not isinstance(payload, bytes):
        raise ValueError("checkpoint must be bytes")
    message = lease.message
    if next_job is not None and (
        next_job.tenant_id,
        next_job.run_id,
        next_job.document_version_id,
    ) != (message.tenant_id, message.run_id, message.document_version_id):
        raise ValueError("next job must belong to the same tenant/run/document version")
    with self._transaction() as db:
        owned = self._owned(db, lease, now)
        if owned is None:
            return False
        job, run = owned
        before_hash = _job_store.canonical_hash(run)
        try:
            envelope = _job_store.json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            envelope = None
        if message.stage == "parse":
            pinned = self._raw(
                db, message.tenant_id, message.run_id, "parser_note_input", message.job_id
            )
            policy_raw = self._raw(
                db, message.tenant_id, message.run_id, "parser_note_policy", message.job_id
            )
            policy = None if policy_raw is None else _job_store.json.loads(policy_raw)
            native_raw = self._raw(
                db, message.tenant_id, message.run_id, "parser_native_policy", message.job_id
            )
            native_policy = None if native_raw is None else _job_store.json.loads(native_raw)
            if (
                native_raw is None
                and isinstance(envelope, dict)
                and envelope.get("schema")
                in {"local_parser_checkpoint_v4", "local_parser_checkpoint_v5"}
            ):
                raise ValueError("NATIVE_PARAGRAPH_INPUT_NOT_BOUND")
            if native_policy is not None and (
                not isinstance(envelope, dict)
                or envelope.get("schema")
                not in {"local_parser_checkpoint_v4", "local_parser_checkpoint_v5"}
                or envelope.get("native_paragraph_policy_sha256")
                != _job_store.canonical_hash(native_policy)
            ):
                raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
            if (
                isinstance(envelope, dict)
                and native_policy is None
                and (
                    envelope.get("schema")
                    in {"local_parser_checkpoint_v4", "local_parser_checkpoint_v5"}
                    or any(key.startswith("native_paragraph_") for key in envelope)
                )
            ):
                raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
            if native_policy is not None:
                from proofops.adapters.local.run_artifacts import (
                    checkpoint_native_attestation,
                )

                if not isinstance(envelope, dict) or (
                    checkpoint_native_attestation(envelope) is None
                ):
                    raise ValueError("NATIVE_PARAGRAPH_CHECKPOINT_INPUT_MISMATCH")
            if policy is not None and (
                pinned is None
                or not isinstance(envelope, dict)
                or envelope.get("schema")
                not in {
                    "local_parser_checkpoint_v3",
                    "local_parser_checkpoint_v4",
                    "local_parser_checkpoint_v5",
                }
                or envelope.get("note_review_policy_sha256") != _job_store.canonical_hash(policy)
            ):
                raise ValueError("NOTE_REVIEW_POLICY_MISMATCH")
            if (
                isinstance(envelope, dict)
                and policy is None
                and (
                    envelope.get("schema") == "local_parser_checkpoint_v3"
                    or "note_review_policy_sha256" in envelope
                )
            ):
                raise ValueError("NOTE_REVIEW_POLICY_MISMATCH")
            if (
                pinned is None
                and isinstance(envelope, dict)
                and envelope.get("schema") == "local_parser_checkpoint_v2"
            ):
                raise ValueError("NOTE_REVIEW_INPUT_NOT_BOUND")
            if pinned is not None:
                from proofops.adapters.local.run_artifacts import checkpoint_note_reviews

                if not isinstance(envelope, dict) or checkpoint_note_reviews(envelope) != tuple(
                    _job_store.json.loads(pinned)
                ):
                    raise ValueError("NOTE_REVIEW_CHECKPOINT_INPUT_MISMATCH")
        if isinstance(envelope, dict) and str(envelope.get("schema", "")).startswith(
            "local_parser_checkpoint_"
        ):
            from proofops.adapters.local.run_artifacts import checkpoint_note_reviews

            checkpoint_note_reviews(envelope)
            coverage = envelope.get("coverage", {})
            counts = (
                "pages_total",
                "pages_processed",
                "pages_unreadable",
                "pages_unprocessed",
                "chunks_discovered",
                "chunks_processed",
                "claims_discovered",
                "claims_decided",
                "claims_needs_review",
            )
            if (
                message.stage != "parse"
                or next_job is None
                or next_job.stage != "extract"
                or next_job.input_hash != message.input_hash
                or envelope.get("input_hash") != message.input_hash
                or envelope.get("stage_status") != "completed"
                or envelope.get("downstream_status") != "pending"
                or not isinstance(coverage, dict)
                or set(coverage) != {*counts, "full_scope", "complete"}
                or any(type(coverage.get(key)) is not int or coverage[key] < 0 for key in counts)
                or coverage["complete"] is not False
                or type(coverage["full_scope"]) is not bool
                or coverage["pages_total"] != sum(coverage[k] for k in counts[1:4])
                or any(coverage[k] != 0 for k in counts[4:])
            ):
                raise ValueError("invalid local parse stage checkpoint")
            row = db.execute(
                "SELECT payload FROM run_snapshots WHERE tenant_id=? AND run_id=?",
                (message.tenant_id, message.run_id),
            ).fetchone()
            if row is None:
                raise ValueError("parse checkpoint requires a frozen run snapshot")
            snapshot = _job_store.json.loads(row[0])
            if (
                snapshot["input_hash"] != message.input_hash
                or snapshot["document"]["version_id"] != message.document_version_id
                or coverage["pages_total"] != snapshot["document"]["page_count"]
                or coverage["full_scope"] != (snapshot["scope"] == "full")
                or coverage["pages_unprocessed"]
                != coverage["pages_total"] - len(snapshot["selected_pages"])
            ):
                raise ValueError("parse coverage differs from frozen run selection")
            from proofops.adapters.local.raster_job_store import (
                validate_raster_checkpoint_bindings,
            )

            validate_raster_checkpoint_bindings(db, self, message, snapshot, envelope)
            run.update(
                current_stage="extract", coverage=coverage, parse_job=_job_store.asdict(message)
            )
        if (
            message.stage == "extract"
            and "parse_job" in run
            and (
                not isinstance(envelope, dict)
                or envelope.get("schema")
                not in {"local_extract_checkpoint_v1", "local_extract_checkpoint_v2"}
            )
        ):
            raise ValueError("local extract requires versioned claim snapshot")
        if isinstance(envelope, dict) and envelope.get("schema") in {
            "local_extract_checkpoint_v1",
            "local_extract_checkpoint_v2",
        }:
            from proofops.adapters.local.claim_store import validate_extract_commit

            validate_extract_commit(db, self, run, message, envelope, next_job, now=now)
            run.update(
                current_stage="tag",
                coverage=envelope["coverage"],
                extract_job=_job_store.asdict(message),
                claim_snapshot_sha256=_job_store.hashlib.sha256(payload).hexdigest(),
            )
        if message.stage == "tag" and "extract_job" in run:
            from proofops.adapters.local.tag_store import validate_tag_commit

            if not isinstance(envelope, dict) or publish is None:
                raise ValueError("tag stage requires fenced versioned publication")
            coverage = validate_tag_commit(db, self, run, message, envelope, next_job)
            run.update(
                current_stage="tag" if envelope["stage_status"] == "blocked" else "review",
                status="completed"
                if envelope.get("pipeline_profile") == "unattended-v1"
                else "partial",
                coverage=coverage,
                tag_job=_job_store.asdict(message),
                tag_stage_status=envelope["stage_status"],
                tag_snapshot_sha256=_job_store.hashlib.sha256(payload).hexdigest(),
            )
        elif publish is not None:
            raise ValueError("publication hook is restricted to local tag checkpoints")
        key = f"job/{message.job_id}/attempt/{lease.fencing_token}/checkpoint"
        self._put(db, message.tenant_id, message.run_id, "artifact", key, payload, immutable=True)
        job.update(
            status="succeeded",
            artifact_ref={
                "key": key,
                "sha256": _job_store.hashlib.sha256(payload).hexdigest(),
                "byte_size": len(payload),
                "storage": self.kind,
            },
        )
        self._save_job(db, message, job)
        if next_job is not None:
            self._enqueue(db, next_job, now)
        if publish is not None:
            publish(db)
        self._bump_run(db, run, refresh_claim_counts=publish is not None)
        if publish is not None:
            _job_store.append_audit_transaction(
                connection=db,
                change=_job_store.ChangeSet(
                    message.tenant_id,
                    message.run_id,
                    "local-tag-worker",
                    "tag_stage_published",
                    message.job_id,
                    before_hash,
                    _job_store.canonical_hash(run),
                    run["revision"],
                    envelope["stage_status"],
                ),
                expected_head=_job_store.read_audit_head(db, message.tenant_id, message.run_id),
                event_id=str(
                    _job_store.uuid5(
                        _job_store.NAMESPACE_URL,
                        _job_store.canonical_hash(
                            [
                                message.tenant_id,
                                message.run_id,
                                message.job_id,
                                lease.fencing_token,
                            ]
                        ),
                    )
                ),
                timestamp=_job_store.datetime.fromtimestamp(now, _job_store.UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            )
        return True
