"""Authorized two-page I4 canary; task and shared R108 money fences."""

import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_I4_POLICY

from evaluation.i1_live import main
from scripts.finals_demo import FinalsBudget


class I4Budget(FinalsBudget):
    def __init__(self, spend_path, events_path):
        self.task, self.limit_usd = "I4-integration", Decimal(".6")
        self.spend_path, self.events_path = spend_path, events_path
        self.ledgers = {}
        self.lock = threading.Lock()

    @contextmanager
    def transaction(self):
        # Same portable writer fence as P2; never reclaim a crashed writer.
        directory = self.spend_path.with_suffix(".p2-write-lock")
        deadline = time.monotonic() + 30
        while True:
            try:
                directory.mkdir(mode=0o700)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ValueError("I4_LEDGER_WRITER_ACTIVE") from None
                time.sleep(0.01)
        try:
            with super().transaction() as value:
                yield value
        finally:
            directory.rmdir()


if __name__ == "__main__":
    import json
    import sys

    from proofops.adapters.local.job_store import LocalSQLiteJobStore

    root = Path(sys.argv[sys.argv.index("--root") + 1])
    out = Path(sys.argv[sys.argv.index("--output") + 1])
    heartbeat = LocalSQLiteJobStore.heartbeat

    def diagnostic_heartbeat(store, *args, **kwargs):
        try:
            return heartbeat(store, *args, **kwargs)
        except Exception as error:
            # Error types/codes only. No lease weakening or retry.
            record = dict(
                exception_type=type(error).__name__,
                sqlite_errorname=getattr(error, "sqlite_errorname", None),
                sqlite_errorcode=getattr(error, "sqlite_errorcode", None),
            )
            with (out.parent / "heartbeat-errors.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")
            raise

    LocalSQLiteJobStore.heartbeat = diagnostic_heartbeat
    budget = I4Budget(
        root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
        out.parent / "paid-calls.jsonl",
    )
    original = OpenAIProbe.complete

    def guarded(probe, *args, **kwargs):
        # Provider ledgers belong to each new immutable scratch run.
        child = I4Budget(budget.spend_path, budget.events_path)
        child.ledgers = {"openai": probe.ledger.resolve()}
        return child.guarded(original, "openai", lambda *a: Decimal(".02"))(probe, *args, **kwargs)

    OpenAIProbe.complete = guarded
    result = main(
        claim_pages=dict(naver=[88], kia=[106]),
        workers=16,
        budget=".6",
        event_id="I4-USD0.6",
        integration_policy=FINALS_I4_POLICY,
    )
    raise SystemExit(
        0 if all(r["status"] == "completed" for r in result["results"].values()) else 1
    )
