"""Authorized LG fresh-model comparison on disposable, source-attested fixtures.

Parser/OCR inputs are retained; extraction, preliminary, relations and all three
element replicas call the real model. Never publishes an imported run to hosted
users. A single shared SpendGuard covers both fresh runs and every retry.
"""

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from uuid import UUID, uuid4

from proofops.adapters.parsing.parser_artifacts import read_parser_json

from evaluation.pa3_replay import checkpoint, fixture


def pin_scratch_policy(output, tenant, run):
    from proofops.application.analysis_profile import V2_POLICY
    from proofops.domain.provenance import canonical_hash

    with sqlite3.connect(output / "state.sqlite3") as db:
        triggers = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        for name, _ in triggers:
            assert name.replace("_", "").isalnum()
            db.execute(f"DROP TRIGGER {name}")
        frozen = json.loads(
            db.execute("SELECT payload FROM run_snapshots WHERE run_id=?", (run,)).fetchone()[0]
        )
        old = frozen["input_hash"]
        frozen["analysis_profile_policy"] = V2_POLICY
        frozen["analysis_profile_policy_sha256"] = canonical_hash(V2_POLICY)
        frozen["input_hash"] = canonical_hash(
            {k: v for k, v in frozen.items() if k != "input_hash"}
        )

        def update(value):
            if isinstance(value, dict):
                return {
                    k: frozen["input_hash"] if k == "input_hash" and v == old else update(v)
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [update(v) for v in value]
            return value

        db.execute("UPDATE run_snapshots SET payload=? WHERE run_id=?", (json.dumps(frozen), run))
        for kind, key, raw in db.execute(
            "SELECT kind,record_id,value FROM job_records WHERE run_id=?", (run,)
        ).fetchall():
            db.execute(
                "UPDATE job_records SET value=? WHERE run_id=? AND kind=? AND record_id=?",
                (json.dumps(update(json.loads(raw))), run, kind, key),
            )
        # Re-publication in this disposable copied stream needs fresh audit IDs.
        # Immutable original streams, source fixtures and database guards stay intact.
        for table in ("audit_events", "audit_heads"):
            db.execute(f"DELETE FROM {table} WHERE tenant_id=? AND run_id=?", (tenant, run))
        for _, sql in triggers:
            db.execute(sql)
    return frozen


def main():
    from decimal import Decimal

    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.spend_guard import SpendGuard
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops_api.hosted_analysis import read_key
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
    from proofops_worker.composition import build_composition
    from proofops_worker.extract_batch import run_batches

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spend-ledger", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--reuse-cache", type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    manifest = json.loads((source / "pilot.json").read_text())
    run = manifest["run_id"]
    tenant, run = fixture(source, output, "parse")
    frozen = pin_scratch_policy(output, tenant, run)
    (output / "pilot.json").write_text(json.dumps(manifest | dict(evaluation_only=True)))
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
        LOCAL_LLM_MAX_WORKERS=str(args.workers),
        LOCAL_DATABASE_PATH=str(output / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(output / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(output / "settings.json"),
        PROOFOPS_DISPLAY_PREFETCH_WORKERS="4",
        PROOFOPS_VERIFIED_READ_CACHE="exact-verified-read-v3",
    )
    grant = SpendGuard(
        args.spend_ledger, event_id="PA4-USD1.5", daily_limit="1.5", event_limit="1.5"
    )
    experiment = str(uuid4())
    grant.configure_run(experiment, day=time.strftime("%Y-%m-%d", time.gmtime()), run_limit=".75")
    api_key = read_key(str(args.key_file), "OPENAI_API_KEY")
    original = OpenAIProbe.complete
    # Fresh experiments use independent caches; a third replay may explicitly
    # point at the first cache to prove no paid calls or new model outputs.
    cache_path = args.reuse_cache or output / "model-responses.sqlite3"

    def factory(_key, ledger, **kwargs):
        probe = OpenAIProbe(api_key, ledger, **kwargs)
        probe.response_cache_path = cache_path
        if args.reuse_cache:
            # A reuse check must never silently purchase a cache miss.
            probe._post = lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("PA4_REUSE_PROVIDER_DISPATCH_FORBIDDEN")
            )
        guarded = grant.guarded(
            original,
            run_id=experiment,
            provider="openai:" + experiment,
            bound=lambda *a: Decimal(".02"),
        )
        probe.complete = lambda *a, **kw: guarded(probe, *a, **kw)
        return probe

    with sqlite3.connect((source / "upstage.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        parse_receipt = next(
            json.loads(raw)
            for (raw,) in db.execute("SELECT receipt FROM probe_calls WHERE receipt IS NOT NULL")
            if "duration_seconds" in json.loads(raw)
        )
    raw_batches = json.loads(next((source / "parse-responses").glob("*-async.json")).read_text())

    class RetainedParse(UpstageParseProbe):
        def parse_async(self, pdf_bytes, *, request_id, mode="standard"):
            from hashlib import sha256

            from proofops.adapters.local.upstage_parse import PARSE_MODEL_PINNED
            from proofops.domain.provenance import canonical_hash

            assert (
                canonical_hash(
                    dict(
                        model=PARSE_MODEL_PINNED,
                        mode=mode,
                        pdf_sha256=sha256(pdf_bytes).hexdigest(),
                        pages=parse_receipt["pages"],
                        bytes_len=len(pdf_bytes),
                        transport="async",
                    )
                )
                == parse_receipt["request_sha256"]
            )
            self._post_parse = lambda *a: dict(request_id=parse_receipt["provider_request_id"])
            self._async_status = lambda *a: dict(
                status="completed",
                total_pages=parse_receipt["pages"],
                completed_pages=parse_receipt["pages"],
                model=parse_receipt["provider_model"],
                batches=[
                    dict(download_url=f"https://replay.files.upstage.ai/{i}")
                    for i in range(len(raw_batches))
                ],
            )
            self._async_download = lambda url: raw_batches[int(url.rsplit("/", 1)[1])]
            return super().parse_async(pdf_bytes, request_id=request_id, mode=mode) | dict(
                duration_seconds=parse_receipt["duration_seconds"]
            )

    factories = dict(llm=factory, parse=lambda ledger: RetainedParse("offline-fixture", ledger))
    original_dir = next((source / "parser-prepared").rglob("manifest.json")).parent
    from proofops.adapters.parsing import opendataloader, upstage_document

    batches = read_parser_json(original_dir / "candidates.json")
    ids = {b["parser_name"]: UUID(b["parser_run_id"]) for b in batches}
    original_batch = opendataloader._batch

    def batch(*a, auxiliary=False, **kw):
        previous = opendataloader.uuid4
        opendataloader.uuid4 = lambda: ids["pdfplumber" if auxiliary else "opendataloader"]
        try:
            return original_batch(*a, auxiliary=auxiliary, **kw)
        finally:
            opendataloader.uuid4 = previous

    opendataloader._batch = batch
    upstage_document.uuid4 = lambda: ids["upstage_async_standard"]

    def raw_parser(command, work, env, profile):
        for name in (
            "source.json",
            "source.md",
            "source-repaired.json",
            "auxiliary.json",
            "geometry.json",
            "table-repair.json",
            "launcher-stderr.txt",
        ):
            shutil.copy2(original_dir / name, work / name)

    timings, statuses = {}, {}
    start = time.monotonic()
    try:
        with reader_scope(ReplayOCRStore(output / "upstage.sqlite3")):
            for stage in ("parse", "extract", "tag"):
                worker = build_composition(
                    stage=stage,
                    verify_paragraphs=stage == "parse",
                    provider_factories=factories,
                    provider_ledgers=(output / "upstage.sqlite3", output / "live-luna.sqlite3"),
                )
                if stage == "parse":
                    worker.parser._execute = raw_parser
                began = time.monotonic()
                try:
                    status = worker.run_once(tenant_id=tenant, run_id=run)
                    statuses[stage] = status
                    print(json.dumps(dict(stage=stage, status=status)), flush=True)
                    assert status == ("completed" if stage == "tag" else "committed"), status
                    if stage == "extract":
                        batches = run_batches(worker, tenant_id=tenant, run_id=run, batches=100)
                        assert not batches or not batches[-1].get("stop_code"), batches[-1].get(
                            "stop_code"
                        )
                    result = checkpoint(output, stage)
                    (output / (stage + "-checkpoint.json")).write_text(
                        json.dumps(result, ensure_ascii=False)
                    )
                finally:
                    timings[stage] = time.monotonic() - began
                    worker.uploads.close()
                    worker.uploads.registry.close()
    finally:
        probe = OpenAIProbe(api_key, output / "live-luna.sqlite3")
        measurement = dict(
            seconds=time.monotonic() - start,
            stages=statuses,
            stage_seconds=timings,
            analysis_policy_sha256=frozen["analysis_profile_policy_sha256"],
            model=probe.model,
            provider=probe.summary(),
            shared_spend=grant.summary(),
            workers=args.workers,
            parser="retained-source-attested-LG-13-pages",
            evaluation_only=True,
            original_inputs_untouched=True,
        )
        (output / "measurement.json").write_text(json.dumps(measurement, indent=2))
        print(json.dumps(measurement), flush=True)


if __name__ == "__main__":
    main()
