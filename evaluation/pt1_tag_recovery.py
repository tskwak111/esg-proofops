"""Same SK run: existing proof-bounded recovery of never-sent preliminary calls."""

import importlib.util
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from threading import Semaphore

from evaluation.pt1_live import APP, OUT, ROOT, SPEND, deny


def main():
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.adapters.local.tag_store import LocalTagStore
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.registry import Registry
    from proofops.application.uploads import UploadService
    from proofops_worker.tag_recovery import authorize_recovery, plan_recovery, recovery_proof

    from evaluation import local_upstage_pilot as pilot
    from scripts.finals_demo import FinalsBudget

    state = OUT / "states/skino"
    meta = json.loads((state / "pilot.json").read_text())
    argv = json.loads((state / "create-argv.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "pt1_cache_recovery",
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
    uploads = UploadService(store.path, state / "objects", Registry.sqlite(store.path))
    tags = LocalTagStore(store, uploads, OpenDataLoaderParser(state / "parser-prepared"))
    receipts = state / "tagging-receipts" / meta["run_id"]
    proof = recovery_proof(store.usage.cost_data(meta["tenant_id"], meta["run_id"]), receipts)
    ack = proof["classes"].get("unresolved_failure", []) + proof["classes"].get(
        "receipt_failure_without_ledger", []
    )
    plan_path = OUT / "skino-recovery-plan.json"
    if plan_path.exists():
        from proofops_worker.tag_recovery import TagRecoveryPlan

        stored = json.loads(plan_path.read_text())
        plan = TagRecoveryPlan.from_dict(stored["plan"])
        proof = stored["proof"]
        ack = list(plan.acknowledged_failures)
        run = store.jobs.get_run(meta["tenant_id"], meta["run_id"])
    else:
        plan, proof, run = plan_recovery(
            store,
            tags,
            tenant_id=meta["tenant_id"],
            run_id=meta["run_id"],
            receipts=receipts,
            claim_limit=18,
            max_new_requests=153,
            acknowledged_failures=ack,
            authorized_by="PT1: authorized one-run completion; never-sent proof only",
            now=int(time.time()),
        )
    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openai", "openrouter", "upstage")}
    budget = FinalsBudget(
        SPEND, ledgers, OUT / "paid-calls.jsonl", task="pipeline-PT1", limit_usd=".30"
    )
    budget.reserve(Decimal(".16"))
    with budget.transaction() as (_, entry):
        entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - Decimal(".16"))
        assert (
            not entry.get("tag_recovery_authorized")
            or entry["tag_recovery_authorized"]["recovery_job_id"] == plan.recovery_job_id
        )
        entry["tag_recovery_authorized"] = plan.to_dict()
    if not plan_path.exists():
        authorize_recovery(store, plan, proof, run, now=int(time.time()))
    (OUT / "skino-recovery-plan.json").write_text(
        json.dumps({"plan": plan.to_dict(), "proof": proof}, indent=2) + "\n"
    )
    guarded = budget.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal(".02"))
    slots = Semaphore(8)

    def complete(self, system, user, *args, **kwargs):
        data = json.loads(user)
        assert "extraction_profile" not in data, "PT1_REPEAT_EXTRACTION_DISPATCH_FORBIDDEN"
        with slots:
            return guarded(self, system, user, *args, **kwargs)

    OpenAIProbe.complete = complete
    os.environ.update(LOCAL_LLM_MAX_WORKERS="8", PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT))
    sys.argv = argv + ["--key-file", str(ROOT / ".env.openai.local"), "--invoke"]
    began = time.monotonic()
    code = 1
    try:
        code = pilot.main()
    finally:
        with budget.transaction() as (_, entry):
            record = dict(
                seconds=time.monotonic() - began,
                exit_code=code,
                cumulative_task_usd=entry["delta_usd"],
                reserved_usd=entry["reserved_usd"],
                claims_authorized=len(plan.claim_ids),
                never_sent_reissued=len(plan.reissued_request_ids),
                acknowledged_not_retried=ack,
            )
            entry.setdefault("runs", []).append(record)
        (OUT / "skino-recovery.json").write_text(json.dumps(record, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
