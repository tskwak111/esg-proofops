"""Fresh tagging on a disposable copy of a retained extraction; no input writes."""

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path
from time import monotonic

from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.upstage_parse import UpstageParseProbe
from proofops_api.hosted_analysis import read_key
from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
from proofops_worker.composition import build_composition

from evaluation.k9_live import K9Budget
from evaluation.pa3_replay import fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # A failed job can exist before tag_job is attached to mutable run metadata.
    # Prepare that link only in a disposable seed; the failed source stays intact.
    with tempfile.TemporaryDirectory(prefix="proofops-k9-tag-seed-") as directory:
        seed = Path(directory) / "source"
        seed.mkdir()
        for name in ("objects", "parser-prepared"):
            shutil.copytree(args.source / name, seed / name)
        for name in ("settings.json", "parser.json", "upstage.sqlite3", "pilot.json"):
            shutil.copy2(args.source / name, seed / name)
        with sqlite3.connect(
            (args.source / "state.sqlite3").as_uri() + "?mode=ro", uri=True
        ) as original:
            with sqlite3.connect(seed / "state.sqlite3") as db:
                original.backup(db)
                state = json.loads(
                    db.execute("SELECT value FROM job_records WHERE kind='run'").fetchone()[0]
                )
                if "tag_job" not in state:
                    jobs = [
                        json.loads(raw)
                        for (raw,) in db.execute("SELECT value FROM job_records WHERE kind='job'")
                    ]
                    tags = [j["message"] for j in jobs if j["message"]["stage"] == "tag"]
                    if len(tags) != 1:
                        raise ValueError("K9_TAG_JOB_AMBIGUOUS")
                    state["tag_job"] = tags[0]
                    db.execute(
                        "UPDATE job_records SET value=? WHERE kind='run'", (json.dumps(state),)
                    )
        tenant, run = fixture(seed, args.output, "tag")
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
        LOCAL_LLM_MAX_WORKERS="8",
        LOCAL_DATABASE_PATH=str(args.output / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(args.output / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(args.output / "settings.json"),
        PROOFOPS_VERIFIED_READ_CACHE="exact-verified-read-v4",
    )
    root = Path("/path/to/ESG_ProofOps")
    shared = root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"
    original = OpenAIProbe.complete
    key = read_key(str(root / ".env.openai.local"), "OPENAI_API_KEY")

    def factory(_key, ledger, **kwargs):
        probe = OpenAIProbe(key, ledger, **kwargs)
        fence = K9Budget(
            shared, {"openai": probe.ledger.resolve()}, args.output.parent / "paid-calls.jsonl"
        )
        probe.complete = lambda *a, **kw: fence.guarded(
            original, "openai", lambda *a: Decimal(".02")
        )(probe, *a, **kw)
        return probe

    started = monotonic()

    class RetainedOnlyParser(UpstageParseProbe):
        def parse_async(self, *args, **kwargs):
            raise AssertionError("K9_FINISH_TAG_PARSER_DISPATCH_FORBIDDEN")

    with reader_scope(ReplayOCRStore(args.output / "upstage.sqlite3")):
        worker = build_composition(
            stage="tag",
            provider_factories={
                "llm": factory,
                "parse": lambda ledger: RetainedOnlyParser("offline-retained-source", ledger),
            },
            provider_ledgers=(args.output / "upstage.sqlite3", args.output / "live-luna.sqlite3"),
        )
        status = worker.run_once(tenant_id=tenant, run_id=run)
    result = dict(
        status=status,
        seconds=monotonic() - started,
        source=str(args.source),
        retained_extraction=True,
        fresh_model_tags=True,
        production_writes=0,
    )
    (args.output / "measurement.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
