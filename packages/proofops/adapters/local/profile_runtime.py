"""Process-local composition for the integrated profile; provider caps remain active."""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, cast

from proofops.adapters.local.spend_guard import SpendGuard

_SESSION_LOCK = Lock()


def workers_from_headers(headers: Mapping[str, str | None]) -> int:
    """Conservative burst bound: two paid attempts, full input/output capacity per slot."""
    try:
        requests = min(
            int(cast(str, headers["x-ratelimit-limit-requests"])),
            int(cast(str, headers["x-ratelimit-remaining-requests"])),
        )
        tokens = min(
            int(cast(str, headers["x-ratelimit-limit-tokens"])),
            int(cast(str, headers["x-ratelimit-remaining-tokens"])),
        )
        return max(1, min(24, requests // 2, tokens // (2 * (32768 + 4096))))
    except (TypeError, KeyError, ValueError):
        return 8  # unobserved headers never authorize an increase


def profile_workers() -> int:
    path = os.environ.get("PROOFOPS_OPENAI_RATE_OBSERVATION")
    if not path:
        return min(8, int(os.environ.get("LOCAL_LLM_MAX_WORKERS", "8")))
    data = json.loads(Path(path).read_text())
    age = datetime.now(UTC).timestamp() - data["captured_at_epoch"]
    if not 0 <= age <= 86400 or data["model"] != "gpt-6-luna":
        raise ValueError("OPENAI_RATE_OBSERVATION_EXPIRED")
    return min(
        workers_from_headers(data["headers"]), int(os.environ.get("LOCAL_LLM_MAX_WORKERS", "16"))
    )


@contextmanager
def _spend_session(run_id: str) -> Iterator[SpendGuard]:
    """Bind dispatches for a single sequential worker session, including its threads.

    Hosted callers may instead use SpendGuard.reserve/settle directly per request.
    Overlapping sessions in one interpreter fail closed; processes share SQLite.
    """
    from pypdf import PdfReader

    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.upstage_parse import COST_PER_PAGE, UpstageParseProbe

    root = Path(__file__).resolve().parents[4]
    # Untyped dependency is outside S_ADB ownership.
    guard = SpendGuard(  # type: ignore[no-untyped-call]
        Path(os.environ.get("PROOFOPS_SPEND_LEDGER", root / ".local/finals-spend.sqlite3")),
        event_id=os.environ.get("PROOFOPS_SPEND_EVENT", "finals-v1"),
    )
    # Untyped dependency is outside S_ADB ownership.
    guard.configure_run(  # type: ignore[no-untyped-call]
        run_id,
        day=datetime.now(UTC).date().isoformat(),
        group_id=os.environ.get("PROOFOPS_SPEND_GROUP"),
        group_limit=os.environ.get("PROOFOPS_SPEND_GROUP_LIMIT"),
    )
    workers = profile_workers()
    slots = BoundedSemaphore(workers)
    old_workers = os.environ.get("LOCAL_LLM_MAX_WORKERS")
    old_display = os.environ.get("PROOFOPS_DISPLAY_PREFETCH_WORKERS")
    os.environ.update(LOCAL_LLM_MAX_WORKERS=str(workers), PROOFOPS_DISPLAY_PREFETCH_WORKERS="4")
    old_complete, old_parse = OpenAIProbe.complete, UpstageParseProbe.parse_async

    def parse_bound(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Decimal:
        pages = len(PdfReader(io.BytesIO(args[0]), strict=True).pages)
        return COST_PER_PAGE[kwargs.get("mode", "standard")] * pages

    # Preserve the existing scoped method binding and restoration.
    OpenAIProbe.complete = guard.guarded(  # type: ignore[method-assign, no-untyped-call]
        old_complete, run_id=run_id, provider="openai", bound=lambda *a: Decimal(".02"), slots=slots
    )
    # Preserve the existing scoped method binding and restoration.
    UpstageParseProbe.parse_async = guard.guarded(  # type: ignore[method-assign, no-untyped-call]
        old_parse, run_id=run_id, provider="upstage", bound=parse_bound
    )
    try:
        yield guard
    finally:
        # Preserve the existing scoped method binding and restoration.
        OpenAIProbe.complete, UpstageParseProbe.parse_async = old_complete, old_parse  # type: ignore[method-assign]
        for key, value in [
            ("LOCAL_LLM_MAX_WORKERS", old_workers),
            ("PROOFOPS_DISPLAY_PREFETCH_WORKERS", old_display),
        ]:
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def spend_session(run_id: str) -> Iterator[SpendGuard]:
    if not _SESSION_LOCK.acquire(blocking=False):
        raise ValueError("PROFILE_WORKER_SESSION_BUSY")
    try:
        with _spend_session(run_id) as guard:
            yield guard
    finally:
        _SESSION_LOCK.release()
