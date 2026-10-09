"""PF1: two authorized opt-in runs; cached parsing only; shared USD .25 envelope."""

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
from uuid import uuid4

ROOT = Path("/Users/ss020/Dev/ESG_ProofOps")
APP = ROOT / ".local/r108-q9"
OUT = ROOT / "outputs/agent-results/R108-redesign/lab/perf/PF1"
SPEND = ROOT / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"


def deny(*args, **kwargs):
    raise RuntimeError("PF1_NEW_PARSER_OR_OTHER_PROVIDER_FORBIDDEN")


def wait_for_budget_slot(call, budget):
    while True:
        try:
            return call()
        except ValueError as error:
            if str(error) != "R108_FINALS_BUDGET_EXHAUSTED":
                raise
            with budget.transaction() as (_, entry):
                if Decimal(entry["reserved_usd"]) == 0:
                    raise
            time.sleep(0.1)


def main():
    company = sys.argv[1]
    assert company in ("skino", "naver")
    state = OUT / "states" / company
    recovery = len(sys.argv) == 3 and sys.argv[2] == "recover-unsubmitted"
    assert recovery or not state.exists(), "PF1 one fresh run per company"
    assert not recovery or company == "naver"
    from proofops.adapters.local.decisions import DecisionProbe
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openrouter import OpenRouterProbe
    from proofops.adapters.local.upstage import UpstageProbe

    from evaluation import local_upstage_pilot as pilot
    from scripts.finals_demo import FinalsBudget

    spec = importlib.util.spec_from_file_location(
        "pf1_parse_cache",
        ROOT / "outputs/agent-results/R108-redesign/lab/sprint2/X1/prepare_e2e.py",
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
    naver_state = ROOT / "outputs/agent-results/R108-redesign/lab/decision/RH5/states/control/naver"
    prior = naver_state if company == "naver" else ROOT / ".local/r108-rh2-v2.90m7m22v/live"
    argv = json.loads((naver_state / "create-argv.json").read_text())
    argv[argv.index("--state") + 1] = str(state)
    if company == "skino":
        meta = json.loads((prior / "pilot.json").read_text())
        for flag, value in [
            ("--pdf", meta["source_path"]),
            ("--pages", "2,67"),
            ("--report-year", "2024"),
            ("--period-start", "2024-01-01"),
            ("--period-end", "2024-12-31"),
        ]:
            argv[argv.index(flag) + 1] = value
        at = argv.index("--claim-pages")
        del argv[at : at + 2]
    if not recovery:
        # Preparation performs no model dispatch. Cache reuse checks PDF/page/parser identity.
        sys.argv = argv
        assert pilot.main() == 0
        if company == "naver":
            helper.copy_parse_cache(prior, state)
        else:
            from proofops.domain.provenance import canonical_hash

            old_meta = json.loads((prior / "pilot.json").read_text())
            new_meta = json.loads((state / "pilot.json").read_text())
            with sqlite3.connect((prior / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
                frozen = json.loads(
                    db.execute(
                        "select payload from run_snapshots where run_id=?",
                        ("3f4f63c5-253a-472a-9628-6c97487c2c8f",),
                    ).fetchone()[0]
                )
            assert frozen["selected_pages"] == new_meta["selected_pages"] == [2, 67]
            assert frozen["document"]["sha256"] == new_meta["source_sha256"]
            for folder in ("upstage-cache", "vision-cache"):
                src = prior / "parser-prepared" / folder / old_meta["tenant_id"]
                if src.exists():
                    for file in src.glob("*.json"):
                        raw = json.loads(file.read_text())
                        if folder == "upstage-cache":
                            assert canonical_hash(raw["raw_batches"]) == raw["response_sha256"]
                    shutil.copytree(src, state / "parser-prepared" / folder / new_meta["tenant_id"])

        (state / "create-argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    else:
        from proofops.adapters.local.run_store import LocalSQLiteRunStore

        metadata = json.loads((state / "pilot.json").read_text())
        argv = json.loads((state / "create-argv.json").read_text())
        aborted = state / "extraction-aborted-before-dispatch"
        aborted.mkdir(exist_ok=True)
        archived = []
        with sqlite3.connect(
            (ROOT / ".local/openai/budget.sqlite3").as_uri() + "?mode=ro", uri=True
        ) as db:
            for failure in (state / "extraction-receipts").glob("*/failure.json"):
                rid = json.loads(failure.read_text())["request_id"]
                assert (
                    db.execute("select 1 from probe_calls where request_id=?", (rid,)).fetchone()
                    is None
                )
                assert not (failure.parent / "raw_response.json").exists()
                archived.append(rid)
                failure.parent.rename(aborted / failure.parent.name)
        assert len(archived) == 74
        (OUT / "naver-reservation-recovery.json").write_text(
            json.dumps(
                dict(
                    never_dispatched=archived,
                    paid_receipts_reused=156,
                    reason="Pre-dispatch reservation rejection; no dispatched retry",
                ),
                indent=2,
            )
            + "\n"
        )
        store = LocalSQLiteRunStore(state / "state.sqlite3")
        current = store.jobs.get_run(metadata["tenant_id"], metadata["run_id"])
        store.jobs.retry_run(
            metadata["tenant_id"],
            metadata["run_id"],
            expected_revision=current["revision"],
            idempotency_key=str(uuid4()),
            reason="PF1 replay 156 receipts; finish 74 unsubmitted requests within original cap",
            now=int(time.time()),
            actor_sub="PF1",
        )
    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openai", "openrouter", "upstage")}
    budget = FinalsBudget(
        SPEND, ledgers, OUT / "paid-calls.jsonl", task="perf-PF1", limit_usd="0.25"
    )
    # Reserve the full possible in-flight eight-call exposure before the first dispatch.
    workers = 7 if recovery else 8
    envelope = Decimal(workers) * Decimal(".02")
    budget.reserve(envelope)
    with budget.transaction() as (_, entry):
        entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - envelope)
        entry["reservation_envelope_usd"] = ".16"
        entry["http_concurrency_limit"] = 8
        done = entry.setdefault("companies_started", [])
        assert (
            recovery
            or company not in done
            or (
                Decimal(entry["delta_usd"]) == 0
                and all(r["exit_code"] != 0 for r in entry.get("runs", []))
            )
        ), "No second paid run"
        done.append(company)
    guarded = budget.guarded(OpenAIProbe.complete, "openai", lambda *args: Decimal(".02"))
    slots = Semaphore(workers)

    def complete(self, *args, **kwargs):
        with slots:
            return wait_for_budget_slot(lambda: guarded(self, *args, **kwargs), budget)

    OpenAIProbe.complete = complete
    os.environ.update(
        PROOFOPS_DISPLAY_PREFETCH_WORKERS="4",
        LOCAL_LLM_MAX_WORKERS=str(workers),
        PROOFOPS_DECISION_PROJECT_ROOT=str(ROOT),
    )
    sys.argv = argv + ["--key-file", str(ROOT / ".env.openai.local"), "--invoke"]
    started = time.monotonic()
    code = 1
    try:
        code = pilot.main()
    finally:
        with budget.transaction() as (_, entry):
            record = dict(
                company=company,
                seconds=time.monotonic() - started,
                exit_code=code,
                display_prefetch_workers=4,
                http_concurrency_limit=workers,
                recovery_unsubmitted=recovery,
                cumulative_task_usd=entry["delta_usd"],
                reserved_usd=entry["reserved_usd"],
            )
            entry.setdefault("runs", []).append(record)
            entry["status"] = "complete" if company == "naver" and code == 0 else "measured"
        (OUT / f"{company}-live{'-recovered' if recovery else ''}.json").write_text(
            json.dumps(record, indent=2) + "\n"
        )
        assert Decimal(record["cumulative_task_usd"]) <= Decimal(".25")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
