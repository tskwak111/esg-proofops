"""Explicit D1 four-page paid trial using shared provider and R108 budget fences.

Never creates another USD3 ledger or dispatches OpenRouter generation. Invoke one
case at a time; saved state is immutable and failures are not automatically retried.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.upstage import UpstageProbe
from proofops.adapters.local.upstage_parse import UpstageParseProbe
from proofops.adapters.parsing import gemini_vision

from evaluation import local_upstage_pilot as pilot
from scripts.finals_demo import FinalsBudget, parse_bound, pilot_argv

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
OUT = LAB / "openai"


def ledger_summary(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        rows = list(db.execute("select request_id,committed,receipt is null from probe_calls"))
    return dict(
        calls=len(rows),
        usd=str(sum((Decimal(r[1]) for r in rows), Decimal(0))),
        unsettled=sum(r[2] for r in rows),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["sk", "hyundai"], required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    state = OUT / ("D1-" + args.case)
    if state.exists():
        raise ValueError("D1_FRESH_STATE_REQUIRED")
    ledgers = {
        p: (ROOT / f".local/{p}/budget.sqlite3").resolve()
        for p in ("openai", "openrouter", "upstage")
    }
    spend = LAB / "sprint3/E2E/r108-spend.json"
    before = {p: ledger_summary(path) for p, path in ledgers.items()}
    (OUT / f"{args.case}-before.json").write_text(json.dumps(before, indent=2))
    # USD0.25 is cumulative across both D1 OpenAI cases; parse has its own
    # stricter USD0.15 task limit, both recorded in the existing R108 ledger.
    fence = FinalsBudget(
        spend, ledgers, OUT / "D1-paid-calls.jsonl", task="openai-D1", limit_usd="0.25"
    )
    parse_fence = FinalsBudget(
        spend, ledgers, OUT / "D1-paid-calls.jsonl", task="openai-D1-parse", limit_usd="0.15"
    )
    OpenAIProbe.complete = fence.guarded(
        OpenAIProbe.complete, "openai", lambda a, k: Decimal("0.02")
    )
    UpstageParseProbe.parse_async = parse_fence.guarded(
        UpstageParseProbe.parse_async, "upstage", parse_bound
    )

    def deny(*a, **k):
        raise ValueError("D1_UNACCOUNTED_DISPATCH_FORBIDDEN")

    UpstageProbe._post = deny
    UpstageParseProbe.parse = deny
    gemini_vision._request = deny
    original_vision = gemini_vision.parse_pages

    def bounded_vision(*a, **k):
        k["request"] = deny
        return original_vision(*a, **k)

    gemini_vision.parse_pages = bounded_vision
    template = json.loads(
        (LAB / f"sprint5/E2E3/states/{args.case}-attempt3/create-argv.json").read_text()
    )
    pdf = (
        next((ROOT / "기업보고서").rglob("KOR_SKI_2024.pdf"))
        if args.case == "sk"
        else Path(template[template.index("--pdf") + 1])
    )
    os.environ["PROOFOPS_LLM_PROVIDER"] = "openai"
    os.environ["PROOFOPS_RECEIPT_READ_PROFILE"] = "receipt-env-drift-v1"
    os.environ["LOCAL_LLM_MAX_WORKERS"] = "4"
    os.environ["PROOFOPS_FINALS_YEAR"] = "2024" if args.case == "sk" else "2025"
    argv = pilot_argv(template, pdf=pdf, state=state, port=50988, root=ROOT)
    for flag in ("--serve", "--serve-worker"):
        argv.remove(flag)
    port_index = argv.index("--port")
    del argv[port_index : port_index + 2]
    argv[argv.index("--pages") + 1] = "66,67" if args.case == "sk" else "22,41"
    argv.append("--invoke")
    (OUT / f"{args.case}-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=2))
    # Secondary parser credentials are read only from the authorized root file.
    read_text = Path.read_text

    def key_read(path, *a, **k):
        if path in (pilot.ROOT / ".env.upstage.local", pilot.ROOT / ".env.openrouter.local"):
            path = ROOT / path.name
        return read_text(path, *a, **k)

    Path.read_text = key_read
    sys.argv = argv
    started = time.monotonic()
    error, code = None, None
    try:
        code = pilot.main()
    except Exception as exc:
        error = type(exc).__name__
        raise
    finally:
        Path.read_text = read_text
        after = {p: ledger_summary(path) for p, path in ledgers.items()}
        (OUT / f"{args.case}-execution.json").write_text(
            json.dumps(
                dict(
                    seconds=round(time.monotonic() - started, 3),
                    exit_code=code,
                    error=error,
                    before=before,
                    after=after,
                    deltas={
                        p: dict(
                            calls=after[p]["calls"] - before[p]["calls"],
                            usd=str(Decimal(after[p]["usd"]) - Decimal(before[p]["usd"])),
                            unsettled=after[p]["unsettled"] - before[p]["unsettled"],
                        )
                        for p in ledgers
                    },
                ),
                indent=2,
            )
        )
        for budget in (fence, parse_fence):
            with budget.transaction() as (_, entry):
                entry["status"] = "stopped"
    return code


if __name__ == "__main__":
    raise SystemExit(main())
