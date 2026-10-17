"""Bounded private failure evidence, owned and purged with the source document.

Database projections are diagnostic copies, never recovery inputs. Only job and
provider accounting tables are copied: sessions, registry/cursor secrets, live
configuration, environment, subprocess output and uploaded files are excluded.
"""

import fcntl
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

MAX_RUN_BYTES = 128 * 1024 * 1024
MAX_FILES = 2048
TABLES = {
    "state.sqlite3": ("job_records", "run_snapshots", "usage_runs", "usage_attempts"),
    "luna.sqlite3": ("probe_policy", "probe_calls", "probe_transport_attempts"),
    "upstage.sqlite3": ("probe_policy", "probe_calls", "ocr_calls", "ocr_response_bytes"),
}
RECEIPTS = (
    "dispatch-failures",
    "tagging-receipts",
    "extraction-receipts",
    "luna.sqlite3.responses",
)


@contextmanager
def analysis_workspace(store, job, directory):
    with TemporaryDirectory(prefix="analysis-work-", dir=directory) as scratch:
        workspace = Path(scratch)
        try:
            yield workspace
        except BaseException as error:
            retain_failure(store, job, workspace, error)
            raise
        else:
            outcome = workspace / "state" / "outcome.json"
            try:
                failed = outcome.exists() and json.loads(outcome.read_bytes()).get("status") != (
                    "completed"
                )
            except (OSError, ValueError, AttributeError):
                failed = True
            if failed:
                retain_failure(store, job, workspace)


def failure_record(error):
    """Retain the original category and code, never arbitrary exception text."""
    from proofops.adapters.local.source_hx3 import failure_location

    code = getattr(error, "sqlite_errorcode", None)
    return dict(
        exception_type=type(error).__name__,
        sqlite_errorcode=code if type(code) is int else None,
        location=failure_location(error),
    )


def write_child_failure(state, error):
    # Parent collects this only after reaping the child and its process group.
    try:
        path = Path(state) / "failure.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            json.dump(failure_record(error), f)
    except (OSError, ValueError):
        pass


def _database(source, target, tables, limit):
    # CTAS deliberately omits executable triggers, identity/auth tables and free
    # pages containing deleted data. The read-only source is never modified.
    target.touch(mode=0o600, exist_ok=False)
    with closing(sqlite3.connect(target)) as db:
        db.execute("PRAGMA page_size=4096")
        db.execute(f"PRAGMA max_page_count={max(1, limit // 4096)}")
        db.execute("ATTACH DATABASE ? AS evidence", (source.resolve().as_uri() + "?mode=ro",))
        for table in tables:
            if db.execute(
                "SELECT 1 FROM evidence.sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                db.execute(f'CREATE TABLE "{table}" AS SELECT * FROM evidence."{table}"')
        db.commit()
    target.chmod(0o600)


def retain_failure(store, job, workspace, error=None):
    """Best effort, no change to accounting, fences, publication or failure flow."""
    if not store.settings.retain_failed_analysis:
        return
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    try:
        # The caller still owns analysis.lock, so purge cannot race retention.
        # One store-wide disk budget also covers concurrent document failures.
        lock_path = store.root / "analysis-diagnostics.lock"
        with lock_path.open("a+b") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            used = sum(
                p.stat().st_size
                for root in (store.root / "payloads").glob("*/*/analysis-failures")
                if not root.is_symlink()
                for p in root.rglob("*")
                if p.is_file() and not p.is_symlink()
            )
            remaining = min(MAX_RUN_BYTES, store.settings.failure_diagnostics_max_bytes - used)
            if remaining < 16384 or not directory.is_dir():
                return
            root = directory / "analysis-failures"
            root.mkdir(mode=0o700, exist_ok=True)
            if root.is_symlink():
                return
            root.chmod(0o700)
            target = root / f'{job["run_id"]}-{job["fence"]}'
            target.mkdir(mode=0o700)  # create only; never overwrite prior evidence
            state = workspace / "state"
            manifest = dict(
                schema="hosted-failure-diagnostics-v1",
                run_id=job["run_id"],
                fence=job["fence"],
                created=time.time(),
                parent_failure=failure_record(error) if error is not None else None,
                database_mode="diagnostic_projection_not_recovery",
                files=[],
                skipped=0,
                database_failures=[],
            )
            remaining -= 16384  # bounded manifest reserve
            for name, tables in TABLES.items():
                source, destination = state / name, target / name
                if not source.is_file() or source.is_symlink():
                    continue
                try:
                    _database(source, destination, tables, remaining)
                except sqlite3.Error as exc:
                    destination.unlink(missing_ok=True)
                    destination.with_name(name + "-journal").unlink(missing_ok=True)
                    manifest["skipped"] += 1
                    manifest["database_failures"].append(dict(file=name, **failure_record(exc)))
                    continue
                size = destination.stat().st_size
                if size > remaining:
                    destination.unlink()
                    manifest["skipped"] += 1
                    continue
                remaining -= size
                manifest["files"].append(name)
            candidates = [state / "failure.json", state / "outcome.json"]
            for name in RECEIPTS:
                parent = state / name
                if parent.is_dir() and not parent.is_symlink():
                    candidates.extend(parent.rglob("*.json"))
            copied = 0
            for source in candidates:
                if not source.is_file() or source.is_symlink():
                    continue
                relative = source.relative_to(state)
                if any(p.is_symlink() for p in source.parents if p != state and state in p.parents):
                    continue
                size = source.stat().st_size
                if size > remaining or copied >= MAX_FILES:
                    manifest["skipped"] += 1
                    continue
                destination = target / relative
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                for parent in destination.parents:
                    if parent == target:
                        break
                    parent.chmod(0o700)
                destination.touch(mode=0o600, exist_ok=False)
                shutil.copyfile(source, destination)
                destination.chmod(0o600)
                remaining -= size
                copied += 1
            manifest["receipt_files"] = copied
            with os.fdopen(
                os.open(target / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                "w",
            ) as stream:
                json.dump(manifest, stream)
    except (OSError, ValueError, sqlite3.Error) as exc:
        logging.getLogger(__name__).warning(
            "hosted failure diagnostics unavailable type=%s", type(exc).__name__
        )


def record_dispatch_failure(store, job, call_id, provider, input_sha, phase, error, context):
    """Finite metadata at the boundary before an exception changes run state."""
    # Kept in the same capped failure capture; no prompts, responses, or keys.
    settings = getattr(store, "settings", None)
    state = (
        context.get("state")
        if context and getattr(settings, "retain_failed_analysis", False)
        else None
    )
    if state is None:
        return
    record = failure_record(error) | dict(
        run_id=job["run_id"],
        fence=job["fence"],
        observed_at=time.time(),
        call_id=call_id,
        provider=provider,
        input_sha256=input_sha,
        phase=phase,
        role=context.get("role"),
        request_bytes=context.get("request_bytes"),
    )
    try:
        folder = Path(state) / "dispatch-failures"
        folder.mkdir(mode=0o700, exist_ok=True)
        # call_id is broker generated for hosted models; reject arbitrary paths.
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", call_id):
            return
        with os.fdopen(
            os.open(folder / (call_id + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as stream:
            json.dump(record, stream)
    except (OSError, ValueError):
        pass
