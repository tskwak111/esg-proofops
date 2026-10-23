"""Hosted retention; every operation uses the facade's shared transaction context."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from proofops_api.hosted_contracts import (
    HostedError,
    digest,
)

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore


def delete_document(
    store: HostedStore, auth: Any, document: str, key: str, *, now: float
) -> dict[str, Any]:
    if not isinstance(key, str) or not 16 <= len(key) <= 128:
        raise HostedError("IDEMPOTENCY_KEY_INVALID", 400)
    with store.transaction() as db:
        owner = db.execute(
            "SELECT user_hash FROM document_owners WHERE tenant_id=? " "AND document_id=?",
            (auth.tenant_id, document),
        ).fetchone()
        if not auth.has_capability("admin") and (
            owner is None or owner[0] != store.user_hash(auth.user_sub)
        ):
            store._document(db, auth.tenant_id, document)
            raise HostedError("FORBIDDEN", 403)
        row = db.execute(
            "SELECT * FROM deletion.tombstones WHERE tenant_id=? AND document_id=?",
            (auth.tenant_id, document),
        ).fetchone()
        if row is None:
            store._document(db, auth.tenant_id, document)
            db.execute(
                "INSERT INTO deletion.tombstones VALUES (?,?,?,?,?)",
                (auth.tenant_id, document, str(uuid4()), now, digest(key)),
            )
            db.execute(
                "UPDATE runs SET status='cancelled',fence=fence+1,lease_until=0 WHERE "
                "tenant_id=? AND document_id=?",
                (auth.tenant_id, document),
            )
            store.guest.audit(db, auth, "delete", document, now)
    # Tombstone is durable before any filesystem deletion.
    return store._purge(auth.tenant_id, document, now)


def _purge(store: HostedStore, tenant: str, document: str, now: float) -> dict[str, Any]:
    status = "completed"
    try:
        with store.transaction(readonly=True) as db:
            if not store._deleted(db, tenant, document):
                raise HostedError("TOMBSTONE_REQUIRED")
            backups = db.execute("SELECT path FROM backups").fetchall()
        path = store.document_dir(tenant, document)
        if path.exists():
            lock_path = path / "analysis.lock"
            if lock_path.exists():
                # The committed tombstone fences new users; keep the existing
                # document lease while removing bytes, without a DB writer.
                with lock_path.open("a+b") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    shutil.rmtree(path)
            else:
                shutil.rmtree(path)
        for backup in backups:
            target = Path(backup[0]) / "artifacts" / tenant / document
            if target.exists():
                shutil.rmtree(target)
        with store.transaction() as db:
            if not store._deleted(db, tenant, document):
                raise HostedError("TOMBSTONE_REQUIRED")
            runs = db.execute(
                "SELECT run_id FROM runs WHERE tenant_id=? AND document_id=?",
                (tenant, document),
            ).fetchall()
            for run in runs:
                store._settle_envelope(db, run[0])
                db.execute("DELETE FROM run_progress WHERE run_id=?", (run[0],))
                db.execute("DELETE FROM run_claim_progress WHERE run_id=?", (run[0],))
                db.execute("DELETE FROM run_claim_stage_progress WHERE run_id=?", (run[0],))
                db.execute("DELETE FROM result_snapshots WHERE run_id=?", (run[0],))
            db.execute(
                "DELETE FROM document_owners WHERE tenant_id=? AND document_id=?",
                (tenant, document),
            )
            db.execute("DELETE FROM runs WHERE tenant_id=? AND document_id=?", (tenant, document))
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
    with store.transaction() as db:
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


def replay_deletions(store: HostedStore, *, now: float) -> None:
    with store.transaction(readonly=True) as db:
        rows = db.execute("SELECT tenant_id,document_id FROM deletion.tombstones").fetchall()
    for row in rows:
        result = store._purge(row[0], row[1], now)
        if result["status"] != "completed":
            raise HostedError("PURGE_INCOMPLETE", 503)


def maintain(store: HostedStore, *, now: float) -> None:
    # API and worker both maintain this volume. Serialize filesystem GC
    # separately so slow unlink never reserves the control/ledger writer.
    with (store.root / "maintenance.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        store._maintain(now=now)


def _maintain(store: HostedStore, *, now: float) -> None:
    with store.transaction() as db:
        store._expire_running(db, now)
        expired = db.execute(
            "SELECT tenant_id,document_id FROM documents WHERE expires<=?", (now,)
        ).fetchall()
        for row in expired:
            if not store._deleted(db, row[0], row[1]):
                db.execute(
                    "INSERT INTO deletion.tombstones VALUES (?,?,?,?,?)",
                    (row[0], row[1], str(uuid4()), now, digest("expiry")),
                )
        backups = db.execute("SELECT path FROM backups WHERE expires<=?", (now,)).fetchall()
        db.execute("DELETE FROM sessions WHERE expires<=? OR idle<=? OR revoked=1", (now, now))
        store.access.maintain(db, now, store.settings.audit_days)
        store.guest.maintain(db, now)
        db.execute("DELETE FROM invitations WHERE expires<=? OR used=1", (now,))
        db.execute("DELETE FROM rate_limits WHERE bucket<?", (int(now // 60) - 2,))
        cutoff = now - store.settings.audit_days * 86400
        db.execute("DELETE FROM rc1_reuse_audit WHERE created<?", (cutoff,))
        db.execute("DELETE FROM deletion.source_retention WHERE created<?", (cutoff,))
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
    for backup in backups:
        target = Path(backup[0])
        if target.exists():
            shutil.rmtree(target)
        with store.transaction() as db:
            db.execute("DELETE FROM backups WHERE path=? AND expires<=?", (backup[0], now))
    store.replay_deletions(now=now)
    with store.transaction(expiry_cutoff=now - store.settings.audit_days * 86400) as db:
        expired = db.execute(
            "SELECT t.tenant_id,t.document_id FROM deletion.tombstones t "
            "JOIN deletion.attempts a USING(tenant_id,document_id) "
            "WHERE t.created<=? AND a.status='completed'",
            (now - store.settings.audit_days * 86400,),
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
    trash = store.root / ".maintenance-trash"
    trash.mkdir(mode=0o700, exist_ok=True)
    with store.transaction() as db:
        known = {
            (row[0], row[1]) for row in db.execute("SELECT tenant_id,document_id FROM documents")
        }
        payloads = store.root / "payloads"
        if payloads.exists():
            for tenant in payloads.iterdir():
                for doc in tenant.iterdir():
                    if (tenant.name, doc.name) not in known:
                        # Atomic detachment keeps the upload race fenced.
                        os.rename(doc, trash / str(uuid4()))
    for orphan in trash.iterdir():
        shutil.rmtree(orphan)


def backup(store: HostedStore, target: Path, *, now: float) -> Path:
    """Operator-only stopped-service backup, allowlist excludes raw bytes and sessions."""
    target = target.resolve()
    if target.exists() or target == store.root or store.root.is_relative_to(target):
        raise ValueError("new backup directory required")
    target.mkdir(parents=True, mode=0o700)
    with store.transaction() as db:
        # SQLite online backup from a separate read connection, while writer fence is held.
        source = sqlite3.connect(store.path)
        destination = sqlite3.connect(target / "control.sqlite3")
        try:
            source.backup(destination)
            destination.execute("PRAGMA secure_delete=ON")
            for table in (
                "sessions",
                "invitations",
                "memberships",
                "rate_limits",
                "backups",
                "access_sessions",
                "access_login_failures",
                "access_login_locks",
                "access_auth_audit",
                "guest_session_starts",
                "guest_audit",
            ):
                destination.execute(f"DELETE FROM {table}")
            destination.commit()
            destination.execute("VACUUM")
        finally:
            source.close()
            destination.close()
        for doc in db.execute("SELECT tenant_id,document_id,created FROM documents"):
            if store._deleted(db, doc[0], doc[1]):
                continue
            path = store.document_dir(doc[0], doc[1])
            for kind in ("receipt", "graph", "export"):
                source_dir = path / kind
                if source_dir.exists():
                    dest = target / "artifacts" / doc[0] / doc[1] / kind
                    shutil.copytree(source_dir, dest)
        oldest = db.execute("SELECT min(created) FROM documents").fetchone()[0]
        expires = (
            min(now, oldest if oldest is not None else now) + store.settings.backup_days * 86400
        )
        db.execute("INSERT INTO backups VALUES (?,?,?)", (str(target), now, expires))
        store._write(
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


def restore(store: HostedStore, backup: Path, *, now: float) -> None:
    """Restore payload/control rows only; never roll back deletion or money ledgers."""
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest["schema"] != 1 or manifest["expires"] <= now:
        raise HostedError("BACKUP_EXPIRED")
    with store.transaction() as db:
        identity = db.execute("SELECT ledger_id FROM deletion.identity WHERE id=1").fetchone()[0]
        if manifest.get("ledger_id") != identity:
            raise HostedError("LEDGER_RECOVERY_REQUIRED", 503)
        db.execute("ATTACH DATABASE ? AS recovered", (str(backup / "control.sqlite3"),))
        # Only still-active document metadata; original deliberately unavailable on restore.
        for row in db.execute(
            "SELECT * FROM recovered.documents WHERE expires>?", (now,)
        ).fetchall():
            if store._deleted(db, row["tenant_id"], row["document_id"]):
                continue
            db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?)", tuple(row))
            source = backup / "artifacts" / row["tenant_id"] / row["document_id"]
            if source.exists():
                dest = store.document_dir(row["tenant_id"], row["document_id"])
                shutil.copytree(source, dest, dirs_exist_ok=True)
    store.replay_deletions(now=now)
