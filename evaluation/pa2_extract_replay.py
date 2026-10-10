"""Offline Linux extract benchmark; retained requests/responses are exact fixtures."""

import argparse
import cProfile
import json
import os
import shutil
import socket
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid5


def pre_extract_fixture(source, target, run):
    assert not target.exists() and source.resolve() != target.resolve()
    target.mkdir(parents=True)
    with sqlite3.connect(source.joinpath("state.sqlite3").as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(target / "state.sqlite3") as dst:
            src.backup(dst)
    for name in ("objects", "parser-prepared"):
        shutil.copytree(source / name, target / name)
    for name in ("parser.json", "settings.json", "upstage.sqlite3"):
        shutil.copy2(source / name, target / name)
    with sqlite3.connect(target / "state.sqlite3") as db:
        triggers = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        for name, _ in triggers:
            assert name.replace("_", "").isalnum()
            db.execute(f"DROP TRIGGER {name}")
        row = db.execute(
            "SELECT tenant_id,value FROM job_records WHERE run_id=? AND kind='run'", (run,)
        ).fetchone()
        tenant, state = row[0], json.loads(row[1])
        first = str(uuid5(UUID(state["parse_job"]["job_id"]), "extract"))
        kept = {state["parse_job"]["job_id"], first}
        for kind, key, raw in db.execute(
            "SELECT kind,record_id,value FROM job_records WHERE run_id=?", (run,)
        ).fetchall():
            value = json.loads(raw)
            preserve = (
                kind == "run"
                or kind.startswith("parser_")
                or (
                    kind == "artifact"
                    and key.startswith("job/" + state["parse_job"]["job_id"] + "/")
                )
                or (
                    kind in {"job", "outbox"}
                    and (key in kept if kind == "job" else value["message"]["job_id"] in kept)
                )
            )
            if not preserve:
                db.execute(
                    "DELETE FROM job_records WHERE run_id=? AND kind=? AND record_id=?",
                    (run, kind, key),
                )
                continue
            if kind == "job" and key == first:
                value.update(status="pending", lease_owner=None, lease_until=None, heartbeat_at=0)
                db.execute(
                    "UPDATE job_records SET value=? WHERE run_id=? AND kind=? AND record_id=?",
                    (json.dumps(value), run, kind, key),
                )
            if kind == "outbox" and value["message"]["job_id"] == first:
                value.update(status="pending", attempts=0)
                db.execute(
                    "UPDATE job_records SET value=? WHERE run_id=? AND kind=? AND record_id=?",
                    (json.dumps(value), run, kind, key),
                )
        for key in (
            "extract_job",
            "tag_job",
            "claim_snapshot_sha256",
            "tag_snapshot_sha256",
            "tag_stage_status",
        ):
            state.pop(key, None)
        state.update(status="queued", current_stage="extract")
        db.execute(
            "UPDATE job_records SET value=? WHERE run_id=? AND kind='run'", (json.dumps(state), run)
        )
        db.execute("DELETE FROM usage_attempts WHERE run_id=?", (run,))
        db.execute("DELETE FROM local_tag_cache_v1")
        for _, sql in triggers:
            db.execute(sql)
    return tenant


def main():
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops.application.ports.jobs import JobMessage
    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
    from proofops_worker.composition import build_composition
    from proofops_worker.extract_batch import run_batches

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rtt-ms", type=float, default=150)
    parser.add_argument("--verify-original", action="store_true")
    parser.add_argument(
        "--cache-profile",
        choices=("off", "exact-verified-read-v1", "exact-verified-read-v2"),
        default="exact-verified-read-v2",
    )
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    manifest = json.loads((source / "pilot.json").read_text())
    run = manifest["run_id"]
    tenant = pre_extract_fixture(source, output, run)
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        LOCAL_EXTRACTION_MODE="upstage_probe",
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
        for p in (source / "extraction-receipts").glob("*/request.json")
    }
    responses = {
        (d["request_id"], d["attempt"]): d["provider_response"]
        for p in (source / "luna.sqlite3.responses").glob("*.json")
        for d in [json.loads(p.read_text())]
    }
    events, counts = [], {}
    lock = threading.Lock()

    class ReplayProbe(OpenAIProbe):
        def _post(self, body, **kwargs):
            key = json.loads(body["messages"][1]["content"])["request_id"]
            request = requests[key]
            expected = self.request_body(
                request["system_prompt"],
                request["user_json"],
                request_id=key,
                max_tokens=request["max_tokens"],
                json_mode=request["json_mode"],
            )
            with lock:
                attempt = counts.get(key, 0)
                counts[key] = attempt + 1
            if attempt == 0:
                assert body == expected, "REPLAY_WIRE_CHANGED"
            started = time.monotonic()
            time.sleep(args.rtt_ms / 1000)
            with lock:
                events.append(
                    dict(request_id=key, start=started, seconds=time.monotonic() - started)
                )
            return json.loads(json.dumps(responses[(key, attempt)]))

    def deny(*a, **k):
        raise AssertionError("PA2_OFFLINE_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.create_connection = deny
    worker = build_composition(
        stage="extract",
        provider_ledgers=(output / "upstage.sqlite3", output / "replay-luna.sqlite3"),
        provider_factories={
            "llm": lambda key, ledger, **kw: ReplayProbe("offline-fixture", ledger, **kw),
            "parse": lambda ledger: UpstageParseProbe("offline-fixture", ledger),
        },
    )
    # Fixture clock stays within the original frozen authorization window.
    with sqlite3.connect(source / "state.sqlite3") as db:
        frozen = json.loads(
            db.execute("SELECT payload FROM run_snapshots WHERE run_id=?", (run,)).fetchone()[0]
        )
    checked = frozen["runtime"]["approved_at"]
    from datetime import datetime

    worker.clock = lambda: datetime.fromisoformat(checked.replace("Z", "+00:00")).timestamp() + 600
    profiler = cProfile.Profile()
    started = time.monotonic()
    profiler.enable()
    try:
        with reader_scope(ReplayOCRStore(output / "upstage.sqlite3")):
            status = worker.run_once(tenant_id=tenant, run_id=run)
            assert status == "committed", status
            run_batches(worker, tenant_id=tenant, run_id=run, batches=100)
            current = worker.store.jobs.get_run(tenant, run)
            checkpoint = json.loads(
                worker.store.jobs.read_checkpoint(JobMessage(**current["extract_job"]))
            )
            seconds = time.monotonic() - started
            profiler.disable()
            identity = {}
            if args.verify_original:
                from proofops.adapters.local.claim_source_policies import claim_source_reader
                from proofops.adapters.local.claim_store import (
                    _RecordedExtractor,
                    claim_scope,
                    extraction_profile,
                )
                from proofops.adapters.local.native_replay_cache import replay_claims_cached
                from proofops.application.claims import discover_atomic_claims

                envelope, _, graph = worker.claims.load_evidence(tenant, run, for_extraction=True)
                frozen = worker.store.snapshot(tenant, run)
                raw = discover_atomic_claims(
                    graph,
                    claim_scope(frozen, graph),
                    extractor=_RecordedExtractor(
                        extraction_profile(frozen), envelope["discovery"]["receipts"]
                    ),
                )
                source_bytes = worker.uploads.read_original(tenant, graph.document_version_id)
                reader = claim_source_reader(frozen["claim_source_policy"])
                params = dict(
                    receipt=envelope["claim_source_attestation"],
                    graph=graph,
                    source=source_bytes,
                    discovery=raw,
                    tenant_id=tenant,
                )
                cached = replay_claims_cached(
                    reader=reader, policy=frozen["claim_source_policy"], **params
                )
                original = reader.replay_claim_spans(
                    params["receipt"], graph, source_bytes, raw, tenant_id=tenant
                )
                assert cached == original, "PA2_VERIFIED_RESULT_CHANGED"
                identity = dict(
                    original_reader_identical=True,
                    verified_discovery_sha256=canonical_hash(asdict(cached[0])),
                    verified_graph_sha256=canonical_hash(asdict(cached[1])),
                    claims=len(cached[0].claims),
                    verified=sum(c.source_quality == "verified" for c in cached[0].claims),
                )
        with sqlite3.connect(output / "state.sqlite3") as db:
            checkpoints = [
                json.loads(v[0])
                for v in db.execute(
                    "SELECT value FROM job_records WHERE run_id=? AND kind='job' "
                    "AND json_extract(value,'$.message.stage')='extract' "
                    "AND json_extract(value,'$.status')='succeeded'",
                    (run,),
                )
            ]
        result = dict(
            seconds=seconds,
            workers=args.workers,
            rtt_ms=args.rtt_ms,
            cache_profile=args.cache_profile,
            calls=sum(counts.values()),
            provider_calls=0,
            paid_usd="0",
            batches=len(checkpoints),
            discovery_sha256=canonical_hash(checkpoint["discovery"]),
            coverage=checkpoint["coverage"],
            attestation_sha256=canonical_hash(checkpoint["claim_source_attestation"]),
            wire_exact=True,
            events=events,
            **identity,
        )
        (output / "checkpoint.json").write_text(json.dumps(checkpoint, ensure_ascii=False))
        (output / "discovery.json").write_text(
            json.dumps(checkpoint["discovery"], ensure_ascii=False)
        )
        (output / "measurement.json").write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "events"}), flush=True)
    finally:
        profiler.disable()
        profiler.dump_stats(str(output / "extract.prof"))
        worker.uploads.close()
        worker.uploads.registry.close()


if __name__ == "__main__":
    main()
