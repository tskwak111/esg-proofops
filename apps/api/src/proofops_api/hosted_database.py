"""Hosted database; every operation uses the facade's shared transaction context."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

from proofops_api.hosted_sqlite import BUSY_TIMEOUT_MS, retry_busy

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore


def initialize(store: HostedStore) -> None:
    with store.transaction() as db:
        store.access.migrate(db)
        store.guest.migrate(db)
        db.execute("CREATE TABLE IF NOT EXISTS hosted_schema (version INTEGER PRIMARY KEY)")
        versions = db.execute("SELECT version FROM hosted_schema").fetchall()
        if versions and [row[0] for row in versions] != [1]:
            raise ValueError("unsupported hosted schema")
        db.execute("INSERT OR IGNORE INTO hosted_schema VALUES (1)")
        db.execute("""CREATE TABLE IF NOT EXISTS ops2_provider_observations (
                provider TEXT PRIMARY KEY, observed REAL NOT NULL, error_code TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS admission_control (
                id INTEGER PRIMARY KEY CHECK(id=1),
                draining INTEGER NOT NULL CHECK(draining IN (0,1)), updated REAL NOT NULL)""")
        db.execute("INSERT OR IGNORE INTO admission_control VALUES (1,0,0)")
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
        db.execute("""CREATE TABLE IF NOT EXISTS run_claim_progress (
                run_id TEXT PRIMARY KEY, extracted INTEGER NOT NULL, processed INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS run_claim_stage_progress (
                run_id TEXT NOT NULL, stage TEXT NOT NULL, completed INTEGER NOT NULL,
                PRIMARY KEY(run_id, stage))""")
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
        db.execute("""CREATE TABLE IF NOT EXISTS deletion.source_retention (
                tenant_id TEXT NOT NULL, run_id TEXT NOT NULL, document_id TEXT NOT NULL,
                expires REAL NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(tenant_id,run_id))""")
        db.execute(
            "INSERT OR IGNORE INTO deletion.source_retention "
            "SELECT r.tenant_id,r.run_id,r.document_id,d.expires,r.created "
            "FROM runs r JOIN documents d USING(tenant_id,document_id)"
        )
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
        from proofops_api.hosted_reuse import migrate

        migrate(db)
    for path in (store.path, store.ledger):
        os.chmod(path, 0o600)
    with store.transaction() as db:
        # Lost control state never makes admitted/unknown dispatch safe to retry.
        db.execute(
            "UPDATE deletion.spend SET status='accounting_pending' WHERE status='reserved' "
            "AND NOT EXISTS(SELECT 1 FROM runs r WHERE r.run_id=deletion.spend.run_id)"
        )
    store.replay_deletions(now=time.time())


@contextmanager
def transaction(
    store: HostedStore,
    *,
    expiry_cutoff: float | None = None,
    readonly: bool = False,
    lock_wait_seconds: float | None = None,
    operation: str = "transaction",
) -> Iterator[sqlite3.Connection]:
    # Keep rollback journals: WAL loses cross-file atomicity for the attached
    # money/tombstone ledger. Reads need a snapshot, not a reserved writer.
    def acquire():
        db = sqlite3.connect(store.path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.create_function(
            "retention_expired",
            1,
            lambda created: int(expiry_cutoff is not None and created <= expiry_cutoff),
        )
        try:
            # ATTACH itself can encounter a pending writer. Recreate the
            # connection on BUSY, before any caller side effects can execute.
            db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            db.execute("ATTACH DATABASE ? AS deletion", (str(store.ledger),))
            if readonly:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                # Take both read locks before yielding to avoid a reader /
                # attached-ledger commit lock cycle.
                for schema in ("main", "deletion"):
                    db.execute(f"SELECT rootpage FROM {schema}.sqlite_master LIMIT 1").fetchall()
            else:
                db.execute("PRAGMA secure_delete=ON")
                db.execute("BEGIN IMMEDIATE")
            return db
        except BaseException:
            db.rollback()
            db.close()
            raise

    db = retry_busy(acquire, phase=f"{operation}:acquire", wait_seconds=lock_wait_seconds)
    try:
        started = time.monotonic()
        yield db
        # A busy COMMIT keeps this exact transaction open. Retry COMMIT only;
        # yielding the body again would duplicate files or provider effects.
        retry_busy(db.commit, phase=f"{operation}:commit", wait_seconds=lock_wait_seconds)
        elapsed = time.monotonic() - started
        if not readonly and elapsed >= 1:
            logging.getLogger("proofops_api.hosted_store").warning(
                "hosted sqlite writer operation=%s elapsed_ms=%d",
                operation,
                int(elapsed * 1000),
            )
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
