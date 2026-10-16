"""Offline S1 parse benchmark: real source guards, retained provider/Java output."""

import argparse
import functools
import json
import os
import resource
import shutil
import socket
import sqlite3
import time
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from proofops.adapters.parsing.parser_artifacts import read_parser_json

from evaluation.pa3_replay import checkpoint, fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--provider-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speed", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    tenant, run = fixture(source, output, "parse")
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        LOCAL_DATABASE_PATH=str(output / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(output / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(output / "settings.json"),
        PROOFOPS_VERIFIED_READ_CACHE="exact-verified-read-v5",
    )
    from proofops.adapters.local import evidence_source_ocr_v1 as evidence
    from proofops.adapters.local import frozen_native_replay, parse_table_cache
    from proofops.adapters.local import native_glyph_geometry as glyph
    from proofops.adapters.local import upstage_ocr_page as page_ocr
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local.local_raster_reader import LocalRasterReader
    from proofops.adapters.local.upstage_parse import PARSE_MODEL_PINNED, UpstageParseProbe
    from proofops.adapters.parsing import opendataloader, upstage_document
    from proofops.application.analysis_profile import S1_POLICY
    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
    from proofops_worker.composition import build_composition

    def deny(*a, **k):
        raise AssertionError("S1_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.create_connection = deny
    events = []

    def instrument(owner, name, label=None):
        original = getattr(owner, name)

        @functools.wraps(original)
        def measured(*a, **k):
            start, cpu = time.monotonic(), time.thread_time()
            try:
                return original(*a, **k)
            finally:
                events.append(
                    dict(
                        function=label or name,
                        seconds=time.monotonic() - start,
                        cpu_seconds=time.thread_time() - cpu,
                    )
                )

        setattr(owner, name, measured)

    # Wrap dynamically composed private verifiers without cProfile/PDFium tracing.
    original_exec = frozen_native_replay._exec_private

    def private(*a, **k):
        module = original_exec(*a, **k)
        for name in (
            "attest_tables",
            "attest_native_sources",
            "attest_evidence_sources",
            "_grid",
            "_native_bands",
            "_rendered_cell",
            "_rendered_text",
        ):
            if hasattr(module, name):
                instrument(module, name, a[1] + ":" + name)
        return module

    # Already imported compositions keep their own factory reference.
    frozen_native_replay._exec_private = private
    for module in (v6._wrapper._composition, v6._wrapper, evidence, evidence.v4._composition):
        module._exec_private = private
    for owner, name in (
        (LocalRasterReader, "read"),
        (page_ocr, "render_page"),
        (glyph, "native_word_ink_geometry"),
        (v6.Reader, "attest_tables"),
        (v6.Reader, "replay_tables"),
        (v6.Reader, "attest_native_sources"),
        (evidence.Reader, "attest_evidence_sources"),
        (evidence.Reader, "replay_evidence_sources"),
    ):
        instrument(owner, name)

    receipts, responses = {}, {}
    provider_source = args.provider_source.resolve()
    with sqlite3.connect(
        (provider_source / "upstage.sqlite3").as_uri() + "?mode=ro", uri=True
    ) as db:
        for (raw,) in db.execute("SELECT receipt FROM probe_calls WHERE receipt IS NOT NULL"):
            receipt = json.loads(raw)
            if "duration_seconds" in receipt:
                receipts[receipt["mode"]] = receipt
    for path in (provider_source / "parse-responses").glob("*-async.json"):
        value = json.loads(path.read_text())
        for mode, receipt in receipts.items():
            if canonical_hash(value) == receipt["response_sha256"]:
                responses[mode] = value

    class RetainedParse(UpstageParseProbe):
        def parse_async(self, pdf_bytes, *, request_id, mode="standard"):
            begin = time.monotonic()
            receipt = receipts[mode]
            body = dict(
                model=PARSE_MODEL_PINNED,
                mode=mode,
                pdf_sha256=sha256(pdf_bytes).hexdigest(),
                pages=receipt["pages"],
                bytes_len=len(pdf_bytes),
                transport="async",
            )
            assert canonical_hash(body) == receipt["request_sha256"]
            assert canonical_hash(responses[mode]) == receipt["response_sha256"]
            events.append(
                dict(
                    function="retained_parse:" + mode,
                    seconds=time.monotonic() - begin,
                    cpu_seconds=0,
                )
            )
            return receipt | dict(raw_batches=responses[mode])

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
    original_candidate = upstage_document.candidate_batch

    def candidate(*a, mode, **k):
        previous = upstage_document.uuid4
        upstage_document.uuid4 = lambda: ids["upstage_async_" + mode]
        try:
            return original_candidate(*a, mode=mode, **k)
        finally:
            upstage_document.uuid4 = previous

    upstage_document.candidate_batch = candidate

    worker = build_composition(
        stage="parse",
        verify_paragraphs=True,
        provider_ledgers=(output / "upstage.sqlite3", output / "offline.sqlite3"),
        provider_factories={"parse": lambda ledger: RetainedParse("offline", ledger)},
    )

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

    worker.parser._execute = raw_parser
    snapshot = worker.store.snapshot(tenant, run)
    worker.clock = (
        lambda: datetime.fromisoformat(
            snapshot["runtime"]["approved_at"].replace("Z", "+00:00")
        ).timestamp()
        + 600
    )
    start = time.monotonic()
    try:
        # Evaluation-only replay retains every input identity for byte comparison.
        # New production runs enter this scope only through their new persisted pin.
        with (
            reader_scope(ReplayOCRStore(output / "upstage.sqlite3")),
            parse_table_cache.scope(tenant, run) if args.speed else nullcontext(),
        ):
            status = worker.run_once(tenant_id=tenant, run_id=run)
        result = checkpoint(output, "parse")
        expected = checkpoint(source, "parse")
        (output / "checkpoint.json").write_text(json.dumps(result, ensure_ascii=False))
        totals = defaultdict(lambda: dict(calls=0, seconds=0.0, cpu_seconds=0.0))
        for event in events:
            entry = totals[event["function"]]
            entry["calls"] += 1
            entry["seconds"] += event["seconds"]
            entry["cpu_seconds"] += event["cpu_seconds"]
        measured = dict(
            status=status,
            seconds=time.monotonic() - start,
            checkpoint_equal=result == expected,
            checkpoint_sha256=canonical_hash(result),
            expected_sha256=canonical_hash(expected),
            functions=dict(totals),
            max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            provider_seconds={m: r["duration_seconds"] for m, r in receipts.items()},
            source_sha256=sha256((source / "parse-checkpoint.json").read_bytes()).hexdigest(),
            network="disabled",
            paid_calls=0,
            paid_usd="0",
            speed=args.speed,
            execution_policy_sha256=canonical_hash(S1_POLICY)
            if args.speed
            else snapshot["analysis_profile_policy_sha256"],
        )
        (output / "measurement.json").write_text(json.dumps(measured, indent=2))
        (output / "events.json").write_text(json.dumps(events))
        print(json.dumps(measured), flush=True)
        assert status == "committed" and result == expected
    finally:
        worker.uploads.close()
        worker.uploads.registry.close()


if __name__ == "__main__":
    main()
