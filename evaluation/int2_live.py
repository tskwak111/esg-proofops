"""Authorized INT2: one fresh run for each MP1 original."""

import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT2"


def main():
    import io

    from proofops.adapters.local.decisions import DecisionProbe
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.local.upstage_parse import COST_PER_PAGE, UpstageParseProbe
    from pypdf import PdfReader

    from evaluation import local_upstage_pilot as pilot
    from scripts.finals_demo import FinalsBudget

    class INT2Budget(FinalsBudget):
        def __init__(self):
            super().__init__(
                ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
                {
                    n: ROOT / f".local/{n}/budget.sqlite3"
                    for n in ("openai", "openrouter", "upstage")
                },
                OUT / "paid-calls.jsonl",
                task="integ-INT2",
            )
            self.limit_usd = Decimal("1.50")
            with self.transaction() as (_, entry):
                if entry["delta_usd"] == "0" and entry["reserved_usd"] == "0":
                    entry["limit_usd"] = "1.50"
                assert Decimal(entry["limit_usd"]) == self.limit_usd

    budget = INT2Budget()
    OpenAIProbe.complete = budget.guarded(OpenAIProbe.complete, "openai", lambda *a: Decimal(".02"))

    def parse_bound(args, kwargs):
        return COST_PER_PAGE[kwargs.get("mode", "standard")] * len(
            PdfReader(io.BytesIO(args[0]), strict=True).pages
        )

    UpstageParseProbe.parse_async = budget.guarded(
        UpstageParseProbe.parse_async, "upstage", parse_bound
    )
    command = sys.argv[1]
    assert command in ("samsung", "kepco"), "INT2 authorizes only the two original runs"
    original_read = Path.read_text

    def key_read(path, *a, **k):
        if path == pilot.ROOT / ".env.upstage.local":
            path = ROOT / ".env.upstage.local"
        return original_read(path, *a, **k)

    Path.read_text = key_read
    assert command in ("samsung", "kepco")
    state = OUT / "states" / command
    assert not state.exists(), "only one new paid run per original"
    argv = json.loads(
        (
            ROOT / f"outputs/agent-results/R108-redesign/lab/parse/MP1/{command}-argv.json"
        ).read_text()
    )
    argv[argv.index("--state") + 1] = str(state)
    i = argv.index("--pipeline-profile")
    del argv[i : i + 2]
    argv += [
        "--analysis-profile",
        "finals-unattended-v1",
        "--key-file",
        str(ROOT / ".env.openai.local"),
        "--invoke",
    ]
    (OUT / f"{command}-argv.json").write_text(json.dumps(argv, ensure_ascii=False, indent=2) + "\n")

    def deny(*a, **k):
        raise ValueError("INT2_UNAUTHORIZED_PROVIDER")

    OpenRouterProbe._post = UpstageProbe._post = DecisionProbe._post = deny
    os.environ.update(
        PROOFOPS_OPENAI_RATE_OBSERVATION=str(
            ROOT / "outputs/agent-results/R108-redesign/lab/integ/INT1/rate-observation.json"
        ),
        PROOFOPS_SPEND_LEDGER=str(ROOT / ".local/finals-spend.sqlite3"),
        PROOFOPS_SPEND_GROUP="integ-INT2",
        PROOFOPS_SPEND_GROUP_LIMIT="1.5",
        PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT),
    )
    with budget.transaction() as (_, entry):
        companies = entry.setdefault("companies_started", [])
        assert command not in companies
        companies.append(command)
        before = Decimal(entry["delta_usd"])
        entry["prior_INT1_reservation_separate_usd"] = "1.00"
        entry["http_concurrency_envelope_usd"] = ".32"
    sys.argv = argv
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
                company=command,
                seconds=time.monotonic() - started,
                exit_code=code,
                report_usd=str(Decimal(entry["delta_usd"]) - before),
                task_usd=entry["delta_usd"],
                reserved_usd=entry["reserved_usd"],
                error_type=error,
            )
            entry.setdefault("runs", []).append(record)
        (OUT / f"{command}-live.json").write_text(json.dumps(record, indent=2) + "\n")
    return code


def _key(path):
    for line in path.read_text().splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError("OPENAI_API_KEY_MISSING")


if __name__ == "__main__":
    raise SystemExit(main())
