"""Offline retained-response parse/tag benchmark, with original provenance IDs."""

import argparse
import cProfile
import functools
import json
import os
import shutil
import socket
import sqlite3
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

from proofops.adapters.parsing.parser_artifacts import read_parser_json


def checkpoint(directory, stage):
    with sqlite3.connect((directory / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        run = json.loads(db.execute("SELECT value FROM job_records WHERE kind='run'").fetchone()[0])
        job = run[stage + "_job"]["job_id"]
        return json.loads(
            db.execute(
                "SELECT value FROM job_records WHERE kind='artifact' AND record_id LIKE ?",
                (f"job/{job}/%/checkpoint",),
            ).fetchone()[0]
        )


def normalize_timing(value):
    if isinstance(value, dict):
        return {
            k: normalize_timing(v)
            for k, v in value.items()
            if k
            not in {"latency_ms", "duration_seconds", "provider_scheduler", "connection_attempts"}
        }
    if isinstance(value, list):
        return [normalize_timing(v) for v in value]
    return value


def retained_parse_batches(source, receipt):
    from proofops.domain.provenance import canonical_hash

    candidates = [
        json.loads(path.read_text()) for path in (source / "parse-responses").glob("*-async.json")
    ]
    for path in (source / "parser-prepared" / "upstage-cache").rglob("*.json"):
        value = json.loads(path.read_text())
        if "raw_batches" in value:
            candidates.append(value["raw_batches"])
    return next(
        value for value in candidates if canonical_hash(value) == receipt["response_sha256"]
    )


def fixture(source, output, stage):
    assert not output.exists() and source != output
    output.mkdir(parents=True, mode=0o700)
    for name in ("objects", "parser-prepared"):
        shutil.copytree(source / name, output / name)
    for name in ("settings.json", "parser.json", "upstage.sqlite3", "pilot.json"):
        shutil.copy2(source / name, output / name)
    with sqlite3.connect((source / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(output / "state.sqlite3") as copied:
            original.backup(copied)
    manifest = json.loads((source / "pilot.json").read_text())
    run, tenant = manifest["run_id"], manifest["tenant_id"]
    with sqlite3.connect(output / "state.sqlite3") as db:
        triggers = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        for name, _ in triggers:
            assert name.replace("_", "").isalnum()
            db.execute(f"DROP TRIGGER {name}")
        state = json.loads(
            db.execute("SELECT value FROM job_records WHERE kind='run'").fetchone()[0]
        )
        job = state[stage + "_job"]["job_id"]
        for kind, key, raw in db.execute("SELECT kind,record_id,value FROM job_records").fetchall():
            v = json.loads(raw)
            remove = kind in {"document_evidence_search", "element_evidence_search"}
            if stage == "parse":
                remove |= kind != "run" and not (
                    (kind == "job" and key == job)
                    or (kind == "outbox" and v["message"]["job_id"] == job)
                )
            else:
                remove |= kind == "artifact" and key.startswith(f"job/{job}/")
                remove |= kind == "usage" and v.get("message", {}).get("stage") == "tag"
            if remove:
                db.execute("DELETE FROM job_records WHERE kind=? AND record_id=?", (kind, key))
            elif kind == "job" and key == job:
                v.update(
                    status="pending",
                    lease_owner=None,
                    lease_until=None,
                    heartbeat_at=0,
                    next_attempt_at=0,
                )
                db.execute(
                    "UPDATE job_records SET value=? WHERE kind='job' AND record_id=?",
                    (json.dumps(v), key),
                )
            elif kind == "outbox" and v["message"]["job_id"] == job:
                v.update(status="pending", attempts=0, next_attempt_at=0)
                db.execute(
                    "UPDATE job_records SET value=? WHERE kind='outbox' AND record_id=?",
                    (json.dumps(v), key),
                )
        for key in ("tag_job", "tag_snapshot_sha256", "tag_stage_status"):
            state.pop(key, None)
        if stage == "parse":
            for key in ("parse_job", "extract_job", "claim_snapshot_sha256"):
                state.pop(key, None)
        state.update(status="queued", current_stage=stage)
        db.execute("UPDATE job_records SET value=? WHERE kind='run'", (json.dumps(state),))
        db.execute(
            "DELETE FROM usage_attempts WHERE run_id=? "
            + ("" if stage == "parse" else "AND json_extract(reservation,'$.call.role')='tagger'"),
            (run,),
        )
        db.execute("DELETE FROM local_tag_cache_v1")
        if stage == "parse":
            # A full replay recreates the original job IDs from scratch. Keep
            # the live audit immutability guard: reset ONLY this copied fixture
            # stream, so its original publication event cannot collide later.
            for table in ("audit_events", "audit_heads"):
                db.execute(f"DELETE FROM {table} WHERE tenant_id=? AND run_id=?", (tenant, run))
        for _, sql in triggers:
            db.execute(sql)
    if stage == "parse":
        shutil.rmtree(output / "parser-prepared")
    return tenant, run


def main():
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
    from proofops_worker import tag_runner
    from proofops_worker.composition import build_composition
    from proofops_worker.live_tagging import LiveTaggingRuntime

    args = argparse.ArgumentParser()
    args.add_argument("--source", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    args.add_argument("--stage", choices=("parse", "tag", "pipeline", "extraction"), required=True)
    args.add_argument("--cache-profile", default="exact-verified-read-v2")
    args.add_argument("--workers", type=int, default=8)
    args.add_argument("--scheduler-rps", type=int, choices=range(1, 9))
    args.add_argument("--rtt-ms", type=float, default=150)
    args.add_argument("--recorded-wait", action="store_true")
    args.add_argument("--no-profile", action="store_true")
    args.add_argument("--trace-failures", action="store_true")
    args = args.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    ledger_name = next(
        (
            name
            for name in ("luna.sqlite3", "live-luna.sqlite3")
            if (source / name).is_file() and (source / (name + ".responses")).is_dir()
        ),
        None,
    )
    if ledger_name is None:
        raise ValueError("REPLAY_RETAINED_MODEL_LEDGER_REQUIRED")
    first_stage = "parse" if args.stage in ("pipeline", "extraction") else args.stage
    tenant, run = fixture(source, output, first_stage)
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
        PROOFOPS_VERIFIED_READ_CACHE=args.cache_profile,
    )
    requests = {
        p.parent.name: json.loads(p.read_text())
        for p in (source / "tagging-receipts").rglob("request.json")
    }
    requests.update(
        {
            p.parent.name: json.loads(p.read_text())
            for p in (source / "extraction-receipts").glob("*/request.json")
        }
    )
    responses = {
        (d["request_id"], d["attempt"]): d["provider_response"]
        for p in (source / (ledger_name + ".responses")).glob("*.json")
        for d in [json.loads(p.read_text())]
    }
    local = threading.local()
    scheduler = None
    if args.scheduler_rps:
        from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

        scheduler = RoleProviderConcurrency(
            args.workers,
            requests_per_second=args.scheduler_rps,
            resilience_directory=output / "scheduler-events",
        )
    events, counts = [], {}
    lock = threading.Lock()
    with sqlite3.connect((source / ledger_name).as_uri() + "?mode=ro", uri=True) as db:
        provider_receipts = {
            key: json.loads(v)
            for key, v in db.execute(
                "SELECT request_id,receipt FROM probe_calls WHERE receipt IS NOT NULL"
            )
        }

    class ReplayProbe(OpenAIProbe):
        def complete(self, system, user, *, request_id, **kwargs):
            local.request_id = request_id
            result = super().complete(system, user, request_id=request_id, **kwargs)
            expected = provider_receipts[request_id] | dict(content=result["content"])
            assert normalize_timing(result) == normalize_timing(
                expected
            ), "PA3_PROVIDER_METADATA_CHANGED"
            # Retain timing bytes used by semantic hashes. Experimental wait
            # still comes from the real replay transport interval in events.
            return expected

        def _post(self, body, **kwargs):
            if scheduler is None:
                return self._retained_post(body, **kwargs)
            role = provider_receipts[local.request_id]["response_request"]["role"]
            with scheduler.attempt(role):
                return self._retained_post(body, **kwargs)

        def _retained_post(self, body, **kwargs):
            key = local.request_id
            retained = requests[key]
            expected = self.request_body(
                retained.get("wire_system", retained.get("system_prompt")),
                retained.get("wire_user_json", retained.get("user_json")),
                request_id=key,
                max_tokens=retained.get("request", retained)["max_tokens"],
                json_mode=True,
            )
            assert body == expected, "PA3_WIRE_CHANGED"
            with lock:
                attempt = counts.get(key, 0)
                counts[key] = attempt + 1
            wait = (
                provider_receipts[key]["attempts"][attempt]["latency_ms"] / 1000
                if args.recorded_wait
                else args.rtt_ms / 1000
            )
            # Wire validation/body preparation precede the physical transport
            # boundary, matching OpenAIProbe._post_admitted.
            start = scheduler.pace_transport() if scheduler else time.monotonic()
            time.sleep(wait)
            with lock:
                events.append(
                    dict(
                        function="llm",
                        start=start,
                        seconds=time.monotonic() - start,
                        request_id=key,
                        thread=threading.get_ident(),
                        recorded_seconds=provider_receipts[key]["attempts"][attempt]["latency_ms"]
                        / 1000,
                    )
                )
            return json.loads(json.dumps(responses[key, attempt]))

    class ReplayParse(UpstageParseProbe):
        def parse_async(self, pdf_bytes, *, request_id, mode="standard"):
            with sqlite3.connect(
                (source / "upstage.sqlite3").as_uri() + "?mode=ro", uri=True
            ) as db:
                retained = [
                    json.loads(v)
                    for (v,) in db.execute(
                        "SELECT receipt FROM probe_calls WHERE receipt IS NOT NULL"
                    )
                ]
            receipt = next(r for r in retained if "duration_seconds" in r and r["mode"] == mode)
            batches = retained_parse_batches(source, receipt)
            from hashlib import sha256

            from proofops.adapters.local.upstage_parse import PARSE_MODEL_PINNED

            body = dict(
                model=PARSE_MODEL_PINNED,
                mode=mode,
                pdf_sha256=sha256(pdf_bytes).hexdigest(),
                pages=receipt["pages"],
                bytes_len=len(pdf_bytes),
                transport="async",
            )
            assert canonical_hash(body) == receipt["request_sha256"], "PA3_PARSE_WIRE_CHANGED"
            self._post_parse = lambda *a: dict(request_id=receipt["provider_request_id"])
            self._async_status = lambda *a: dict(
                status="completed",
                total_pages=receipt["pages"],
                completed_pages=receipt["pages"],
                model=receipt["provider_model"],
                batches=[
                    dict(download_url=f"https://replay.files.upstage.ai/{i}")
                    for i in range(len(batches))
                ],
            )
            self._async_download = lambda url: batches[int(url.rsplit("/", 1)[1])]
            start = time.monotonic()
            time.sleep(args.rtt_ms / 1000)
            result = super().parse_async(pdf_bytes, request_id=request_id, mode=mode)
            with lock:
                events.append(
                    dict(
                        function="upstage.parse",
                        start=start,
                        seconds=time.monotonic() - start,
                        recorded_seconds=receipt["duration_seconds"],
                    )
                )
            # Retain the provider's measured duration as immutable provenance;
            # the experiment's actual wall time is recorded separately above.
            return result | dict(duration_seconds=receipt["duration_seconds"])

    def deny(*a, **k):
        raise AssertionError("PA3_OFFLINE_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.create_connection = deny
    from proofops_agent.upstage_tagging import UpstageTaggingTransport

    original_invoke = UpstageTaggingTransport._invoke
    for path in (source / "tagging-receipts").rglob("request.json"):
        requests[path.parent.name]["_path"] = str(path.parent)

    def retained_metadata(self, request):
        response = original_invoke(self, request)
        original = json.loads(
            (Path(requests[request["request_id"]]["_path"]) / "response.json").read_text()
        )
        assert normalize_timing(asdict(response)) == normalize_timing(
            original
        ), "PA3_RESTORED_PAYLOAD_CHANGED"
        return replace(
            response, usage=replace(response.usage, latency_ms=original["usage"]["latency_ms"])
        )

    UpstageTaggingTransport._invoke = retained_metadata
    worker = build_composition(
        stage=first_stage,
        verify_paragraphs=first_stage == "parse",
        provider_ledgers=(output / "upstage.sqlite3", output / "replay-luna.sqlite3"),
        provider_factories={
            "llm": lambda key, ledger, **kw: ReplayProbe("offline-fixture", ledger, **kw),
            "parse": lambda ledger: ReplayParse("offline-fixture", ledger),
        },
    )
    with sqlite3.connect((source / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        frozen = json.loads(
            db.execute("SELECT payload FROM run_snapshots WHERE run_id=?", (run,)).fetchone()[0]
        )
    worker.clock = (
        lambda: datetime.fromisoformat(
            frozen["runtime"]["approved_at"].replace("Z", "+00:00")
        ).timestamp()
        + 600
    )
    if first_stage == "parse":
        from proofops.adapters.parsing import opendataloader, upstage_document

        original_dir = next((source / "parser-prepared").rglob("manifest.json")).parent
        batches = read_parser_json(original_dir / "candidates.json")
        ids = {b["parser_name"]: UUID(b["parser_run_id"]) for b in batches}
        original_batch = opendataloader._batch

        def batch(*a, auxiliary=False, **k):
            previous = opendataloader.uuid4
            opendataloader.uuid4 = lambda: ids["pdfplumber" if auxiliary else "opendataloader"]
            try:
                return original_batch(*a, auxiliary=auxiliary, **k)
            finally:
                opendataloader.uuid4 = previous

        opendataloader._batch = batch
        candidate_batch = upstage_document.candidate_batch

        def pinned_candidate_batch(*a, mode, **k):
            previous = upstage_document.uuid4
            upstage_document.uuid4 = lambda: ids["upstage_async_" + mode]
            try:
                return candidate_batch(*a, mode=mode, **k)
            finally:
                upstage_document.uuid4 = previous

        upstage_document.candidate_batch = pinned_candidate_batch

        def raw_parser(command, work, env, profile):
            if (original_dir / "h6-local.json").is_file():
                retained = json.loads((original_dir / "h6-local.json").read_bytes())
                selected = json.loads((work / "request.json").read_bytes())["selected"]
                record = next(
                    b
                    for b in retained["batches"]
                    if b["status"] == "parsed" and b["pages"] == selected
                )
                prefix = record["prefix"]
                for name in ("source.json", "auxiliary.json", "geometry.json"):
                    shutil.copy2(original_dir / (prefix + name), work / name)
                shutil.copy2(original_dir / (prefix + "h6-selected.pdf"), work / "h6-selected.pdf")
                shutil.copy2(original_dir / "source.md", work / "source.md")
                repaired = json.loads((original_dir / "source-repaired.json").read_bytes())

                def unprefix(value):
                    if isinstance(value, dict):
                        return {
                            k: v.removeprefix(prefix)
                            if k == "id" and isinstance(v, str)
                            else unprefix(v)
                            for k, v in value.items()
                        }
                    return [unprefix(v) for v in value] if isinstance(value, list) else value

                (work / "source-repaired.json").write_text(json.dumps(unprefix(repaired)))
                repair = json.loads((original_dir / "table-repair.json").read_bytes())
                (work / "table-repair.json").write_text(json.dumps(repair["batches"][0]))
                return
            for name in (
                "source.json",
                "source.md",
                "source-repaired.json",
                "auxiliary.json",
                "geometry.json",
                "table-repair.json",
                "launcher-stderr.txt",
                "local-selected.pdf",
                "local-selected.json",
                "local-page-map.json",
            ):
                if (original_dir / name).is_file():
                    shutil.copy2(original_dir / name, work / name)

        worker.parser._execute = raw_parser

    def instrument(owner, name):
        original = getattr(owner, name)

        @functools.wraps(original)
        def measured(*a, **k):
            start = time.monotonic()
            cpu = time.thread_time()
            try:
                return original(*a, **k)
            finally:
                with lock:
                    events.append(
                        dict(
                            function=name,
                            start=start,
                            seconds=time.monotonic() - start,
                            cpu_seconds=time.thread_time() - cpu,
                        )
                    )

        setattr(owner, name, measured)

    for owner, name in (
        (LiveTaggingRuntime, "preliminary"),
        (LiveTaggingRuntime, "relations"),
        (LiveTaggingRuntime, "display_packet"),
        (tag_runner, "retrieve_evidence"),
        (tag_runner, "tag_replicates"),
    ):
        instrument(owner, name)
    main_profile = cProfile.Profile()

    def measured_call(operation, *a, **k):
        if args.no_profile:
            return operation(*a, **k)
        return main_profile.runcall(operation, *a, **k)

    start = time.monotonic()
    stage_times = {}
    try:
        with reader_scope(ReplayOCRStore(output / "upstage.sqlite3")):
            begin = time.monotonic()
            status = measured_call(worker.run_once, tenant_id=tenant, run_id=run)
            stage_times[first_stage] = time.monotonic() - begin
            events.append(
                dict(function="stage." + first_stage, start=begin, seconds=stage_times[first_stage])
            )
            if args.stage in ("pipeline", "extraction"):
                assert status == "committed", status
                factories = dict(
                    llm=lambda key, ledger, **kw: ReplayProbe("offline-fixture", ledger, **kw),
                    parse=lambda ledger: ReplayParse("offline-fixture", ledger),
                )
                for stage in ("extract",) if args.stage == "extraction" else ("extract", "tag"):
                    if args.trace_failures and stage == "extract":

                        def trace(frame, event, value):
                            filename = frame.f_code.co_filename
                            if event == "exception" and filename.endswith(
                                ("extract_runner.py", "pa7_raster_cache.py")
                            ):
                                kind = value[0].__name__
                                print(
                                    json.dumps(
                                        dict(
                                            event="w3_failure_frame",
                                            file=Path(filename).name,
                                            line=frame.f_lineno,
                                            exception_type=kind,
                                        )
                                    ),
                                    flush=True,
                                )
                            return trace

                        import sys

                        sys.settrace(trace)
                        threading.settrace(trace)
                    worker.uploads.close()
                    worker.uploads.registry.close()
                    worker = build_composition(
                        stage=stage,
                        provider_ledgers=(
                            output / "upstage.sqlite3",
                            output / "replay-luna.sqlite3",
                        ),
                        provider_factories=factories,
                    )
                    worker.clock = (
                        lambda: datetime.fromisoformat(
                            frozen["runtime"]["approved_at"].replace("Z", "+00:00")
                        ).timestamp()
                        + 600
                    )
                    begin = time.monotonic()
                    status = measured_call(worker.run_once, tenant_id=tenant, run_id=run)
                    if stage == "extract":
                        assert status == "committed", status
                        from proofops_worker.extract_batch import run_batches

                        measured_call(
                            run_batches, worker, tenant_id=tenant, run_id=run, batches=100
                        )
                    stage_times[stage] = time.monotonic() - begin
                    events.append(
                        dict(function="stage." + stage, start=begin, seconds=stage_times[stage])
                    )
        seconds = time.monotonic() - start
        assert status == ("completed" if args.stage in ("tag", "pipeline") else "committed"), status
        final_stage = (
            "tag"
            if args.stage == "pipeline"
            else "extract"
            if args.stage == "extraction"
            else args.stage
        )
        result = checkpoint(output, final_stage)
        expected = checkpoint(source, final_stage)
        identical = normalize_timing(result) == normalize_timing(expected)
        measurement = dict(
            seconds=seconds,
            stage=args.stage,
            workers=args.workers,
            cache_profile=args.cache_profile,
            rtt_ms=args.rtt_ms,
            recorded_wait=args.recorded_wait,
            profiled=not args.no_profile,
            replay_calls=sum(counts.values()),
            live_provider_calls=0,
            paid_usd="0",
            wire_exact=True,
            original_result_identical=identical,
            original_checkpoint_identical=result == expected,
            result_sha256=canonical_hash(normalize_timing(result)),
            events=events,
            stage_seconds=stage_times,
        )
        if scheduler is not None:
            from proofops.application.analysis_profile import FINALS_S5_POLICY

            measurement.update(
                scheduler=scheduler.snapshot(),
                execution_policy_sha256=canonical_hash(FINALS_S5_POLICY),
                replay_policy="historical-pins-retained; S5-physical-queue-only",
            )
        (output / "checkpoint.json").write_text(json.dumps(result, ensure_ascii=False))
        (output / "measurement.json").write_text(json.dumps(measurement, indent=2))
        print(json.dumps({k: v for k, v in measurement.items() if k != "events"}), flush=True)
        if not identical:
            print(
                "differing_keys",
                [k for k in result if normalize_timing(result[k]) != normalize_timing(expected[k])],
            )
        assert identical, "PA3_RESULT_CHANGED"
    finally:
        if not args.no_profile:
            main_profile.dump_stats(str(output / "main.prof"))
        worker.uploads.close()
        worker.uploads.registry.close()


if __name__ == "__main__":
    main()
