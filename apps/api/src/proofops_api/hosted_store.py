"""Single-host durable P1 control plane; no research DB or model adapter reuse.

Payload isolation makes authorized purge possible without disabling immutable
research triggers. All dispatches require a durable, fenced reservation first.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from proofops.application.authorization import MembershipRecord, SessionExpiredError, SessionRecord
from proofops.application.uploads_security import (
    PdfLimits,
    QuarantinedPdf,
    UploadRejected,
    verify_quarantined_pdf,
)

MICRO = Decimal(1_000_000)
TERMINAL = ("partial_blocked", "completed", "cancelled", "failed")
OPENROUTER_LIMIT_CODES = frozenset({"OPENROUTER_HTTP_402", "OPENROUTER_HTTP_403"})
OPENAI_LIMIT_CODES = frozenset({"OPENAI_HTTP_401", "OPENAI_HTTP_429", "OPENAI_INSUFFICIENT_QUOTA"})
PROVIDER_LIMIT_CODES = {
    "openrouter": OPENROUTER_LIMIT_CODES,
    "openai": OPENAI_LIMIT_CODES,
}
ALL_PROVIDER_LIMIT_CODES = OPENROUTER_LIMIT_CODES | OPENAI_LIMIT_CODES
PROVIDER_LIMIT_MESSAGE = "분석 서비스 한도 초과 — 운영자 확인 필요"


class HostedError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def micros(value: Decimal | str) -> int:
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0 or amount * MICRO != (amount * MICRO).to_integral():
        raise ValueError("invalid micro-USD amount")
    return int(amount * MICRO)


def usd(value: int) -> str:
    return f"{Decimal(value) / MICRO:.6f}"


def identifier(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise HostedError("RESOURCE_NOT_FOUND", 404) from None


def day(now: float) -> str:
    return datetime.fromtimestamp(now, ZoneInfo("Asia/Seoul")).date().isoformat()


@dataclass(frozen=True)
class HostedSettings:
    root: Path
    origin: str
    secret: str
    event_id: str
    accept_uploads: bool = False
    consent_version: str = ""
    backend: str = "static"
    accept_runs: bool = False
    live_disabled: bool = True
    live_config: Path | None = None
    max_upload_bytes: int = 50 * 1024 * 1024
    active_days: int = 7
    backup_days: int = 14
    audit_days: int = 30
    run_usd: Decimal = Decimal("1.0")
    day_usd: Decimal = Decimal("7")
    event_usd: Decimal = Decimal("7")

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in self.origin
        ):
            raise ValueError("APP_ORIGIN must be one exact HTTPS origin")
        if not self.root.is_absolute() or len(self.secret.encode()) < 32 or not self.event_id:
            raise ValueError(
                "absolute private data directory, session secret and event ID required"
            )
        if self.backend not in {"r108", "legacy", "static"}:
            raise ValueError("invalid analysis backend")
        if not self.live_disabled:
            from proofops_api.hosted_analysis import read_operator_config

            read_operator_config(self.live_config)
        if self.accept_uploads and not self.consent_version:
            raise ValueError("upload consent version required")
        for value in (self.max_upload_bytes, self.active_days, self.backup_days, self.audit_days):
            if type(value) is not int or value <= 0:
                raise ValueError("positive limits required")
        if (
            self.max_upload_bytes > 50 * 1024 * 1024
            or self.active_days > 7
            or self.backup_days > 14
            or self.audit_days > 30
        ):
            raise ValueError("limits exceed P1 ceilings")
        if not self.active_days <= self.backup_days <= self.audit_days:
            raise ValueError("retention order invalid")
        for amount, ceiling in ((self.run_usd, "1.0"), (self.day_usd, "7"), (self.event_usd, "7")):
            if not 0 < micros(amount) <= micros(ceiling):
                raise ValueError("budget exceeds DEC-22 ceilings")

    @classmethod
    def from_env(cls, env: Any) -> HostedSettings:
        def flag(name: str, default: str) -> bool:
            value = env.get(name, default)
            if value not in {"true", "false"}:
                raise ValueError(f"invalid {name}")
            return value == "true"

        if env.get("APP_ENV") != "hosted" or env.get("MODEL_ADAPTER", "disabled") != "disabled":
            raise ValueError("explicit hosted/disabled composition required")
        return cls(
            root=Path(env.get("HOSTED_DATA_DIR", "")),
            origin=env.get("APP_ORIGIN", ""),
            secret=env.get("HOSTED_SESSION_SECRET", ""),
            event_id=env.get("HOSTED_EVENT_ID", ""),
            accept_uploads=flag("HOSTED_ACCEPT_UPLOADS", "false"),
            consent_version=env.get("HOSTED_CONSENT_VERSION", ""),
            backend=env.get("ANALYSIS_BACKEND", "static"),
            accept_runs=flag("R108_ACCEPT_NEW_RUNS", "false"),
            live_disabled=flag("LIVE_DISABLED", "true"),
            live_config=Path(env["HOSTED_LIVE_CONFIG"]) if env.get("HOSTED_LIVE_CONFIG") else None,
            max_upload_bytes=int(env.get("HOSTED_MAX_UPLOAD_BYTES", "52428800")),
            active_days=int(env.get("HOSTED_ACTIVE_DAYS", "7")),
            backup_days=int(env.get("HOSTED_BACKUP_DAYS", "14")),
            audit_days=int(env.get("HOSTED_AUDIT_DAYS", "30")),
            run_usd=Decimal(env.get("HOSTED_RUN_USD", "1.0")),
            day_usd=Decimal(env.get("HOSTED_DAY_USD", "7")),
            event_usd=Decimal(env.get("HOSTED_EVENT_USD", "7")),
        )


class SQLiteSessions:
    def __init__(self, store: HostedStore):
        self.store = store

    def csrf_token_for(self, sid: str) -> str:
        return hmac.new(
            self.store.settings.secret.encode(), sid.encode(), hashlib.sha256
        ).hexdigest()

    def get(self, sid: str) -> SessionRecord | None:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM sessions WHERE sid_hash=?", (digest(sid),)).fetchone()
        if row is None:
            return None
        return SessionRecord(
            sid,
            row["user_id"],
            row["tenant_id"],
            row["csrf_hash"],
            row["expires"],
            row["idle"],
            bool(row["revoked"]),
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
        record = self.get(new_id)
        assert record is not None
        return record


class SQLiteMemberships:
    def __init__(self, store: HostedStore):
        self.store = store

    def get(self, tenant_id: str, user_sub: str) -> MembershipRecord | None:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT role,status FROM memberships WHERE tenant_id=? AND user_id=?",
                (tenant_id, user_sub),
            ).fetchone()
        return MembershipRecord(tenant_id, user_sub, row[0], row[1]) if row else None

    def tenant_exists(self, tenant_id: str) -> bool:
        with self.store.transaction() as db:
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
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS hosted_schema (version INTEGER PRIMARY KEY)")
            versions = db.execute("SELECT version FROM hosted_schema").fetchall()
            if versions and [row[0] for row in versions] != [1]:
                raise ValueError("unsupported hosted schema")
            db.execute("INSERT OR IGNORE INTO hosted_schema VALUES (1)")
            db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                sid_hash TEXT PRIMARY KEY, user_id TEXT, tenant_id TEXT, csrf_hash TEXT,
                expires REAL, idle REAL, revoked INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS memberships (
                tenant_id TEXT, user_id TEXT, role TEXT, status TEXT,
                PRIMARY KEY(tenant_id,user_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS invitations (
                code_hash TEXT PRIMARY KEY, tenant_id TEXT, user_id TEXT, role TEXT,
                expires REAL, used INTEGER DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                tenant_id TEXT, document_id TEXT, sha256 TEXT, page_count INTEGER,
                size_bytes INTEGER, created REAL, expires REAL, consent_version TEXT,
                PRIMARY KEY(tenant_id,document_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS document_owners (
                tenant_id TEXT, document_id TEXT, user_hash TEXT,
                PRIMARY KEY(tenant_id,document_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS run_progress (
                run_id TEXT PRIMARY KEY, stage TEXT, progress INTEGER, result_ready INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS result_snapshots (
                run_id TEXT, revision INTEGER, sha256 TEXT NOT NULL,
                PRIMARY KEY(run_id,revision))""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS result_snapshot_update
                BEFORE UPDATE ON result_snapshots
                BEGIN SELECT RAISE(ABORT,'immutable result snapshot'); END""")
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                tenant_id TEXT, run_id TEXT PRIMARY KEY, document_id TEXT, user_hash TEXT,
                pages TEXT, status TEXT, created REAL, day TEXT, event_id TEXT,
                envelope INTEGER, fence INTEGER DEFAULT 0, lease_until REAL DEFAULT 0,
                error_code TEXT, prepared_sha256 TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS idempotency (
                tenant_id TEXT, user_hash TEXT, route TEXT, key_hash TEXT, request_hash TEXT,
                resource_id TEXT, document_id TEXT, created REAL,
                PRIMARY KEY(tenant_id,user_hash,route,key_hash))""")
            db.execute("""CREATE TABLE IF NOT EXISTS deletion.costs (
                run_id TEXT, call_id TEXT, request_id TEXT, provider TEXT, input_sha256 TEXT,
                bound INTEGER, actual INTEGER, status TEXT, created REAL,
                PRIMARY KEY(run_id,call_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS deletion.spend (
                run_id TEXT PRIMARY KEY, user_hash TEXT, day TEXT, event_id TEXT,
                amount INTEGER, created REAL, status TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS deletion.event_totals (
                event_id TEXT PRIMARY KEY, amount INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS rate_limits (
                subject TEXT, bucket INTEGER, count INTEGER, PRIMARY KEY(subject,bucket))""")
            db.execute("""CREATE TABLE IF NOT EXISTS backups (
                path TEXT PRIMARY KEY, created REAL, expires REAL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS deletion.identity (
                id INTEGER PRIMARY KEY CHECK(id=1), ledger_id TEXT NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO deletion.identity VALUES (1,?)", (str(uuid4()),))
            db.execute("""CREATE TABLE IF NOT EXISTS deletion.tombstones (
                tenant_id TEXT, document_id TEXT, deletion_id TEXT, created REAL,
                key_hash TEXT, PRIMARY KEY(tenant_id,document_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS deletion.attempts (
                tenant_id TEXT, document_id TEXT, status TEXT, updated REAL,
                PRIMARY KEY(tenant_id,document_id))""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS deletion.tombstone_update
                BEFORE UPDATE ON tombstones
                BEGIN SELECT RAISE(ABORT,'immutable tombstone'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS deletion.tombstone_delete
                BEFORE DELETE ON tombstones WHEN retention_expired(OLD.created)=0
                BEGIN SELECT RAISE(ABORT,'immutable tombstone'); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS deletion.tombstone_insert
                BEFORE INSERT ON tombstones WHEN EXISTS(SELECT 1 FROM tombstones
                    WHERE tenant_id=NEW.tenant_id AND document_id=NEW.document_id)
                BEGIN SELECT RAISE(ABORT,'immutable tombstone'); END""")
        for path in (self.path, self.ledger):
            os.chmod(path, 0o600)
        with self.transaction() as db:
            # Lost control state never makes admitted/unknown dispatch safe to retry.
            db.execute(
                "UPDATE deletion.spend SET status='accounting_pending' WHERE status='reserved' "
                "AND NOT EXISTS(SELECT 1 FROM runs r WHERE r.run_id=deletion.spend.run_id)"
            )
        self.replay_deletions(now=time.time())

    @contextmanager
    def transaction(self, *, expiry_cutoff: float | None = None) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.create_function(
            "retention_expired",
            1,
            lambda created: int(expiry_cutoff is not None and created <= expiry_cutoff),
        )
        try:
            db.execute("ATTACH DATABASE ? AS deletion", (str(self.ledger),))
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def user_hash(self, user: str) -> str:
        return hmac.new(self.settings.secret.encode(), user.encode(), hashlib.sha256).hexdigest()

    def invite(self, tenant: str, user: str, role: str, *, now: float) -> str:
        identifier(tenant)
        MembershipRecord(tenant, user, role, "active")  # type: ignore[arg-type]
        if not user or len(user) > 200:
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
        with self.transaction() as db:
            return dict(self._document(db, tenant, document))

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

    def upload(self, auth: Any, content: bytes, key: str, *, now: float) -> dict:
        if not auth.has_capability("editor"):
            raise HostedError("FORBIDDEN", 403)
        if not self.settings.accept_uploads or not self.settings.consent_version:
            raise HostedError("UPLOAD_DISABLED", 503)
        if len(content) > self.settings.max_upload_bytes:
            raise HostedError("PAYLOAD_TOO_LARGE", 413)
        sha = digest(content)
        with self.transaction() as db:
            replay = self._replay(db, auth, "upload", key, sha)
            if replay:
                return dict(self._document(db, auth.tenant_id, replay))
        doc = str(uuid4())
        source = QuarantinedPdf(auth.tenant_id, doc, str(uuid4()), content, len(content), sha)
        try:
            verified = verify_quarantined_pdf(
                source,
                PdfLimits(max_bytes=self.settings.max_upload_bytes),
                tenant_id=auth.tenant_id,
            )
        except UploadRejected as exc:
            raise HostedError(str(exc), 422) from None
        # Publish under the same writer lock as metadata, so deletion/backup cannot race.
        with self.transaction() as db:
            replay = self._replay(db, auth, "upload", key, sha)
            if replay:
                return dict(self._document(db, auth.tenant_id, replay))
            path = self.document_dir(auth.tenant_id, doc)
            path.mkdir(parents=True, mode=0o700)
            self._write(path / "original.pdf", content)
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (
                    auth.tenant_id,
                    doc,
                    sha,
                    verified.page_count,
                    len(content),
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
            return dict(self._document(db, auth.tenant_id, doc))

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
            "queue_position": queue if row["status"] == "queued" else None,
            "result_url": f'/v1/runs/{row["run_id"]}/result' if ready else None,
            "result": result,
            "error_code": row["error_code"],
            "error_message": PROVIDER_LIMIT_MESSAGE
            if row["error_code"] in ALL_PROVIDER_LIMIT_CODES
            else None,
            "retryable": False,
            "prepared_sha256": row["prepared_sha256"],
        }

    def provider_limits(self) -> dict:
        """Observed service availability only; never probe providers on public GETs."""
        limits = {}
        with self.transaction() as db:
            for provider, codes in PROVIDER_LIMIT_CODES.items():
                parameters = tuple(sorted(codes))
                placeholders = ",".join("?" for _ in parameters)
                row = db.execute(
                    f"SELECT error_code FROM runs WHERE error_code IN ({placeholders}) "
                    "ORDER BY created DESC,run_id DESC LIMIT 1",
                    parameters,
                ).fetchone()
                limits[provider] = {
                    "status": "blocked" if row else "unknown",
                    "error_code": row[0] if row else None,
                    "remaining_usd": None,
                    "source": "observed_http_failure" if row else "not_queried",
                    "retryable": False,
                    "message": PROVIDER_LIMIT_MESSAGE if row else None,
                }
        return limits

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
            with self.transaction() as db:
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
                with self.transaction() as db:
                    self._run(db, tenant, run)
            return result
        finally:
            if lock is not None:
                lock.close()

    def _scope(self, db, tenant: str, document: str) -> dict:
        doc = self._document(db, tenant, document)
        if time.time() >= doc["expires"]:
            raise HostedError("SOURCE_EXPIRED")
        paths = sorted(self.document_dir(tenant, document).glob("scope-*.json"))
        if not paths:
            raise HostedError("SCOPE_PLAN_REQUIRED")
        scope = json.loads(paths[-1].read_text())
        from evaluation.report_scope import validate_selection

        if scope["plan"]["source_sha256"] != doc["sha256"]:
            raise HostedError("SOURCE_HASH_MISMATCH")
        if scope["plan"]["status"] != "failed":
            try:
                selection = validate_selection(scope["plan"], doc["sha256"], doc["page_count"])
            except (ValueError, KeyError, TypeError):
                raise HostedError("SCOPE_INTEGRITY_INVALID") from None
            if selection != scope["selection"]:
                raise HostedError("SCOPE_INTEGRITY_INVALID")
        return scope

    def get_scope(self, tenant: str, document: str) -> dict:
        with self.transaction() as db:
            return self._scope(db, tenant, document)

    def generate_scope(self, auth, document: str) -> dict:
        if not auth.has_capability("editor"):
            raise HostedError("FORBIDDEN", 403)
        with self.transaction() as db:
            doc = dict(self._document(db, auth.tenant_id, document))
            path = self.document_dir(auth.tenant_id, document)
            if list(path.glob("scope-*.json")):
                return self._scope(db, auth.tenant_id, document)
            if time.time() >= doc["expires"]:
                raise HostedError("SOURCE_EXPIRED")
        # Share the cross-process upload slot with validation on the 4GiB host.
        with (self.settings.root / "upload.lock").open("a+b") as lease:
            os.fchmod(lease.fileno(), 0o600)
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HostedError("UPLOAD_BUSY", 429) from None
            with TemporaryDirectory(prefix="proofops-scope-") as scratch:
                output = Path(scratch) / "plan.json"
                try:
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "proofops_api.hosted_scope",
                            str(path / "original.pdf"),
                            str(output),
                        ],
                        timeout=90,
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except (subprocess.SubprocessError, OSError):
                    raise HostedError("SCOPE_INSPECTION_FAILED", 422) from None
                plan = json.loads(output.read_text())
        from evaluation.report_scope import validate_selection

        selection = (
            None
            if plan["status"] == "failed"
            else validate_selection(plan, doc["sha256"], doc["page_count"])
        )
        with self.transaction() as db:
            current = self._document(db, auth.tenant_id, document)
            if time.time() >= current["expires"]:
                raise HostedError("SOURCE_EXPIRED")
            if plan["source_sha256"] != current["sha256"]:
                raise HostedError("SOURCE_HASH_MISMATCH")
            if list(path.glob("scope-*.json")):
                return self._scope(db, auth.tenant_id, document)
            scope = dict(revision=1, plan=plan, selection=selection)
            self._write(path / "scope-000001.json", json.dumps(scope).encode())
            return scope

    def edit_scope(self, auth, document, claims, evidence, if_match):
        if not auth.has_capability("editor"):
            raise HostedError("FORBIDDEN", 403)
        with self.transaction() as db:
            scope = self._scope(db, auth.tenant_id, document)
            if if_match is None:
                raise HostedError("IF_MATCH_REQUIRED", 428)
            if if_match != f'"{scope["revision"]}"':
                raise HostedError("SCOPE_CONFLICT", 412)
            if scope["plan"]["status"] == "failed":
                raise HostedError("SCOPE_PLAN_FAILED", 422)
            doc = self._document(db, auth.tenant_id, document)
            plan = scope["plan"] | dict(
                selected_claim_pages=claims, selected_evidence_pages=evidence
            )
            from evaluation.report_scope import validate_selection

            try:
                selection = validate_selection(plan, doc["sha256"], doc["page_count"])
            except (ValueError, KeyError, TypeError):
                raise HostedError("PAGE_SELECTION_INVALID", 422) from None
            revision = scope["revision"] + 1
            updated = dict(revision=revision, plan=plan, selection=selection)
            self._write(
                self.document_dir(auth.tenant_id, document) / f"scope-{revision:06}.json",
                json.dumps(updated).encode(),
            )
            return updated

    def run_options(self, job) -> dict:
        path = (
            self.document_dir(job["tenant_id"], job["document_id"])
            / f'{job["run_id"]}.options.json'
        )
        if not path.is_file():
            return {}  # Previous <=2-page runs retain their frozen profile.
        options = json.loads(path.read_text())
        from proofops.domain.provenance import canonical_hash

        expected = options.pop("sha256")
        if canonical_hash(options) != expected or options["pages"] != json.loads(job["pages"]):
            raise HostedError("SCOPE_INTEGRITY_INVALID")
        return options

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
    ) -> dict:
        if not auth.has_capability("editor"):
            raise HostedError("FORBIDDEN", 403)
        if not self.settings.accept_runs or self.settings.backend != "r108":
            raise HostedError("ANALYSIS_DISABLED", 503)
        with self.transaction() as db:
            doc = self._document(db, auth.tenant_id, document)
            if now >= doc["expires"]:
                raise HostedError("SOURCE_EXPIRED", 409)
            options = None
            if auto_scope and pages is None:
                scope = self._scope(db, auth.tenant_id, document)
                if scope["plan"]["status"] == "failed":
                    raise HostedError("SCOPE_PLAN_FAILED", 422)
                selection = scope["selection"]
                if (
                    scope_selection_sha256
                    and scope_selection_sha256 != selection["selection_sha256"]
                ):
                    raise HostedError("SCOPE_CONFLICT", 412)
                selected = selection["pages"]
                options = selection | dict(
                    pipeline_profile=pipeline_profile,
                    source_sha256=doc["sha256"],
                    scope_policy_sha256=scope["plan"]["policy_sha256"],
                )
            else:
                selected = list(range(1, min(2, doc["page_count"]) + 1)) if pages is None else pages
                if auto_scope:
                    options = dict(
                        pages=selected,
                        claim_pages=selected,
                        pipeline_profile=pipeline_profile,
                        source_sha256=doc["sha256"],
                        declared_subset=True,
                    )
            if (
                not isinstance(selected, list)
                or not 1 <= len(selected) <= (30 if options else 2)
                or any(
                    type(page) is not int or not 1 <= page <= doc["page_count"] for page in selected
                )
                or len(set(selected)) != len(selected)
            ):
                raise HostedError("PAGE_SELECTION_INVALID", 422)
            if pipeline_profile not in {"unattended-v1", "strict-v1"}:
                raise HostedError("PIPELINE_PROFILE_INVALID", 422)
            body_hash = digest(json.dumps([document, selected, options]))
            replay = self._replay(db, auth, "run", key, body_hash)
            if replay:
                return self._project_run(self._run(db, auth.tenant_id, replay), db)
            if not (self.document_dir(auth.tenant_id, document) / "original.pdf").is_file():
                raise HostedError("SOURCE_UNAVAILABLE")
            if db.execute(
                "SELECT 1 FROM deletion.spend WHERE status='accounting_pending'"
            ).fetchone():
                raise HostedError("ACCOUNTING_PENDING", 503)
            user = self.user_hash(auth.user_sub)
            if db.execute(
                "SELECT 1 FROM runs WHERE user_hash=? AND status IN "
                "('queued','running','accounting_pending')",
                (user,),
            ).fetchone():
                raise HostedError("USER_RUN_LIMIT", 429)
            if db.execute("SELECT count(*) FROM runs WHERE status='queued'").fetchone()[0] >= 8:
                raise HostedError("QUEUE_FULL", 429)
            today = day(now)
            for subject, maximum in ((user, 2), (None, 10)):
                query = "SELECT count(*) FROM deletion.spend WHERE day=?"
                params: tuple = (today,)
                if subject is not None:
                    query += " AND user_hash=?"
                    params += (subject,)
                if db.execute(query, params).fetchone()[0] >= maximum:
                    raise HostedError("DAILY_RUN_LIMIT", 429)
            bound = micros(self.settings.run_usd)
            for field, value, cap in (
                ("day", today, self.settings.day_usd),
                ("event_id", self.settings.event_id, self.settings.event_usd),
            ):
                total = db.execute(
                    f"SELECT coalesce(sum(amount),0) FROM deletion.spend WHERE {field}=?", (value,)
                ).fetchone()[0]
                if field == "event_id":
                    archived = db.execute(
                        "SELECT amount FROM deletion.event_totals WHERE event_id=?", (value,)
                    ).fetchone()
                    total += archived[0] if archived else 0
                if total + bound > micros(cap):
                    raise HostedError("BUDGET_EXCEEDED", 429)
            run = str(uuid4())
            if options:
                from proofops.domain.provenance import canonical_hash

                options["sha256"] = canonical_hash(options)
                self._write(
                    self.document_dir(auth.tenant_id, document) / f"{run}.options.json",
                    json.dumps(options).encode(),
                )
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,'queued',?,?,?,?,0,0,NULL,NULL)",
                (
                    auth.tenant_id,
                    run,
                    document,
                    user,
                    json.dumps(selected),
                    now,
                    today,
                    self.settings.event_id,
                    bound,
                ),
            )
            db.execute(
                "INSERT INTO deletion.spend VALUES (?,?,?,?,?,?,'reserved')",
                (run, user, today, self.settings.event_id, bound, now),
            )
            self._remember(db, auth, "run", key, body_hash, run, document, now)
            return self._project_run(self._run(db, auth.tenant_id, run), db)

    def claim(self, *, now: float) -> dict | None:
        with self.transaction() as db:
            expired = db.execute(
                "SELECT run_id FROM runs WHERE status='running' AND lease_until<=?", (now,)
            ).fetchall()
            for row in expired:
                db.execute(
                    "UPDATE runs SET "
                    "status='accounting_pending',fence=fence+1,error_code='LEASE_EXPIRED' WHERE "
                    "run_id=?",
                    (row[0],),
                )
                db.execute(
                    "UPDATE deletion.spend SET status='accounting_pending' WHERE run_id=?",
                    (row[0],),
                )
            # Unknown provider dispatch blocks the single worker, requiring operator reconciliation.
            if db.execute(
                "SELECT 1 FROM runs WHERE status IN ('running','accounting_pending') "
                "UNION ALL SELECT 1 FROM deletion.spend WHERE status='accounting_pending'"
            ).fetchone():
                return None
            row = db.execute(
                "SELECT * FROM runs WHERE status='queued' ORDER BY created,run_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._document(db, row["tenant_id"], row["document_id"])
            db.execute(
                "UPDATE runs SET status='running',fence=fence+1,lease_until=? WHERE run_id=?",
                (now + 900, row["run_id"]),
            )
            return dict(
                db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            )

    def _fenced(self, db: sqlite3.Connection, job: dict, now: float) -> sqlite3.Row:
        row = self._run(db, job["tenant_id"], job["run_id"])
        if row["status"] != "running" or row["fence"] != job["fence"] or row["lease_until"] <= now:
            raise HostedError("LEASE_LOST")
        return row

    def prepare(self, job: dict, *, now: float) -> Path:
        # Snapshot under the fence, perform bounded PDF work outside the DB lock,
        # then recheck the fence before publication. Delete cannot resurrect files.
        with self.transaction() as db:
            row = self._fenced(db, job, now)
            doc = self._document(db, job["tenant_id"], job["document_id"])
            if now >= doc["expires"]:
                raise HostedError("SOURCE_EXPIRED")
            path = self.document_dir(job["tenant_id"], job["document_id"])
            original = (path / "original.pdf").read_bytes()
            if digest(original) != doc["sha256"]:
                raise HostedError("SOURCE_HASH_MISMATCH")
            pages = row["pages"]
        with TemporaryDirectory(prefix="proofops-prepare-") as scratch:
            source, output = Path(scratch) / "source.pdf", Path(scratch) / "selected.pdf"
            self._write(source, original)
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
            with output.open("rb") as stream:
                content = stream.read(self.settings.max_upload_bytes + 1)
            if len(content) > self.settings.max_upload_bytes:
                raise HostedError("PREPARE_TOO_LARGE")
        with self.transaction() as db:
            self._fenced(db, job, time.time())
            prepared = path / f'{job["run_id"]}.prepared.pdf'
            self._write(prepared, content)
            db.execute(
                "UPDATE runs SET prepared_sha256=? WHERE run_id=?", (digest(content), job["run_id"])
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
    ) -> dict:
        """Broker boundary for a future approved adapter. No HTTP/provider implementation here."""
        if (
            not provider
            or not call_id
            or len(input_sha) != 64
            or any(c not in "0123456789abcdef" for c in input_sha)
        ):
            raise HostedError("DISPATCH_INVALID", 422)
        reserved = micros(bound)
        if reserved <= 0:
            raise HostedError("DISPATCH_INVALID", 422)
        with self.transaction() as db:
            row = self._fenced(db, job, now)
            if db.execute(
                "SELECT 1 FROM deletion.costs WHERE run_id=? AND call_id=?",
                (job["run_id"], call_id),
            ).fetchone():
                raise HostedError("DISPATCH_ALREADY_RECORDED")
            total = db.execute(
                "SELECT coalesce(sum(CASE WHEN status='settled' THEN actual ELSE bound END),0) "
                "FROM deletion.costs WHERE run_id=?",
                (job["run_id"],),
            ).fetchone()[0]
            if total + reserved > row["envelope"]:
                raise HostedError("BUDGET_EXCEEDED", 429)
            request = {"request_id": str(uuid4()), "provider": provider, "input_sha256": input_sha}
            db.execute(
                "INSERT INTO deletion.costs VALUES (?,?,?,?,?,?,NULL,'reserved',?)",
                (job["run_id"], call_id, request["request_id"], provider, input_sha, reserved, now),
            )
        try:
            response = transport(request)
            if any(response.get(k) != v for k, v in request.items()):
                raise HostedError("RECEIPT_MISMATCH")
            actual = micros(response["actual_usd"])
            if actual > reserved:
                raise HostedError("RECEIPT_BOUND_EXCEEDED")
            with self.transaction() as db:
                # A late cancelled/deleted result may settle money, but cannot publish payload.
                db.execute(
                    "UPDATE deletion.costs SET actual=?,status='settled' "
                    "WHERE run_id=? AND call_id=? "
                    "AND status='reserved'",
                    (actual, job["run_id"], call_id),
                )
                state = db.execute(
                    "SELECT status FROM runs WHERE run_id=?", (job["run_id"],)
                ).fetchone()
                if state is None or state[0] in TERMINAL:
                    self._settle_envelope(db, job["run_id"])
            return response
        except BaseException as exc:
            # A rejected quota call is terminal, but its unknown cost still needs
            # operator reconciliation. Never release reservations or redeliver it.
            limit_code = str(exc)
            quota_blocked = limit_code in PROVIDER_LIMIT_CODES.get(provider, ())
            with self.transaction() as db:
                db.execute(
                    "UPDATE deletion.costs SET status='accounting_pending' "
                    "WHERE run_id=? AND call_id=? "
                    "AND status='reserved'",
                    (job["run_id"], call_id),
                )
                db.execute(
                    "UPDATE runs SET "
                    "status=?,fence=fence+1,error_code=?,lease_until=0 "
                    "WHERE run_id=? AND status='running' AND fence=?",
                    (
                        "failed" if quota_blocked else "accounting_pending",
                        limit_code if quota_blocked else "ACCOUNTING_PENDING",
                        job["run_id"],
                        job["fence"],
                    ),
                )
                db.execute(
                    "UPDATE deletion.spend SET status='accounting_pending' WHERE run_id=?",
                    (job["run_id"],),
                )
            raise

    def _settle_envelope(self, db: sqlite3.Connection, run: str) -> None:
        unknown = db.execute(
            "SELECT 1 FROM deletion.costs WHERE run_id=? AND status!='settled'", (run,)
        ).fetchone()
        if unknown:
            db.execute(
                "UPDATE deletion.spend SET status='accounting_pending' WHERE run_id=?", (run,)
            )
        else:
            actual = db.execute(
                "SELECT coalesce(sum(actual),0) FROM deletion.costs WHERE run_id=?", (run,)
            ).fetchone()[0]
            db.execute(
                "UPDATE deletion.spend SET amount=?,status='settled' WHERE run_id=?", (actual, run)
            )

    def finish(self, job: dict, status: str, *, now: float) -> None:
        if status not in TERMINAL or status == "completed":
            # Completion is available only through fenced analysis artifact publication.
            raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
        with self.transaction() as db:
            self._fenced(db, job, now)
            db.execute(
                "UPDATE runs SET status=?,lease_until=0,error_code=? WHERE run_id=?",
                (
                    status,
                    "LIVE_BINDING_UNAVAILABLE" if status == "partial_blocked" else None,
                    job["run_id"],
                ),
            )
            self._settle_envelope(db, job["run_id"])

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
                self.finish(job, "partial_blocked", now=time.time())
        except (HostedError, OSError, ValueError, subprocess.SubprocessError) as exc:
            code = (
                exc.code
                if isinstance(exc, HostedError)
                else str(exc)
                if str(exc) in ALL_PROVIDER_LIMIT_CODES
                else "ANALYSIS_WORKER_FAILED"
                if prepared is not None
                else "PREPARE_FAILED"
            )
            with self.transaction() as db:
                row = db.execute(
                    "SELECT status,fence FROM runs WHERE run_id=?", (job["run_id"],)
                ).fetchone()
                if row and row[0] == "running" and row[1] == job["fence"]:
                    db.execute(
                        "UPDATE runs SET status='failed',error_code=?,lease_until=0 WHERE "
                        "run_id=?",
                        (code, job["run_id"]),
                    )
                    self._settle_envelope(db, job["run_id"])
        try:
            return self.get_run(job["tenant_id"], job["run_id"])
        except HostedError as exc:
            if exc.status != 404:
                raise
            return None

    def update_progress(self, job: dict, stage: str, progress: int) -> None:
        with self.transaction() as db:
            self._fenced(db, job, time.time())
            db.execute(
                "INSERT INTO run_progress VALUES (?,?,?,0) ON CONFLICT(run_id) "
                "DO UPDATE SET stage=excluded.stage,progress=excluded.progress",
                (job["run_id"], stage, progress),
            )

    def publish_analysis(self, job: dict, source: Path, status: str, error: str | None) -> None:
        from proofops_api.hosted_results import result_snapshot

        if status not in {"completed", "partial_blocked"}:
            raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
        # The worker owns analysis.lock while validating its private workspace.
        # Replay must never hold the control writer or run on a GET request.
        content = result_snapshot(source, job["tenant_id"], json.loads(job["pages"]))
        with self.transaction() as db:
            self._fenced(db, job, time.time())
            target = (
                self.document_dir(job["tenant_id"], job["document_id"]) / "analysis" / job["run_id"]
            )
            target.parent.mkdir(mode=0o700, exist_ok=True)
            shutil.copytree(source, target)
            self._publish_snapshot(db, job["run_id"], target, content)
            db.execute(
                "INSERT OR REPLACE INTO run_progress VALUES (?, 'result',100,1)", (job["run_id"],)
            )
            db.execute(
                "UPDATE runs SET status=?,error_code=?,lease_until=0 WHERE run_id=?",
                (status, error, job["run_id"]),
            )
            self._settle_envelope(db, job["run_id"])

    def _publish_snapshot(self, db: sqlite3.Connection, run: str, path: Path, content: bytes):
        revision = db.execute(
            "SELECT coalesce(max(revision),0)+1 FROM result_snapshots WHERE run_id=?", (run,)
        ).fetchone()[0]
        target = path / f"result-{revision}.json"
        self._write(target, content)
        target.chmod(0o400)
        db.execute("INSERT INTO result_snapshots VALUES (?,?,?)", (run, revision, digest(content)))

    def _result(self, db: sqlite3.Connection | None, row: sqlite3.Row) -> dict:
        path = self.document_dir(row["tenant_id"], row["document_id"]) / "analysis" / row["run_id"]
        if db is None:
            with self.transaction() as connection:
                anchor = connection.execute(
                    "SELECT revision,sha256 FROM result_snapshots WHERE run_id=? "
                    "ORDER BY revision DESC LIMIT 1",
                    (row["run_id"],),
                ).fetchone()
        else:
            anchor = db.execute(
                "SELECT revision,sha256 FROM result_snapshots WHERE run_id=? "
                "ORDER BY revision DESC LIMIT 1",
                (row["run_id"],),
            ).fetchone()
        try:
            if anchor is None:
                raise ValueError("snapshot not published")
            content = (path / f"result-{anchor['revision']}.json").read_bytes()
            if digest(content) != anchor["sha256"]:
                raise ValueError("snapshot hash mismatch")
            snapshot = json.loads(content)
            if snapshot["tenant_id"] != row["tenant_id"] or snapshot["page_map"] != json.loads(
                row["pages"]
            ):
                raise ValueError("snapshot scope mismatch")
            for relative, expected in snapshot["source_hashes"].items():
                if digest((path / relative).read_bytes()) != expected:
                    raise ValueError("source hash mismatch")
            return snapshot["result"]
        except (OSError, ValueError, KeyError, TypeError):
            raise HostedError("RESULT_INTEGRITY_UNAVAILABLE", 409) from None

    def get_result(self, tenant: str, run: str) -> dict:
        result = self.get_run(tenant, run)
        if result["result_url"] is None:
            raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
        return result["result"]

    def resolve_review(
        self, auth: Any, run: str, review: str, body: dict, if_match: str | None, key: str
    ) -> dict:
        from proofops_api.hosted_results import resolve_review, result_snapshot

        if not auth.has_capability("reviewer"):
            raise HostedError("FORBIDDEN", 403)
        with self.transaction() as db:
            row = self._run(db, auth.tenant_id, run)
            if row["status"] not in {"completed", "partial_blocked"}:
                raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
            path = self.document_dir(auth.tenant_id, row["document_id"]) / "analysis" / run
            # Shared payload lease lets GETs continue reading the prior immutable
            # snapshot while one review at a time publishes a validated revision.
            lock = (path.parent.parent / "analysis.lock").open("a+b")
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        try:
            with (path / "review.lock").open("a+b") as review_lock:
                os.fchmod(review_lock.fileno(), 0o600)
                fcntl.flock(review_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                resolved = resolve_review(path, auth, review, body, if_match, key)
                content = result_snapshot(path, auth.tenant_id, json.loads(row["pages"]))
                with self.transaction() as db:
                    self._run(db, auth.tenant_id, run)
                    self._publish_snapshot(db, run, path, content)
                return resolved
        finally:
            lock.close()

    def cancel(self, auth: Any, run: str, *, now: float) -> dict:
        with self.transaction() as db:
            row = self._run(db, auth.tenant_id, run)
            if row["user_hash"] != self.user_hash(auth.user_sub) and not auth.has_capability(
                "admin"
            ):
                raise HostedError("FORBIDDEN", 403)
            db.execute(
                "UPDATE runs SET status='cancelled',fence=fence+1,lease_until=0 WHERE run_id=?",
                (run,),
            )
            self._settle_envelope(db, run)
            return self._project_run(self._run(db, auth.tenant_id, run), db)

    def budget_totals(self) -> dict:
        with self.transaction() as db:
            total = db.execute(
                "SELECT coalesce(sum(amount),0) FROM deletion.spend WHERE event_id=?",
                (self.settings.event_id,),
            ).fetchone()[0]
            archived = db.execute(
                "SELECT amount FROM deletion.event_totals WHERE event_id=?",
                (self.settings.event_id,),
            ).fetchone()
            total += archived[0] if archived else 0
        return {"event_reserved_usd": usd(total)}

    def delete_document(self, auth: Any, document: str, key: str, *, now: float) -> dict:
        if not isinstance(key, str) or not 16 <= len(key) <= 128:
            raise HostedError("IDEMPOTENCY_KEY_INVALID", 400)
        with self.transaction() as db:
            owner = db.execute(
                "SELECT user_hash FROM document_owners WHERE tenant_id=? " "AND document_id=?",
                (auth.tenant_id, document),
            ).fetchone()
            if not auth.has_capability("admin") and (
                owner is None or owner[0] != self.user_hash(auth.user_sub)
            ):
                self._document(db, auth.tenant_id, document)
                raise HostedError("FORBIDDEN", 403)
            row = db.execute(
                "SELECT * FROM deletion.tombstones WHERE tenant_id=? AND document_id=?",
                (auth.tenant_id, document),
            ).fetchone()
            if row is None:
                self._document(db, auth.tenant_id, document)
                db.execute(
                    "INSERT INTO deletion.tombstones VALUES (?,?,?,?,?)",
                    (auth.tenant_id, document, str(uuid4()), now, digest(key)),
                )
                db.execute(
                    "UPDATE runs SET status='cancelled',fence=fence+1,lease_until=0 WHERE "
                    "tenant_id=? AND document_id=?",
                    (auth.tenant_id, document),
                )
        # Tombstone is durable before any filesystem deletion.
        return self._purge(auth.tenant_id, document, now)

    def _purge(self, tenant: str, document: str, now: float) -> dict:
        status = "completed"
        try:
            with self.transaction() as db:
                if not self._deleted(db, tenant, document):
                    raise HostedError("TOMBSTONE_REQUIRED")
                path = self.document_dir(tenant, document)
                if path.exists():
                    lock_path = path / "analysis.lock"
                    if lock_path.exists():
                        # Tombstone already fenced dispatch/publication. Do not
                        # unlink working source bytes while a child still owns them.
                        with lock_path.open("a+b") as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            shutil.rmtree(path)
                    else:
                        shutil.rmtree(path)
                for backup in db.execute("SELECT path FROM backups").fetchall():
                    target = Path(backup[0]) / "artifacts" / tenant / document
                    if target.exists():
                        shutil.rmtree(target)
                runs = db.execute(
                    "SELECT run_id FROM runs WHERE tenant_id=? AND document_id=?",
                    (tenant, document),
                ).fetchall()
                for run in runs:
                    self._settle_envelope(db, run[0])
                    db.execute("DELETE FROM run_progress WHERE run_id=?", (run[0],))
                    db.execute("DELETE FROM result_snapshots WHERE run_id=?", (run[0],))
                db.execute(
                    "DELETE FROM document_owners WHERE tenant_id=? AND document_id=?",
                    (tenant, document),
                )
                db.execute(
                    "DELETE FROM runs WHERE tenant_id=? AND document_id=?", (tenant, document)
                )
                db.execute(
                    "DELETE FROM documents WHERE tenant_id=? AND document_id=?", (tenant, document)
                )
                db.execute(
                    "DELETE FROM idempotency WHERE tenant_id=? AND document_id=?",
                    (tenant, document),
                )
                from proofops_api.hosted_results import clear_receipt_caches

                clear_receipt_caches()
        except (OSError, sqlite3.DatabaseError):
            status = "failed"
        with self.transaction() as db:
            db.execute(
                "INSERT INTO deletion.attempts VALUES (?,?,?,?) ON "
                "CONFLICT(tenant_id,document_id) DO UPDATE SET "
                "status=excluded.status,updated=excluded.updated",
                (tenant, document, status, now),
            )
            row = db.execute(
                "SELECT deletion_id,created FROM deletion.tombstones WHERE tenant_id=? AND "
                "document_id=?",
                (tenant, document),
            ).fetchone()
        return {"deletion_id": row[0], "status": status, "requested_at": row[1]}

    def replay_deletions(self, *, now: float) -> None:
        with self.transaction() as db:
            rows = db.execute("SELECT tenant_id,document_id FROM deletion.tombstones").fetchall()
        for row in rows:
            result = self._purge(row[0], row[1], now)
            if result["status"] != "completed":
                raise HostedError("PURGE_INCOMPLETE", 503)

    def maintain(self, *, now: float) -> None:
        with self.transaction() as db:
            expired = db.execute(
                "SELECT tenant_id,document_id FROM documents WHERE expires<=?", (now,)
            ).fetchall()
            for row in expired:
                if not self._deleted(db, row[0], row[1]):
                    db.execute(
                        "INSERT INTO deletion.tombstones VALUES (?,?,?,?,?)",
                        (row[0], row[1], str(uuid4()), now, digest("expiry")),
                    )
            backups = db.execute("SELECT path FROM backups WHERE expires<=?", (now,)).fetchall()
            for backup in backups:
                target = Path(backup[0])
                if target.exists():
                    shutil.rmtree(target)
                db.execute("DELETE FROM backups WHERE path=?", (backup[0],))
            db.execute("DELETE FROM sessions WHERE expires<=? OR idle<=? OR revoked=1", (now, now))
            db.execute("DELETE FROM invitations WHERE expires<=? OR used=1", (now,))
            db.execute("DELETE FROM rate_limits WHERE bucket<?", (int(now // 60) - 2,))
            cutoff = now - self.settings.audit_days * 86400
            # Remove per-run audit after30d, retaining only a subject-free event aggregate.
            # Unreconciled money cannot be discarded to free budget.
            old = db.execute(
                "SELECT run_id,event_id,amount FROM deletion.spend WHERE created<? AND "
                "status='settled'",
                (cutoff,),
            ).fetchall()
            for run in old:
                db.execute(
                    "INSERT INTO deletion.event_totals VALUES (?,?) ON CONFLICT(event_id) "
                    "DO UPDATE SET amount=amount+excluded.amount",
                    (run[1], run[2]),
                )
                db.execute("DELETE FROM deletion.costs WHERE run_id=?", (run[0],))
                db.execute("DELETE FROM deletion.spend WHERE run_id=?", (run[0],))
        self.replay_deletions(now=now)
        with self.transaction(expiry_cutoff=now - self.settings.audit_days * 86400) as db:
            expired = db.execute(
                "SELECT t.tenant_id,t.document_id FROM deletion.tombstones t "
                "JOIN deletion.attempts a USING(tenant_id,document_id) "
                "WHERE t.created<=? AND a.status='completed'",
                (now - self.settings.audit_days * 86400,),
            ).fetchall()
            for row in expired:
                db.execute(
                    "DELETE FROM deletion.tombstones WHERE tenant_id=? AND document_id=?",
                    tuple(row),
                )
                db.execute(
                    "DELETE FROM deletion.attempts WHERE tenant_id=? AND document_id=?", tuple(row)
                )
        # Remove unreferenced files left by a crashed upload; no content enters logs.
        with self.transaction() as db:
            known = {
                (row[0], row[1])
                for row in db.execute("SELECT tenant_id,document_id FROM documents")
            }
            payloads = self.root / "payloads"
            if payloads.exists():
                for tenant in payloads.iterdir():
                    for doc in tenant.iterdir():
                        if (tenant.name, doc.name) not in known:
                            shutil.rmtree(doc)

    def backup(self, target: Path, *, now: float) -> Path:
        """Operator-only stopped-service backup, allowlist excludes raw bytes and sessions."""
        target = target.resolve()
        if target.exists() or target == self.root or self.root.is_relative_to(target):
            raise ValueError("new backup directory required")
        target.mkdir(parents=True, mode=0o700)
        with self.transaction() as db:
            # SQLite online backup from a separate read connection, while writer fence is held.
            source = sqlite3.connect(self.path)
            destination = sqlite3.connect(target / "control.sqlite3")
            try:
                source.backup(destination)
                destination.execute("PRAGMA secure_delete=ON")
                for table in ("sessions", "invitations", "memberships", "rate_limits", "backups"):
                    destination.execute(f"DELETE FROM {table}")
                destination.commit()
                destination.execute("VACUUM")
            finally:
                source.close()
                destination.close()
            for doc in db.execute("SELECT tenant_id,document_id,created FROM documents"):
                if self._deleted(db, doc[0], doc[1]):
                    continue
                path = self.document_dir(doc[0], doc[1])
                for kind in ("receipt", "graph", "export"):
                    source_dir = path / kind
                    if source_dir.exists():
                        dest = target / "artifacts" / doc[0] / doc[1] / kind
                        shutil.copytree(source_dir, dest)
            oldest = db.execute("SELECT min(created) FROM documents").fetchone()[0]
            expires = (
                min(now, oldest if oldest is not None else now) + self.settings.backup_days * 86400
            )
            db.execute("INSERT INTO backups VALUES (?,?,?)", (str(target), now, expires))
            self._write(
                target / "manifest.json",
                json.dumps(
                    {
                        "schema": 1,
                        "created": now,
                        "expires": expires,
                        "raw_source": "excluded",
                        "ledger_id": db.execute(
                            "SELECT ledger_id FROM deletion.identity WHERE id=1"
                        ).fetchone()[0],
                    }
                ).encode(),
            )
        return target

    def restore(self, backup: Path, *, now: float) -> None:
        """Restore payload/control rows only; never roll back deletion or money ledgers."""
        manifest = json.loads((backup / "manifest.json").read_text())
        if manifest["schema"] != 1 or manifest["expires"] <= now:
            raise HostedError("BACKUP_EXPIRED")
        with self.transaction() as db:
            identity = db.execute("SELECT ledger_id FROM deletion.identity WHERE id=1").fetchone()[
                0
            ]
            if manifest.get("ledger_id") != identity:
                raise HostedError("LEDGER_RECOVERY_REQUIRED", 503)
            db.execute("ATTACH DATABASE ? AS recovered", (str(backup / "control.sqlite3"),))
            # Only still-active document metadata; original deliberately unavailable on restore.
            for row in db.execute(
                "SELECT * FROM recovered.documents WHERE expires>?", (now,)
            ).fetchall():
                if self._deleted(db, row["tenant_id"], row["document_id"]):
                    continue
                db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?)", tuple(row))
                source = backup / "artifacts" / row["tenant_id"] / row["document_id"]
                if source.exists():
                    dest = self.document_dir(row["tenant_id"], row["document_id"])
                    shutil.copytree(source, dest, dirs_exist_ok=True)
        self.replay_deletions(now=now)
