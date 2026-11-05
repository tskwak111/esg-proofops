"""Retry lock acquisition/commit, never replay a transaction's side effects."""

import logging
import sqlite3
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

BUSY_TIMEOUT_MS = 250
LOCK_WAIT_SECONDS = 10


def is_busy(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    return (
        (code & 0xFF) == sqlite3.SQLITE_BUSY
        if code is not None
        else str(exc) in {"database is locked", "database is busy"}
    )


def retry_busy(operation: Callable[[], T], *, phase: str, wait_seconds: float | None = None) -> T:
    deadline = time.monotonic() + (LOCK_WAIT_SECONDS if wait_seconds is None else wait_seconds)
    retries = 0
    while True:
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            remaining = deadline - time.monotonic()
            if not is_busy(exc) or remaining <= 0:
                raise
            retries += 1
            if retries == 1:
                logging.getLogger(__name__).warning("hosted sqlite busy phase=%s", phase)
            time.sleep(min(0.05 * min(retries, 5), remaining))
