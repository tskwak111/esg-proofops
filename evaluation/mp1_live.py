"""MP1: one source-bound AS1 run per report; USD1.20 shared task ceiling."""

import io
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from threading import Semaphore

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/parse/MP1"


def main():
    from proofops.adapters.local.decisions import DecisionProbe
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from pypdf import PdfReader

    from evaluation import local_upstage_pilot as pilot
    from scripts.finals_demo import FinalsBudget

    company = sys.argv[1]
    assert company in ("samsung", "kepco")
    plan = json.loads(
        (
            ROOT / f"outputs/agent-results/R108-redesign/lab/scope/AS1/{company}-plan.json"
        ).read_text()
    )
    state = OUT / "states" / company
    assert not state.exists(), "MP1 allows one fresh paid run per company"
    argv = json.loads(
        (
            ROOT / "outputs/agent-results/R108-redesign/lab/rehearsal/UR1/steel/live-argv.json"
        ).read_text()
    )
    for flag in ("--serve", "--serve-worker"):
        argv.remove(flag)
    for flag in ("--port", "--key-file"):
        i = argv.index(flag)
        del argv[i : i + 2]
    for flag, value in (
        ("--pdf", plan["source_path"]),
        ("--state", str(state)),
        ("--pages", ",".join(map(str, plan["selected_evidence_pages"]))),
        ("--parser", "mixed-v1"),
        ("--vision-parse", "off"),
        ("--claim-source-profile", "claim-source-v3"),
        ("--parser-max-output-bytes", "134217728"),
    ):
        argv[argv.index(flag) + 1] = value
    argv += [
        "--claim-pages",
        ",".join(map(str, plan["selected_claim_pages"])),
        "--pipeline-profile",
        "unattended-v1",
    ]
    # Reuse root key files in memory; never copy or print credentials.
    original_read = Path.read_text

    def key_read(path, *args, **kwargs):
        if path == pilot.ROOT / ".env.upstage.local":
            path = ROOT / ".env.upstage.local"
        return original_read(path, *args, **kwargs)

    Path.read_text = key_read
    ledgers = {
        name: ROOT / f".local/{name}/budget.sqlite3" for name in ("openai", "openrouter", "upstage")
    }

    class MP1Budget(FinalsBudget):
        def __init__(self):
            super().__init__(
                ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
                ledgers,
                OUT / "paid-calls.jsonl",
                task="parse-MP1",
            )
            # DEC-22/task parse-MP1 explicitly authorizes USD1.20 for both reports.
            # This subclass changes only this task ceiling; provider/global caps stay pinned.
            self.limit_usd = Decimal("1.20")
            with self.transaction() as (_, entry):
                if entry["delta_usd"] == "0" and entry["reserved_usd"] == "0":
                    entry["limit_usd"] = "1.20"
                assert Decimal(entry["limit_usd"]) == self.limit_usd

    budget = MP1Budget()
    budget.reserve(Decimal(".16"))  # eight concurrent calls * USD.02 minimum
    with budget.transaction() as (_, entry):
        entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - Decimal(".16"))
        entry["reservation_envelope_usd"] = ".16"
        entry["http_concurrency_limit"] = 8
        companies = entry.setdefault("companies_started", [])
        assert company not in companies
        companies.append(company)
        before = Decimal(entry["delta_usd"])
    slots = Semaphore(8)
    original_complete = OpenAIProbe.complete
    guarded_complete = budget.guarded(original_complete, "openai", lambda *args: Decimal(".02"))

    def complete(self, *args, **kwargs):
        with slots:
            return guarded_complete(self, *args, **kwargs)

    OpenAIProbe.complete = complete
    original_parse = UpstageParseProbe.parse_async

    def parse_bound(args, kwargs):
        pages = len(PdfReader(io.BytesIO(args[0]), strict=True).pages)
        assert 1 <= pages <= 10
        from proofops.adapters.local.upstage_parse import COST_PER_PAGE

        return max(Decimal(".02"), COST_PER_PAGE[kwargs.get("mode", "standard")] * pages)
        # Unknown provider calls still retain the provider's full USD1 ledger reservation.

    UpstageParseProbe.parse_async = budget.guarded(original_parse, "upstage", parse_bound)

    def deny(*args, **kwargs):
        raise RuntimeError("MP1_UNAUTHORIZED_PROVIDER")

    UpstageProbe._post = OpenRouterProbe._post = DecisionProbe._post = deny
    os.environ.update(LOCAL_LLM_MAX_WORKERS="8", PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT))
    (OUT / f"{company}-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=2) + "\n")
    sys.argv = argv + ["--key-file", str(ROOT / ".env.openai.local"), "--invoke"]
    started = time.monotonic()
    code = 1
    error = None
    try:
        code = pilot.main()
    except Exception as exc:
        error = type(exc).__name__
        raise
    finally:
        with budget.transaction() as (_, entry):
            record = dict(
                company=company,
                seconds=time.monotonic() - started,
                exit_code=code,
                task_usd=entry["delta_usd"],
                report_usd=str(Decimal(entry["delta_usd"]) - before),
                reserved_usd=entry["reserved_usd"],
                error_type=error,
            )
            entry.setdefault("runs", []).append(record)
        (OUT / f"{company}-live.json").write_text(json.dumps(record, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
