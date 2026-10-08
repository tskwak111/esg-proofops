"""Private R108 finals session using the existing pilot and provider ledgers."""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
TASK = "sprint6-F8"


class FinalsBudget:
    """Reserve across threads/processes before dispatch; retain uncertain charges."""

    def __init__(self, spend_path: Path, ledgers: dict[str, Path], events_path: Path):
        self.spend_path, self.ledgers, self.events_path = spend_path, ledgers, events_path
        self.lock = threading.Lock()

    @contextmanager
    def transaction(self):
        with self.lock, self.spend_path.with_suffix(".decisions.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.spend_path.read_text())
            entries = data.setdefault("executions", [])
            entry = next((e for e in entries if e.get("task") == TASK), None)
            if entry is None:
                entry = dict(
                    task=TASK,
                    sprint=6,
                    limit_usd="0.50",
                    delta_usd="0",
                    reserved_usd="0",
                    status="running",
                )
                entries.append(entry)
            yield data, entry
            temporary = self.spend_path.with_suffix(".f8.tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(self.spend_path)

    def unsettled(self):
        amount = Decimal(0)
        for ledger in self.ledgers.values():
            with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
                amount += sum(
                    (
                        Decimal(r[0])
                        for r in db.execute(
                            "select committed from probe_calls where receipt is null"
                        )
                    ),
                    Decimal(0),
                )
        return amount

    def reserve(self, bound: Decimal):
        if not bound.is_finite() or bound <= 0:
            raise ValueError("R108_FINALS_INVALID_RESERVATION")
        with self.transaction() as (data, entry):
            pending = Decimal(entry["reserved_usd"])
            if Decimal(entry["delta_usd"]) + pending + bound > Decimal("0.50"):
                raise ValueError("R108_FINALS_BUDGET_EXHAUSTED")
            # Preserve the cumulative R108 cap and every provider's unsettled ledger row.
            if Decimal(data["cumulative_usd"]) + self.unsettled() + pending + bound > Decimal(
                data["limit_usd"]
            ):
                raise ValueError("R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED")
            entry["reserved_usd"] = str(pending + bound)
            entry["status"] = "running"

    def guarded(self, original, provider, reserve):
        def call(probe, *args, **kwargs):
            ledger = self.ledgers[provider]
            if not probe.ledger.samefile(ledger):
                raise ValueError("R108_FINALS_SHARED_LEDGER_REQUIRED")
            request_id = kwargs["request_id"]
            with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
                previous = db.execute(
                    "select committed,receipt from probe_calls where request_id=?", (request_id,)
                ).fetchone()
            # The provider owns cache/retry integrity; cached settled calls cost no new money.
            if previous:
                if previous[1] is None:
                    raise ValueError("R108_FINALS_UNSETTLED_RETRY_FORBIDDEN")
                return original(probe, *args, **kwargs)
            bound = reserve(args, kwargs)
            self.reserve(bound)
            started, error = time.monotonic(), None
            try:
                return original(probe, *args, **kwargs)
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                with self.transaction() as (data, entry):
                    with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
                        row = db.execute(
                            "select committed,receipt from probe_calls where request_id=?",
                            (request_id,),
                        ).fetchone()
                    charged = Decimal(row[0]) if row else Decimal(0)
                    entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - bound)
                    entry["delta_usd"] = str(Decimal(entry["delta_usd"]) + charged)
                    data["cumulative_usd"] = str(Decimal(data["cumulative_usd"]) + charged)
                    event = dict(
                        provider=provider,
                        request_id=request_id,
                        seconds=round(time.monotonic() - started, 3),
                        planned_usd=str(bound),
                        committed_usd=str(charged),
                        unsettled=bool(row and row[1] is None),
                        error=error,
                    )
                    with self.events_path.open("a") as stream:
                        stream.write(json.dumps(event) + "\n")

        return call


def parse_bound(args, kwargs):
    from proofops.adapters.local.upstage_parse import COST_PER_PAGE
    from pypdf import PdfReader

    mode = kwargs.get("mode", "standard")
    if mode not in COST_PER_PAGE:
        raise ValueError("R108_FINALS_PARSE_MODE_INVALID")
    pages = len(PdfReader(io.BytesIO(args[0]), strict=True).pages)
    if not 1 <= pages <= 2:
        raise ValueError("R108_FINALS_TWO_PAGE_SCOPE_REQUIRED")
    return COST_PER_PAGE[mode] * pages


def pilot_argv(template: list[str], *, pdf: Path, state: Path, port: int, root: Path):
    argv = list(template)
    # New web runs choose their own pages; do not inherit a saved report's
    # narrower extraction pages. The existing pilot then extracts the chosen scope.
    claim_pages = argv.index("--claim-pages")
    del argv[claim_pages : claim_pages + 2]
    for flag, value in (
        ("--pdf", str(pdf)),
        ("--state", str(state)),
        ("--pages", "66,67"),
        ("--report-year", os.environ.get("PROOFOPS_FINALS_YEAR", "2024")),
        ("--period-start", os.environ.get("PROOFOPS_FINALS_START", "2024-01-01")),
        ("--period-end", os.environ.get("PROOFOPS_FINALS_END", "2024-12-31")),
    ):
        argv[argv.index(flag) + 1] = value
    assert not any(
        flag in argv
        for flag in (
            "--preliminary-profile",
            "--preliminary-p2",
            "--extraction-atomic",
            "--invoke",
            "--resume",
        )
    )
    assert argv[argv.index("--relation-profile") + 1] == "occurrence-v3"
    assert argv[argv.index("--claim-source-profile") + 1] == "glyph-alignment-v1"
    assert argv[argv.index("--display-text-profile") + 1] == "glyph-joined-display-v1"
    argv += [
        "--key-file",
        str(root / ".env.openrouter.local"),
        "--port",
        str(port),
        "--serve",
        "--serve-worker",
    ]
    return argv


def configure_concurrency() -> int:
    """Use the worker's bounded default while respecting an operator's lower cap."""
    try:
        workers = int(os.environ.get("LOCAL_LLM_MAX_WORKERS", "16"))
    except ValueError:
        raise ValueError("LOCAL_LLM_CONFIGURATION_INVALID") from None
    if not 1 <= workers <= 16:
        raise ValueError("LOCAL_LLM_CONFIGURATION_INVALID")
    os.environ["LOCAL_LLM_MAX_WORKERS"] = str(workers)
    return workers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--kakao-port", type=int, required=True)
    args = parser.parse_args()
    workers = configure_concurrency()
    root, run_root = args.root.resolve(), args.run_root.resolve()
    ledgers = {
        name: (root / f".local/{name}/budget.sqlite3").resolve()
        for name in ("upstage", "openrouter")
    }
    for name, ledger in ledgers.items():
        if not ledger.is_file() or not (APP / f".local/{name}/budget.sqlite3").samefile(ledger):
            raise ValueError("R108_FINALS_SHARED_LEDGER_REQUIRED")
    pdf = (
        Path(os.environ["PROOFOPS_FINALS_PDF"])
        if os.environ.get("PROOFOPS_FINALS_PDF")
        else next((root / "기업보고서").rglob("KOR_SKI_2024.pdf"))
    )
    template = json.loads((run_root / "profile/create-argv.json").read_text())
    argv = pilot_argv(template, pdf=pdf, state=run_root / "live", port=args.port, root=root)
    (run_root / "live-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=2))
    fence = FinalsBudget(
        root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
        ledgers,
        run_root / "paid-calls.jsonl",
    )
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops.adapters.parsing import gemini_vision

    OpenRouterProbe.complete = fence.guarded(
        OpenRouterProbe.complete, "openrouter", lambda a, k: Decimal("0.02")
    )
    UpstageParseProbe.parse_async = fence.guarded(
        UpstageParseProbe.parse_async, "upstage", parse_bound
    )

    def deny(*a, **k):
        raise ValueError("R108_FINALS_UNACCOUNTED_DISPATCH_FORBIDDEN")

    # Existing auto-vision policy remains pinned; uncached unledgered vision cannot dispatch.
    UpstageProbe._post = deny
    UpstageParseProbe.parse = deny
    gemini_vision._request = deny
    vision_parse = gemini_vision.parse_pages

    def bounded_vision(*a, **k):
        k["request"] = deny
        return vision_parse(*a, **k)

    gemini_vision.parse_pages = bounded_vision
    # Existing pilot resolves the secondary parser key relative to the checkout.
    # Redirect only that read to its existing authorized file; never copy credentials.
    read_text = Path.read_text

    def key_read(path, *a, **k):
        if path == APP / ".env.upstage.local":
            path = root / ".env.upstage.local"
        return read_text(path, *a, **k)

    Path.read_text = key_read
    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    child = None
    with (run_root / "kakao.log").open("w") as log:
        try:
            child = subprocess.Popen(
                [
                    sys.executable,
                    str(APP / "scripts/submission_demo.py"),
                    "--seed",
                    str(run_root / "kakao-seed"),
                    "--demo-state",
                    str(run_root / "kakao-state"),
                    "--port",
                    str(args.kakao_port),
                ],
                cwd=APP,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            (run_root / "processes.json").write_text(
                json.dumps(dict(live=os.getpid(), kakao=child.pid))
            )
            # Saved-state replay verification can take >30s under load (seen 2026-10-09).
            deadline = time.monotonic() + int(os.environ.get("PROOFOPS_KAKAO_START_TIMEOUT", "120"))
            while not (run_root / "kakao-state/browser.json").is_file():
                if child.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("R108_FINALS_KAKAO_START_FAILED")
                time.sleep(0.1)
            browser = json.loads((run_root / "kakao-state/browser.json").read_text())
            print("Kakao saved walkthrough: " + browser["login_url"], flush=True)
            print(
                f"Live analysis: OpenRouter Luna · occurrence-v3 · 66,67 · "
                f"USD0.50 cap · {workers} workers",
                flush=True,
            )
            from evaluation.local_upstage_pilot import main as pilot_main

            sys.argv = argv
            return pilot_main()
        finally:
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=10)
            with fence.transaction() as (_, entry):
                entry["status"] = "stopped"
            Path.read_text = read_text


if __name__ == "__main__":
    raise SystemExit(main())
