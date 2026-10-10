"""Process-local composition for the integrated profile; provider caps remain active."""

import io
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import BoundedSemaphore, Lock

from proofops.adapters.local.spend_guard import SpendGuard

_SESSION_LOCK = Lock()


def workers_from_headers(headers):
    """Conservative burst bound: two paid attempts, full input/output capacity per slot."""
    try:
        requests = min(
            int(headers["x-ratelimit-limit-requests"]),
            int(headers["x-ratelimit-remaining-requests"]),
        )
        tokens = min(
            int(headers["x-ratelimit-limit-tokens"]), int(headers["x-ratelimit-remaining-tokens"])
        )
        return max(1, min(16, requests // 2, tokens // (2 * (32768 + 4096))))
    except (TypeError, KeyError, ValueError):
        return 8  # unobserved headers never authorize an increase


def profile_workers():
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
def _spend_session(run_id):
    """Bind dispatches for a single sequential worker session, including its threads.

    Hosted callers may instead use SpendGuard.reserve/settle directly per request.
    Overlapping sessions in one interpreter fail closed; processes share SQLite.
    """
    from pypdf import PdfReader

    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.upstage_parse import COST_PER_PAGE, UpstageParseProbe

    root = Path(__file__).resolve().parents[4]
    guard = SpendGuard(
        Path(os.environ.get("PROOFOPS_SPEND_LEDGER", root / ".local/finals-spend.sqlite3")),
        event_id=os.environ.get("PROOFOPS_SPEND_EVENT", "finals-v1"),
    )
    guard.configure_run(
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

    def parse_bound(args, kwargs):
        pages = len(PdfReader(io.BytesIO(args[0]), strict=True).pages)
        return COST_PER_PAGE[kwargs.get("mode", "standard")] * pages

    OpenAIProbe.complete = guard.guarded(
        old_complete, run_id=run_id, provider="openai", bound=lambda *a: Decimal(".02"), slots=slots
    )
    UpstageParseProbe.parse_async = guard.guarded(
        old_parse, run_id=run_id, provider="upstage", bound=parse_bound
    )
    try:
        yield guard
    finally:
        OpenAIProbe.complete, UpstageParseProbe.parse_async = old_complete, old_parse
        for key, value in [
            ("LOCAL_LLM_MAX_WORKERS", old_workers),
            ("PROOFOPS_DISPLAY_PREFETCH_WORKERS", old_display),
        ]:
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def spend_session(run_id):
    if not _SESSION_LOCK.acquire(blocking=False):
        raise ValueError("PROFILE_WORKER_SESSION_BUSY")
    try:
        with _spend_session(run_id) as guard:
            yield guard
    finally:
        _SESSION_LOCK.release()
