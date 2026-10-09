"""Finish the same SK run: reuse settled extraction, forbid extraction dispatch."""

import importlib.util
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from threading import Semaphore
from uuid import uuid4

from evaluation.pt1_live import APP, OUT, ROOT, SPEND, deny


def main():
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.local.upstage import UpstageProbe

    from evaluation import local_upstage_pilot as pilot
    from scripts.finals_demo import FinalsBudget

    state = OUT / "states/skino"
    meta = json.loads((state / "pilot.json").read_text())
    argv = json.loads((state / "create-argv.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "pt1_cache_resume",
        ROOT / "outputs/agent-results/R108-redesign/lab/sprint2/X1/prepare_e2e.py",
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    sys.path[:] = [p for p in sys.path if "/.local/r108-sprint1" not in p]
    helper.install_cached_parse_only()
    UpstageProbe._post = OpenRouterProbe._post = deny
    read = Path.read_text

    def redirected(path, *args, **kwargs):
        if path in (APP / ".env.upstage.local", APP / ".env.openrouter.local"):
            return read(ROOT / path.name, *args, **kwargs)
        return read(path, *args, **kwargs)

    Path.read_text = redirected
    store = LocalSQLiteRunStore(state / "state.sqlite3")
    run = store.jobs.get_run(meta["tenant_id"], meta["run_id"])
    assert run["current_stage"] == "extract" and run["status"] in ("partial", "running")
    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openai", "openrouter", "upstage")}
    budget = FinalsBudget(
        SPEND, ledgers, OUT / "paid-calls.jsonl", task="pipeline-PT1", limit_usd=".30"
    )
    budget.reserve(Decimal(".16"))
    with budget.transaction() as (_, entry):
        entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - Decimal(".16"))
        assert entry["companies_started"].count("skino") == 1
        entry["settled_extraction_replay"] = True
    guarded = budget.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal(".02"))
    slots = Semaphore(8)

    def complete(self, *args, **kwargs):
        assert "extraction_profile" not in json.loads(
            args[1]
        ), "PT1_REPEAT_EXTRACTION_DISPATCH_FORBIDDEN"
        with slots:
            return guarded(self, *args, **kwargs)

    OpenAIProbe.complete = complete
    if run["status"] == "partial":
        store.jobs.retry_run(
            meta["tenant_id"],
            meta["run_id"],
            expected_revision=run["revision"],
            idempotency_key=str(uuid4()),
            reason=(
                "PT1 settled extraction replay; HTTP503 source unknown; " "no extraction dispatch"
            ),
            now=int(time.time()),
            actor_sub="PT1",
        )
    os.environ.update(LOCAL_LLM_MAX_WORKERS="8", PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT))
    sys.argv = argv + ["--key-file", str(ROOT / ".env.openai.local"), "--invoke"]
    began = time.monotonic()
    code = 1
    try:
        code = pilot.main()
    finally:
        with budget.transaction() as (_, entry):
            record = dict(
                company="skino",
                seconds=time.monotonic() - began,
                exit_code=code,
                cumulative_task_usd=entry["delta_usd"],
                reserved_usd=entry["reserved_usd"],
                same_run=True,
                repeat_extraction_dispatch=False,
            )
            entry.setdefault("runs", []).append(record)
        (OUT / "skino-settled-replay.json").write_text(json.dumps(record, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
