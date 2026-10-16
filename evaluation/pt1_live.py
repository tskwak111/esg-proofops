"""PT1: exactly two authorized fresh runs using cached parser responses."""

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import time
from decimal import Decimal
from pathlib import Path
from threading import Semaphore

ROOT = Path("/path/to/ESG_ProofOps")
APP = ROOT / ".local/r108-q9"
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/pipeline/PT1"
SPEND = ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"


def deny(*args, **kwargs):
    raise RuntimeError("PT1_UNAUTHORIZED_PROVIDER_OR_PARSE")


def main():
    company = sys.argv[1]
    assert company in ("skino", "steel")
    state = OUT / "states" / company
    assert not state.exists(), "PT1 permits one fresh paid run per company"
    from proofops.adapters.local.decisions import DecisionProbe
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.domain.provenance import canonical_hash

    from evaluation import local_upstage_pilot as pilot
    from scripts.finals_demo import FinalsBudget

    spec = importlib.util.spec_from_file_location(
        "pt1_cache", ROOT / "outputs/agent-results/R108-redesign/lab/sprint2/X1/prepare_e2e.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    sys.path[:] = [p for p in sys.path if "/.local/r108-sprint1" not in p]
    helper.install_cached_parse_only()
    UpstageProbe._post = OpenRouterProbe._post = DecisionProbe._post = deny
    read_text = Path.read_text

    def authorized_read(path, *args, **kwargs):
        if path in (APP / ".env.upstage.local", APP / ".env.openrouter.local"):
            return read_text(ROOT / path.name, *args, **kwargs)
        return read_text(path, *args, **kwargs)

    Path.read_text = authorized_read
    steel = ROOT / "outputs/agent-results/R108-redesign/lab/rehearsal/UR1/steel"
    prior = steel / "live" if company == "steel" else ROOT / ".local/r108-rh2-v2.90m7m22v/live"
    argv = json.loads((steel / "live-argv.json").read_text())
    # Remove serving flags; this bounded harness executes stages then exits.
    for flag in ("--serve", "--serve-worker"):
        if flag in argv:
            argv.remove(flag)
    for flag in ("--port", "--key-file"):
        if flag in argv:
            at = argv.index(flag)
            del argv[at : at + 2]
    meta = json.loads((prior / "pilot.json").read_text())
    for flag, value in [
        ("--state", str(state)),
        ("--pdf", meta["source_path"]),
        ("--pages", "18,25" if company == "steel" else "2,67"),
        ("--claim-source-profile", "claim-source-v3"),
    ]:
        argv[argv.index(flag) + 1] = value
    if company == "skino":
        for flag, value in [
            ("--report-year", "2024"),
            ("--period-start", "2024-01-01"),
            ("--period-end", "2024-12-31"),
        ]:
            argv[argv.index(flag) + 1] = value
    if "--claim-pages" in argv:
        at = argv.index("--claim-pages")
        del argv[at : at + 2]
    argv += ["--pipeline-profile", "unattended-v1"]
    sys.argv = argv
    assert pilot.main() == 0
    new = json.loads((state / "pilot.json").read_text())
    with sqlite3.connect((prior / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        snapshots = [json.loads(r[0]) for r in db.execute("select payload from run_snapshots")]
    assert any(
        s["selected_pages"] == new["selected_pages"]
        and s["document"]["sha256"] == new["source_sha256"]
        for s in snapshots
    )
    for folder in ("upstage-cache", "vision-cache"):
        src = prior / "parser-prepared" / folder / meta["tenant_id"]
        if src.exists():
            for file in src.glob("*.json"):
                raw = json.loads(file.read_text())
                if folder == "upstage-cache":
                    assert canonical_hash(raw["raw_batches"]) == raw["response_sha256"]
            shutil.copytree(src, state / "parser-prepared" / folder / new["tenant_id"])
    (state / "create-argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openai", "openrouter", "upstage")}
    budget = FinalsBudget(
        SPEND, ledgers, OUT / "paid-calls.jsonl", task="pipeline-PT1", limit_usd="0.30"
    )
    envelope = Decimal(".16")
    budget.reserve(envelope)
    with budget.transaction() as (_, entry):
        entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - envelope)
        entry["reservation_envelope_usd"] = ".16"
        entry["http_concurrency_limit"] = 8
        done = entry.setdefault("companies_started", [])
        assert company not in done, "No second paid run"
        done.append(company)
    guarded = budget.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal(".02"))
    slots = Semaphore(8)

    def complete(self, *args, **kwargs):
        with slots:
            return guarded(self, *args, **kwargs)

    OpenAIProbe.complete = complete
    os.environ.update(LOCAL_LLM_MAX_WORKERS="8", PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT))
    sys.argv = argv + ["--key-file", str(ROOT / ".env.openai.local"), "--invoke"]
    start = time.monotonic()
    code = 1
    try:
        code = pilot.main()
    finally:
        with budget.transaction() as (_, entry):
            record = dict(
                company=company,
                seconds=time.monotonic() - start,
                exit_code=code,
                cumulative_task_usd=entry["delta_usd"],
                reserved_usd=entry["reserved_usd"],
            )
            entry.setdefault("runs", []).append(record)
            entry["status"] = "measured"
        (OUT / f"{company}-live.json").write_text(json.dumps(record, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
