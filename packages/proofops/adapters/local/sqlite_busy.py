"""Bounded SQLite lock waits; never replay a transaction body or provider call."""

import sqlite3
import time
from contextlib import contextmanager

BUSY_TIMEOUT_SECONDS = 0.25
LOCK_WAIT_SECONDS = 30


def is_busy(error):
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    return str(error) in {
        "database is locked",
        "database is busy",
        "database table is locked",
    }


def retry_busy(operation):
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            return operation()
        except sqlite3.OperationalError as error:
            remaining = deadline - time.monotonic()
            if not is_busy(error) or remaining <= 0:
                raise
            time.sleep(min(0.05, remaining))


class _Connection(sqlite3.Connection):
    acquire_wait_seconds = 0.0


@contextmanager
def connection(path, *, readonly=False, uri=False):
    """Acquire before yielding, retry COMMIT in place, roll back every failed body.

    Writers acquire IMMEDIATE before any reads, avoiding read-to-write upgrades.
    Readers acquire their snapshot before yielding. Neither body is replayed.
    The final SQLite wait can extend each 30s retry budget by at most 250ms.
    """
    db = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_SECONDS,
        isolation_level=None,
        uri=uri,
        factory=_Connection,
    )
    started = time.monotonic()
    try:

        def acquire():
            try:
                db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
                if readonly:
                    # Reading the schema cookie pins the snapshot without a data SELECT.
                    db.execute("PRAGMA schema_version").fetchall()
            except BaseException:
                db.rollback()
                raise

        retry_busy(acquire)
        db.acquire_wait_seconds = time.monotonic() - started
        yield db
        retry_busy(db.commit)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def error_summary(error):
    """Only fixed SQLite message categories; identifiers, paths and SQL never escape."""
    message = str(error).lower()
    exact = {
        "database is locked",
        "database is busy",
        "database table is locked",
        "disk i/o error",
        "database or disk is full",
        "unable to open database file",
        "attempt to write a readonly database",
        "database disk image is malformed",
        "interrupted",
    }
    summary = message if message in exact else "SQLite operational error (detail redacted)"
    for prefix in ("no such table:", "no such column:", "database table is locked:"):
        if message.startswith(prefix):
            summary = prefix + " [redacted]"
            break
    code = getattr(error, "sqlite_errorcode", None)
    return dict(
        exception_type="OperationalError",
        message_summary=summary,
        sqlite_errorcode=code if type(code) is int else None,
    )
