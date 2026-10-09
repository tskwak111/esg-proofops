"""QI1's two authorized fresh runs, sharing a USD1 task reservation."""

import io
import json
import os
import sqlite3
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/quality/QI1"


def budget():
    from scripts.finals_demo import FinalsBudget

    fence = FinalsBudget(
        ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
        {n: ROOT / f".local/{n}/budget.sqlite3" for n in ("openai", "openrouter", "upstage")},
        OUT / "paid-calls.jsonl",
        task="quality-QI1",
    )
    fence.limit_usd = Decimal("1.0")
    with fence.transaction() as (_, entry):
        if entry["delta_usd"] == "0" and entry["reserved_usd"] == "0":
            entry["limit_usd"] = "1.0"
        assert Decimal(entry["limit_usd"]) == fence.limit_usd
        entry["authorized_scope"] = "QA1 20 samples tagging only; Samsung/KEPCO once, MP1 originals"
        entry["profile"] = "finals-unattended-v2"
    return fence


def install_guards(fence):
    from proofops.adapters.local.decisions import DecisionProbe
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.local.upstage_parse import COST_PER_PAGE, UpstageParseProbe
    from pypdf import PdfReader

    def parse_bound(args, kwargs):
        return COST_PER_PAGE[kwargs.get("mode", "standard")] * len(
            PdfReader(io.BytesIO(args[0]), strict=True).pages
        )

    OpenAIProbe.complete = fence.guarded(OpenAIProbe.complete, "openai", lambda *a: Decimal(".02"))
    UpstageParseProbe.parse_async = fence.guarded(
        UpstageParseProbe.parse_async, "upstage", parse_bound
    )

    def deny(*a, **k):
        raise ValueError("QI1_UNAUTHORIZED_PROVIDER")

    OpenRouterProbe._post = UpstageProbe._post = DecisionProbe._post = deny
    os.environ.update(
        PROOFOPS_OPENAI_RATE_OBSERVATION=str(
            ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT1/rate-observation.json"
        ),
        PROOFOPS_SPEND_LEDGER=str(ROOT / ".local/finals-spend.sqlite3"),
        PROOFOPS_SPEND_GROUP="quality-QI1",
        PROOFOPS_SPEND_GROUP_LIMIT="1.0",
        PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT),
    )


def main():
    from evaluation import local_upstage_pilot as pilot

    company = sys.argv[1]
    assert company in ("samsung", "kepco") and len(sys.argv) == 2
    fence = budget()
    install_guards(fence)
    state = OUT / "states" / company
    if state.exists():
        prior = json.loads((OUT / f"{company}-live.json").read_text())
        with sqlite3.connect(state / "state.sqlite3") as db:
            runs = db.execute("select count(*) from run_snapshots").fetchone()[0]
        assert prior["exit_code"] == 1 and Decimal(prior["report_usd"]) == 0 and runs == 0
        failed = state.with_name(company + "-preflight-failed-" + str(time.time_ns()))
        state.rename(failed)
        (OUT / (failed.name + ".json")).write_text(json.dumps(prior, indent=2) + "\n")
    old_read = Path.read_text

    def read_key(path, *a, **k):
        if path == pilot.ROOT / ".env.upstage.local":
            path = ROOT / ".env.upstage.local"
        return old_read(path, *a, **k)

    Path.read_text = read_key
    argv = json.loads(
        (
            ROOT / f"outputs/agent-results/R108-redesign/lab/parse/MP1/{company}-argv.json"
        ).read_text()
    )
    argv[argv.index("--state") + 1] = str(state)
    i = argv.index("--pipeline-profile")
    del argv[i : i + 2]
    argv += [
        "--analysis-profile",
        "finals-unattended-v2",
        "--key-file",
        str(ROOT / ".env.openai.local"),
        "--invoke",
    ]
    (OUT / f"{company}-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=2) + "\n")
    with fence.transaction() as (_, entry):
        started_companies = entry.setdefault("companies_started", [])
        if company in started_companies:
            assert list(OUT.glob(company + "-preflight-failed*.json"))
        else:
            started_companies.append(company)
        before = Decimal(entry["delta_usd"])
    sys.argv = argv
    started, code = time.monotonic(), 1
    import traceback

    from proofops.application.runs import RunRejected

    reject = RunRejected.__init__

    def diagnose(self, code, *args, **kwargs):
        if code == "CONFIG_GATE_BLOCKED":
            caller = traceback.extract_stack(limit=2)[0]
            print("QI1_CONFIG_GATE_LINE", caller.lineno, flush=True)
        reject(self, code, *args, **kwargs)

    RunRejected.__init__ = diagnose
    try:
        code = pilot.main()
    finally:
        Path.read_text = old_read
        with fence.transaction() as (_, entry):
            result = dict(
                company=company,
                seconds=time.monotonic() - started,
                exit_code=code,
                report_usd=str(Decimal(entry["delta_usd"]) - before),
                task_usd=entry["delta_usd"],
                reserved_usd=entry["reserved_usd"],
            )
            entry.setdefault("runs", []).append(result)
        (OUT / f"{company}-live.json").write_text(json.dumps(result, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
