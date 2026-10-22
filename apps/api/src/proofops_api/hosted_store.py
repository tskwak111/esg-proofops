"""Single-host durable P1 control plane; no research DB or model adapter reuse.

Payload isolation makes authorized purge possible without disabling immutable
research triggers. All dispatches require a durable, fenced reservation first.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any
from uuid import uuid4

from proofops.adapters.local.provider_errors import MESSAGES, provider_error_code
from proofops.adapters.local.source_hx3 import failure_location
from proofops.application.authorization import MembershipRecord, SessionExpiredError, SessionRecord
from proofops.application.pipeline_failures import MESSAGES as PIPELINE_MESSAGES
from proofops.application.pipeline_failures import PUBLIC_CODES
from proofops.application.uploads_security import (
    HOSTED_NULL_NAVIGATION_PROFILE,
    PdfLimits,
    UploadRejected,
    verify_pdf_file,
)

from proofops_api import (
    hosted_admission,
    hosted_database,
    hosted_money,
    hosted_publication,
    hosted_retention,
)
from proofops_api.hosted_contracts import (
    ALL_PROVIDER_LIMIT_CODES as ALL_PROVIDER_LIMIT_CODES,
)
from proofops_api.hosted_contracts import (
    CONTROL_MESSAGES as CONTROL_MESSAGES,
)
from proofops_api.hosted_contracts import (
    MICRO as MICRO,
)
from proofops_api.hosted_contracts import (
    OPENAI_LIMIT_CODES as OPENAI_LIMIT_CODES,
)
from proofops_api.hosted_contracts import (
    OPENROUTER_LIMIT_CODES as OPENROUTER_LIMIT_CODES,
)
from proofops_api.hosted_contracts import (
    PROVIDER_LIMIT_CODES as PROVIDER_LIMIT_CODES,
)
from proofops_api.hosted_contracts import (
    PROVIDER_LIMIT_MESSAGE as PROVIDER_LIMIT_MESSAGE,
)
from proofops_api.hosted_contracts import (
    RUN_LEASE_SECONDS as RUN_LEASE_SECONDS,
)
from proofops_api.hosted_contracts import (
    TERMINAL as TERMINAL,
)
from proofops_api.hosted_contracts import (
    HostedError as HostedError,
)
from proofops_api.hosted_contracts import (
    HostedSettings as HostedSettings,
)
from proofops_api.hosted_contracts import (
    copy_verified_file as copy_verified_file,
)
from proofops_api.hosted_contracts import (
    day as day,
)
from proofops_api.hosted_contracts import (
    digest as digest,
)
from proofops_api.hosted_contracts import (
    file_sha256 as file_sha256,
)
from proofops_api.hosted_contracts import (
    identifier as identifier,
)
from proofops_api.hosted_contracts import (
    micros as micros,
)
from proofops_api.hosted_contracts import (
    usd as usd,
)


class SQLiteSessions:
    def __init__(self, store: HostedStore):
        self.store = store

    def csrf_token_for(self, sid: str) -> str:
        return hmac.new(
            self.store.settings.secret.encode(), sid.encode(), hashlib.sha256
        ).hexdigest()

    def get(self, sid: str) -> SessionRecord | None:
        with self.store.transaction(readonly=True) as db:
            row = db.execute("SELECT * FROM sessions WHERE sid_hash=?", (digest(sid),)).fetchone()
            valid = row is not None and self.store.access.session_valid(db, row, time.time())
            if row is not None and row["user_id"].startswith("guest:"):
                valid = valid and self.store.guest.available(time.time())
        if row is None:
            return None
        return SessionRecord(
            sid,
            row["user_id"],
            row["tenant_id"],
            row["csrf_hash"],
            row["expires"],
            row["idle"],
            bool(row["revoked"]) or not valid,
        )

    def revoke(self, sid: str) -> None:
        with self.store.transaction() as db:
            db.execute("UPDATE sessions SET revoked=1 WHERE sid_hash=?", (digest(sid),))

    def touch(self, sid: str, now: float) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE sessions SET idle=min(expires,?) WHERE sid_hash=? AND revoked=0 "
                "AND expires>? AND idle>?",
                (now + 1800, digest(sid), now, now),
            )

    def set_active_tenant(self, sid: str, tenant_id: str, *, now: float) -> SessionRecord:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM sessions WHERE sid_hash=?", (digest(sid),)).fetchone()
            if row is None or row["revoked"] or now >= min(row["expires"], row["idle"]):
                raise SessionExpiredError()
            new_id = secrets.token_urlsafe(32)
            db.execute("UPDATE sessions SET revoked=1 WHERE sid_hash=?", (digest(sid),))
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,0)",
                (
                    digest(new_id),
                    row["user_id"],
                    tenant_id,
                    digest(self.csrf_token_for(new_id)),
                    row["expires"],
                    min(row["expires"], now + 1800),
                ),
            )
            db.execute(
                "INSERT INTO access_sessions SELECT ?,role,session_epoch FROM access_sessions "
                "WHERE sid_hash=?",
                (digest(new_id), digest(sid)),
            )
        record = self.get(new_id)
        assert record is not None
        return record


class SQLiteMemberships:
    def __init__(self, store: HostedStore):
        self.store = store

    def get(self, tenant_id: str, user_sub: str) -> MembershipRecord | None:
        with self.store.transaction(readonly=True) as db:
            row = db.execute(
                "SELECT role,status FROM memberships WHERE tenant_id=? AND user_id=?",
                (tenant_id, user_sub),
            ).fetchone()
        return MembershipRecord(tenant_id, user_sub, row[0], row[1]) if row else None

    def tenant_exists(self, tenant_id: str) -> bool:
        with self.store.transaction(readonly=True) as db:
            return (
                db.execute("SELECT 1 FROM memberships WHERE tenant_id=?", (tenant_id,)).fetchone()
                is not None
            )


class HostedStore:
    app_env = "hosted"

    def __init__(self, settings: HostedSettings):
        self.settings = settings
        self.root = settings.root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "control.sqlite3"
        self.ledger = self.root / "deletions.sqlite3"
        self.sessions = SQLiteSessions(self)
        self.memberships = SQLiteMemberships(self)
        from proofops_api.hosted_access import AccessPasswords
        from proofops_api.hosted_guest import GuestAccess

        self.access = AccessPasswords(self)
        self.guest = GuestAccess(self)
        hosted_database.initialize(self)

    @contextmanager
    def transaction(
        self,
        *,
        expiry_cutoff: float | None = None,
        readonly: bool = False,
        lock_wait_seconds: float | None = None,
        operation: str = "transaction",
    ) -> Iterator[sqlite3.Connection]:
        # Keep rollback journals: WAL loses cross-file atomicity for the attached
        # money/tombstone ledger. Reads need a snapshot, not a reserved writer.
        with hosted_database.transaction(
            self,
            expiry_cutoff=expiry_cutoff,
            readonly=readonly,
            lock_wait_seconds=lock_wait_seconds,
            operation=operation,
        ) as db:
            yield db

    def user_hash(self, user: str) -> str:
        return hmac.new(self.settings.secret.encode(), user.encode(), hashlib.sha256).hexdigest()

    def invite(self, tenant: str, user: str, role: str, *, now: float) -> str:
        identifier(tenant)
        MembershipRecord(tenant, user, role, "active")  # type: ignore[arg-type]
        if not user or len(user) > 200 or user.startswith(("access-password:", "guest:")):
            raise ValueError("invalid user")
        code = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO invitations VALUES (?,?,?,?,?,0)",
                (digest(code), tenant, user, role, now + 86400),
            )
        return code

    def redeem(self, code: str, *, now: float) -> str:
        sid = secrets.token_urlsafe(32)
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM invitations WHERE code_hash=?", (digest(code),)
            ).fetchone()
            if row is None or row["used"] or now >= row["expires"]:
                raise HostedError("INVITATION_INVALID", 401)
            db.execute("UPDATE invitations SET used=1 WHERE code_hash=?", (digest(code),))
            # Invitations cannot silently restore a revoked membership or change a role.
            existing = db.execute(
                "SELECT role,status FROM memberships WHERE tenant_id=? AND user_id=?",
                (row["tenant_id"], row["user_id"]),
            ).fetchone()
            if existing and (existing["status"] != "active" or existing["role"] != row["role"]):
                raise HostedError("INVITATION_INVALID", 401)
            db.execute(
                "INSERT OR IGNORE INTO memberships VALUES (?,?,?,'active')",
                (row["tenant_id"], row["user_id"], row["role"]),
            )
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,0)",
                (
                    digest(sid),
                    row["user_id"],
                    row["tenant_id"],
                    digest(self.sessions.csrf_token_for(sid)),
                    now + 28800,
                    now + 1800,
                ),
            )
        return sid

    def consume(self, subject: str, limit: int, now: float) -> None:
        with self.transaction() as db:
            bucket = int(now // 60)
            hashed = self.user_hash(subject)
            row = db.execute(
                "SELECT count FROM rate_limits WHERE subject=? AND bucket=?", (hashed, bucket)
            ).fetchone()
            if row and row[0] >= limit:
                raise HostedError("RATE_LIMITED", 429)
            db.execute(
                "INSERT INTO rate_limits VALUES (?,?,1) ON CONFLICT(subject,bucket) "
                "DO UPDATE SET count=count+1",
                (hashed, bucket),
            )

    def document_dir(self, tenant: str, document: str) -> Path:
        return self.root / "payloads" / identifier(tenant) / identifier(document)

    @staticmethod
    def _deleted(db: sqlite3.Connection, tenant: str, document: str) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM deletion.tombstones WHERE tenant_id=? AND document_id=?",
                (tenant, document),
            ).fetchone()
            is not None
        )

    def _document(self, db: sqlite3.Connection, tenant: str, document: str) -> sqlite3.Row:
        identifier(tenant)
        identifier(document)
        row = db.execute(
            "SELECT * FROM documents WHERE tenant_id=? AND document_id=?", (tenant, document)
        ).fetchone()
        if row is None or self._deleted(db, tenant, document):
            raise HostedError("RESOURCE_NOT_FOUND", 404)
        return row

    def get_document(self, tenant: str, document: str) -> dict:
        with self.transaction(readonly=True) as db:
            return dict(self._document(db, tenant, document)) | self.ux1_document_metadata(
                tenant, document
            )

    def ux1_document_metadata(self, tenant: str, document: str) -> dict:
        # Caller must first enforce document visibility/tombstones using _document or collection.
        path = self.document_dir(tenant, document) / "ux1-metadata.json"
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
        return {"ux1_metadata": value} if isinstance(value, dict) else {}

    def require_owned_resource(self, auth: Any, kind: str, resource: str) -> None:
        """Opaque denial for organizer resources, including nested source/result routes."""
        from proofops_api.hosted_access import is_organizer

        if not is_organizer(auth):
            return
        with self.transaction(readonly=True) as db:
            if kind == "runs":
                row = self._run(db, auth.tenant_id, resource)
                if row["user_hash"] != self.user_hash(auth.user_sub):
                    raise HostedError("RESOURCE_NOT_FOUND", 404)
                resource = row["document_id"]
            self._require_document_owner(db, auth, resource)

    def _require_document_owner(self, db: Any, auth: Any, document: str) -> None:
        from proofops_api.hosted_access import is_organizer
        from proofops_api.hosted_guest import ShowcaseReader

        if is_organizer(auth) and not isinstance(auth, ShowcaseReader):
            owner = db.execute(
                "SELECT user_hash FROM document_owners WHERE tenant_id=? AND document_id=?",
                (auth.tenant_id, document),
            ).fetchone()
            if owner is None or owner[0] != self.user_hash(auth.user_sub):
                raise HostedError("RESOURCE_NOT_FOUND", 404)

    def _replay(
        self, db: sqlite3.Connection, auth: Any, route: str, key: str, body_hash: str
    ) -> str | None:
        if not 16 <= len(key) <= 128:
            raise HostedError("IDEMPOTENCY_KEY_INVALID", 400)
        row = db.execute(
            "SELECT * FROM idempotency WHERE tenant_id=? AND user_hash=? AND route=? AND "
            "key_hash=?",
            (auth.tenant_id, self.user_hash(auth.user_sub), route, digest(key)),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != body_hash:
            raise HostedError("IDEMPOTENCY_CONFLICT")
        self._document(db, auth.tenant_id, row["document_id"])
        return row["resource_id"]

    def _remember(
        self,
        db: sqlite3.Connection,
        auth: Any,
        route: str,
        key: str,
        body_hash: str,
        resource: str,
        document: str,
        now: float,
    ) -> None:
        db.execute(
            "INSERT INTO idempotency VALUES (?,?,?,?,?,?,?,?)",
            (
                auth.tenant_id,
                self.user_hash(auth.user_sub),
                route,
                digest(key),
                body_hash,
                resource,
                document,
                now,
            ),
        )
        self.guest.audit(db, auth, route, resource, now)

    def upload(self, auth: Any, content: bytes, key: str, *, now: float) -> dict:
        """Compatibility for bounded local callers; HTTP uses upload_file directly."""
        with NamedTemporaryFile(dir=self.settings.root) as staged:
            staged.write(content)
            staged.flush()
            return self.upload_file(auth, Path(staged.name), key, now=now)

    def upload_file(
        self, auth: Any, source: Path, key: str, *, now: float, ux1_metadata: dict | None = None
    ) -> dict:
        if not auth.has_capability("editor"):
            raise HostedError("FORBIDDEN", 403)
        if not self.settings.accept_uploads or not self.settings.consent_version:
            raise HostedError("UPLOAD_DISABLED", 503)
        size = source.stat().st_size
        if size > self.settings.max_upload_bytes:
            raise HostedError("PAYLOAD_TOO_LARGE", 413)
        sha = file_sha256(source)
        with self.transaction() as db:
            replay = self._replay(db, auth, "upload", key, sha)
            if replay:
                return dict(
                    self._document(db, auth.tenant_id, replay)
                ) | self.ux1_document_metadata(auth.tenant_id, replay)
            self.guest.check_upload(db, auth, now)
        doc = str(uuid4())
        with TemporaryDirectory(prefix="proofops-upload-", dir=self.settings.root) as scratch:
            security: dict[str, Any] = {}
            derived = Path(scratch) / "decrypted.pdf"
            try:
                pages = verify_pdf_file(
                    source,
                    PdfLimits(
                        policy_profile=HOSTED_NULL_NAVIGATION_PROFILE,
                        max_bytes=self.settings.max_upload_bytes,
                        max_decoded_bytes=512 * 1024 * 1024,
                    ),
                    expected_size=size,
                    expected_sha256=sha,
                    derived_path=derived,
                    security_metadata=security,
                )
            except UploadRejected as exc:
                raise HostedError(str(exc), 422) from None
            with self.transaction() as db:
                replay = self._replay(db, auth, "upload", key, sha)
                if replay:
                    return dict(
                        self._document(db, auth.tenant_id, replay)
                    ) | self.ux1_document_metadata(auth.tenant_id, replay)
                self.guest.check_upload(db, auth, now)
                path = self.document_dir(auth.tenant_id, doc)
                path.mkdir(parents=True, mode=0o700)
                copy_verified_file(source, path / "original.pdf", sha)
                if security.get("encrypted"):
                    copy_verified_file(derived, path / "decrypted.pdf", security["analysis_sha256"])
                self._write(path / "upload-security.json", json.dumps(security).encode())
                if ux1_metadata is not None:
                    self._write(path / "ux1-metadata.json", json.dumps(ux1_metadata).encode())
                db.execute(
                    "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                    (
                        auth.tenant_id,
                        doc,
                        sha,
                        pages,
                        size,
                        now,
                        now + self.settings.active_days * 86400,
                        self.settings.consent_version,
                    ),
                )
                db.execute(
                    "INSERT INTO document_owners VALUES (?,?,?)",
                    (auth.tenant_id, doc, self.user_hash(auth.user_sub)),
                )
                self._remember(db, auth, "upload", key, sha, doc, doc, now)
                return dict(self._document(db, auth.tenant_id, doc)) | self.ux1_document_metadata(
                    auth.tenant_id, doc
                )

    def analysis_source(self, directory: Path, document: dict) -> Path:
        """Tenant-owned immutable original plus verified, byte-bound plaintext derivative."""
        original = directory / "original.pdf"
        if original.is_symlink() or file_sha256(original) != document["sha256"]:
            raise HostedError("UPLOAD_INTEGRITY_MISMATCH", 422)
        sidecar = directory / "upload-security.json"
        if not sidecar.exists():
            return original  # Pre-FX6b documents have no derivative metadata.
        if sidecar.is_symlink():
            raise HostedError("UPLOAD_INTEGRITY_MISMATCH", 422)
        metadata = json.loads(sidecar.read_text())
        if (
            metadata.get("source_sha256") != document["sha256"]
            or metadata.get("original_inspection") != "complete"
        ):
            raise HostedError("UPLOAD_INTEGRITY_MISMATCH", 422)
        if not metadata.get("encrypted"):
            return original
        derived = directory / "decrypted.pdf"
        if (
            not derived.is_file()
            or derived.is_symlink()
            or file_sha256(derived) != metadata.get("analysis_sha256")
        ):
            raise HostedError("UPLOAD_INTEGRITY_MISMATCH", 422)
        return derived

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def _project_run(
        self, row: sqlite3.Row, db: sqlite3.Connection, *, inline_result: bool = True
    ) -> dict:
        progress = db.execute(
            "SELECT * FROM run_progress WHERE run_id=?", (row["run_id"],)
        ).fetchone()
        counts = db.execute(
            "SELECT * FROM run_claim_progress WHERE run_id=?", (row["run_id"],)
        ).fetchone()
        queue = db.execute(
            "SELECT count(*) FROM runs WHERE status='queued' "
            "AND (created<? OR (created=? AND run_id<=?))",
            (row["created"], row["created"], row["run_id"]),
        ).fetchone()[0]
        ready = bool(
            progress
            and progress["result_ready"]
            and row["status"] in {"completed", "partial_blocked"}
        )
        result = self._result(db, row) if ready and inline_result else None
        raw_error = row["error_code"] or ""
        provider = "openai" if raw_error.startswith("OPENAI_") else "openrouter"
        cause = provider_error_code(provider, raw_error)
        user_counts = db.execute(
            "SELECT count(*),coalesce(sum(status='running'),0) FROM runs WHERE user_hash=? "
            "AND status IN ('queued','running','accounting_pending')",
            (row["user_hash"],),
        ).fetchone()
        return {
            "run_id": row["run_id"],
            "document_id": row["document_id"],
            "status": row["status"],
            "selected_pages": json.loads(row["pages"]),
            "claim_pages": self.run_options(row).get("claim_pages", json.loads(row["pages"])),
            "pipeline_profile": self.run_options(row).get("pipeline_profile", "strict-v1"),
            "status_url": f'/v1/runs/{row["run_id"]}',
            "profile": "r108-hosted-sprint5-v1",
            "stage": progress["stage"] if progress else row["status"],
            "progress": progress["progress"] / 100 if progress else 0,
            "claims_extracted": counts["extracted"] if counts else 0,
            "claims_processed": counts["processed"] if counts else 0,
            "claim_stage_counts": {"preliminary": 0, "relation": 0, "elements": 0}
            | {
                stage: completed
                for stage, completed in db.execute(
                    "SELECT stage,completed FROM run_claim_stage_progress WHERE run_id=?",
                    (row["run_id"],),
                )
            },
            "queue_position": queue if row["status"] == "queued" else None,
            "user_active_count": user_counts[0],
            "user_processing_count": user_counts[1],
            "result_url": f'/v1/runs/{row["run_id"]}/result' if ready else None,
            "result": result,
            "error_code": row["error_code"],
            "error_message": CONTROL_MESSAGES.get(raw_error)
            or MESSAGES.get(raw_error)
            or PIPELINE_MESSAGES.get(raw_error)
            or (PROVIDER_LIMIT_MESSAGE if row["error_code"] in ALL_PROVIDER_LIMIT_CODES else None),
            "provider_error_code": cause,
            "provider_error_message": MESSAGES.get(cause),
            "retryable": False,
            "prepared_sha256": row["prepared_sha256"],
        }

    def provider_limits(self) -> dict:
        return hosted_money.provider_limits(self)

    def _run(self, db: sqlite3.Connection, tenant: str, run: str) -> sqlite3.Row:
        identifier(run)
        row = db.execute(
            "SELECT * FROM runs WHERE tenant_id=? AND run_id=?", (tenant, run)
        ).fetchone()
        if row is None:
            raise HostedError("RESOURCE_NOT_FOUND", 404)
        self._document(db, tenant, row["document_id"])
        return row

    def get_run(self, tenant: str, run: str) -> dict:
        lock = None
        try:
            with self.transaction(readonly=True) as db:
                row = self._run(db, tenant, run)
                result = self._project_run(row, db, inline_result=False)
                if result["result_url"]:
                    # Keep payloads leased without holding the control writer.
                    path = self.document_dir(tenant, row["document_id"]) / "analysis.lock"
                    lock = path.open("a+b")
                    os.fchmod(lock.fileno(), 0o600)
                    fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            if lock is not None:
                result["result"] = self._result(None, row)
                # A deletion may fence the leased payload while hashes are read.
                # Never expose bytes after its tombstone commits.
                with self.transaction(readonly=True) as db:
                    self._run(db, tenant, run)
            return result
        finally:
            if lock is not None:
                lock.close()

    def _scope(self, db, tenant: str, document: str) -> dict:
        return hosted_admission._scope(self, db, tenant, document)

    def get_scope(self, tenant: str, document: str) -> dict:
        return hosted_admission.get_scope(self, tenant, document)

    def generate_scope(self, auth, document: str) -> dict:
        return hosted_admission.generate_scope(self, auth, document)

    def edit_scope(
        self,
        auth,
        document,
        claims,
        evidence,
        if_match,
        *,
        manual_selection=False,
        reporting_scope=None,
    ):
        return hosted_admission.edit_scope(
            self,
            auth,
            document,
            claims,
            evidence,
            if_match,
            manual_selection=manual_selection,
            reporting_scope=reporting_scope,
        )

    def run_options(self, job) -> dict:
        return hosted_admission.run_options(self, job)

    def create_run(
        self,
        auth: Any,
        document: str,
        pages: list[int] | None,
        key: str,
        *,
        now: float,
        auto_scope: bool = False,
        scope_selection_sha256: str | None = None,
        pipeline_profile: str = "unattended-v1",
        force_fresh: bool = False,
    ) -> dict:
        return hosted_admission.create_run(
            self,
            auth,
            document,
            pages,
            key,
            now=now,
            auto_scope=auto_scope,
            scope_selection_sha256=scope_selection_sha256,
            pipeline_profile=pipeline_profile,
            force_fresh=force_fresh,
        )

    @staticmethod
    def _maintenance(db: sqlite3.Connection) -> bool:
        return hosted_admission._maintenance(db)

    def _control_state(self, db: sqlite3.Connection) -> dict:
        return hosted_admission._control_state(self, db)

    def drain(self, *, now: float) -> dict:
        return hosted_admission.drain(self, now=now)

    def resume(self, *, now: float) -> dict:
        return hosted_admission.resume(self, now=now)

    def control_state(self, *, now: float) -> dict:
        return hosted_admission.control_state(self, now=now)

    def _expire_running(self, db: sqlite3.Connection, now: float) -> None:
        return hosted_admission._expire_running(self, db, now)

    def claim(self, *, now: float) -> dict | None:
        return hosted_admission.claim(self, now=now)

    def _fenced(self, db: sqlite3.Connection, job: dict, now: float) -> sqlite3.Row:
        return hosted_admission._fenced(self, db, job, now)

    def renew_lease(self, job: dict, *, now: float) -> None:
        return hosted_admission.renew_lease(self, job, now=now)

    def prepare(self, job: dict, *, now: float) -> Path:
        # Lease source bytes separately from the DB snapshot; deletion remains
        # fenced throughout copying and the actual prepare subprocess.
        with (
            TemporaryDirectory(prefix="proofops-prepare-", dir=self.settings.root) as scratch,
            ExitStack() as leases,
        ):
            source, output = Path(scratch) / "source.pdf", Path(scratch) / "selected.pdf"
            with self.transaction(readonly=True) as db:
                row = self._fenced(db, job, now)
                doc = self._document(db, job["tenant_id"], job["document_id"])
                if now >= doc["expires"]:
                    raise HostedError("SOURCE_EXPIRED")
                path = self.document_dir(job["tenant_id"], job["document_id"])
                lock = leases.enter_context((path / "analysis.lock").open("a+b"))
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                pages = row["pages"]
            analysis = self.analysis_source(path, dict(doc))
            copy_verified_file(analysis, source, file_sha256(analysis))
            try:
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "proofops_api.hosted_prepare",
                        str(source),
                        str(output),
                        pages,
                    ],
                    timeout=30,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (subprocess.SubprocessError, OSError):
                raise HostedError("PREPARE_FAILED") from None
            if output.stat().st_size > 50 * 1024 * 1024:
                raise HostedError("PREPARE_TOO_LARGE")
            prepared_sha = file_sha256(output)
            prepared = path / f'{job["run_id"]}.prepared.pdf'
            copy_verified_file(output, prepared, prepared_sha)
            with self.transaction() as db:
                self._fenced(db, job, time.time())
                db.execute(
                    "UPDATE runs SET prepared_sha256=? WHERE run_id=?",
                    (prepared_sha, job["run_id"]),
                )
                return prepared

    def dispatch(
        self,
        job: dict,
        provider: str,
        call_id: str,
        input_sha: str,
        bound: Decimal,
        transport: Callable[[dict], dict],
        *,
        now: float,
        allow_transient_403: bool = False,
        allow_model_partial: bool = False,
        allow_response_uncertainty: bool = False,
        allow_connect_not_sent: bool = False,
        allow_ops2_fallback: bool = False,
        diagnostic_context: dict | None = None,
    ) -> dict:
        return hosted_money.dispatch(
            self,
            job,
            provider,
            call_id,
            input_sha,
            bound,
            transport,
            now=now,
            allow_transient_403=allow_transient_403,
            allow_model_partial=allow_model_partial,
            allow_response_uncertainty=allow_response_uncertainty,
            allow_connect_not_sent=allow_connect_not_sent,
            allow_ops2_fallback=allow_ops2_fallback,
            diagnostic_context=diagnostic_context,
        )

    def _settle_envelope(self, db: sqlite3.Connection, run: str) -> None:
        return hosted_money._settle_envelope(self, db, run)

    def finish(self, job: dict, status: str, *, now: float) -> None:
        return hosted_money.finish(self, job, status, now=now)

    def tick(self, *, now: float, analysis=None) -> dict | None:
        job = self.claim(now=now)
        if job is None:
            return None
        prepared = None
        try:
            prepared = self.prepare(job, now=now)
            if analysis is not None or not self.settings.live_disabled:
                from proofops_api.hosted_analysis import execute_analysis

                (analysis or execute_analysis)(self, job, prepared)
            else:
                with TemporaryDirectory(prefix="blocked-", dir=prepared.parent) as scratch:
                    state = Path(scratch)
                    self._write(
                        state / "outcome.json",
                        json.dumps(
                            dict(
                                status="partial_blocked",
                                reason="LIVE_BINDING_UNAVAILABLE",
                                stages=[],
                                provider_calls=0,
                                scope=self.run_options(job),
                                reporting_scope=self.run_options(job).get("reporting_scope"),
                            )
                        ).encode(),
                    )
                    self.publish_analysis(job, state, "partial_blocked", "LIVE_BINDING_UNAVAILABLE")
        except (HostedError, OSError, ValueError, subprocess.SubprocessError) as exc:
            code = (
                exc.code
                if isinstance(exc, HostedError)
                else str(exc)
                if str(exc) in ALL_PROVIDER_LIMIT_CODES | PUBLIC_CODES
                else "ANALYSIS_WORKER_FAILED"
                if prepared is not None
                else "PREPARE_FAILED"
            )
            with self.transaction() as db:
                progress = db.execute(
                    "SELECT stage FROM run_progress WHERE run_id=?", (job["run_id"],)
                ).fetchone()
                stage = (
                    progress[0]
                    if progress and progress[0] in {"parse", "extract", "tag", "result"}
                    else "prepare"
                    if prepared is None
                    else "analysis"
                )
                row = db.execute(
                    "SELECT status,fence,error_code FROM runs WHERE run_id=?", (job["run_id"],)
                ).fetchone()
                if row and (row[2] in MESSAGES or row[2] in ALL_PROVIDER_LIMIT_CODES):
                    code = row[2]
                if row and row[0] == "running" and row[1] == job["fence"]:
                    db.execute(
                        "UPDATE runs SET status='failed',error_code=?,lease_until=0 WHERE "
                        "run_id=?",
                        (code, job["run_id"]),
                    )
                    self._settle_envelope(db, job["run_id"])
            logging.getLogger(__name__).warning(
                "hosted run %s failed: %s (%s) stage=%s location=%s",
                job["run_id"],
                code,
                type(exc).__name__,
                stage,
                failure_location(exc),
            )
        try:
            return self.get_run(job["tenant_id"], job["run_id"])
        except HostedError as exc:
            if exc.status != 404:
                raise
            return None

    def update_progress(
        self,
        job: dict,
        stage: str,
        progress: int,
        *,
        claims_extracted: int | None = None,
        claims_processed: int | None = None,
        claim_stage_counts: dict[str, int] | None = None,
    ) -> None:
        if claim_stage_counts is not None and (
            not isinstance(claim_stage_counts, dict)
            or set(claim_stage_counts) - {"preliminary", "relation", "elements"}
            or any(type(count) is not int or count < 0 for count in claim_stage_counts.values())
        ):
            raise ValueError("invalid claim stage progress")
        for count in (claims_extracted, claims_processed):
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("invalid claim progress")
        with self.transaction(operation="progress") as db:
            now = time.time()
            self._fenced(db, job, now)
            db.execute(
                "UPDATE runs SET lease_until=? WHERE run_id=?",
                (now + RUN_LEASE_SECONDS, job["run_id"]),
            )
            db.execute(
                "INSERT INTO run_progress VALUES (?,?,?,0) ON CONFLICT(run_id) "
                "DO UPDATE SET stage=excluded.stage,progress=excluded.progress",
                (job["run_id"], stage, progress),
            )
            if claims_extracted is not None or claims_processed is not None:
                db.execute(
                    "INSERT INTO run_claim_progress VALUES (?,?,?) ON CONFLICT(run_id) "
                    "DO UPDATE SET extracted=max(extracted,excluded.extracted),"
                    "processed=max(processed,excluded.processed)",
                    (job["run_id"], claims_extracted or 0, claims_processed or 0),
                )
            for claim_stage, completed in (claim_stage_counts or {}).items():
                db.execute(
                    "INSERT INTO run_claim_stage_progress VALUES (?,?,?) ON CONFLICT(run_id,stage) "
                    "DO UPDATE SET completed=max(completed,excluded.completed)",
                    (job["run_id"], claim_stage, completed),
                )

    def publish_analysis(
        self, job: dict, source: Path, status: str, error: str | None, *, publication_handoff=None
    ) -> None:
        return hosted_publication.publish_analysis(
            self, job, source, status, error, publication_handoff=publication_handoff
        )

    def _publish_snapshot(self, db: sqlite3.Connection, run: str, path: Path, content: bytes):
        return hosted_publication._publish_snapshot(self, db, run, path, content)

    def _result(self, db: sqlite3.Connection | None, row: sqlite3.Row) -> dict:
        return hosted_publication._result(self, db, row)

    def get_result(self, tenant: str, run: str) -> dict:
        return hosted_publication.get_result(self, tenant, run)

    def resolve_review(
        self, auth: Any, run: str, review: str, body: dict, if_match: str | None, key: str
    ) -> dict:
        return hosted_publication.resolve_review(self, auth, run, review, body, if_match, key)

    def cancel(self, auth: Any, run: str, *, now: float) -> dict:
        return hosted_admission.cancel(self, auth, run, now=now)

    def budget_totals(self) -> dict:
        return hosted_money.budget_totals(self)

    def delete_document(self, auth: Any, document: str, key: str, *, now: float) -> dict:
        return hosted_retention.delete_document(self, auth, document, key, now=now)

    def _purge(self, tenant: str, document: str, now: float) -> dict:
        return hosted_retention._purge(self, tenant, document, now)

    def replay_deletions(self, *, now: float) -> None:
        return hosted_retention.replay_deletions(self, now=now)

    def maintain(self, *, now: float) -> None:
        # API and worker both maintain this volume. Serialize filesystem GC
        # separately so slow unlink never reserves the control/ledger writer.
        return hosted_retention.maintain(self, now=now)

    def _maintain(self, *, now: float) -> None:
        return hosted_retention._maintain(self, now=now)

    def backup(self, target: Path, *, now: float) -> Path:
        return hosted_retention.backup(self, target, now=now)

    def restore(self, backup: Path, *, now: float) -> None:
        return hosted_retention.restore(self, backup, now=now)
