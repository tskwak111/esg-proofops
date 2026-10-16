"""S2 LG full fresh-model comparison on disposable, retained-parser fixtures.

Both arms share one atomic USD .60 ledger. Never writes imported revisions to
hosted users. Source policy/wire/domain stay identical; only S2 execution and
call allowance change. Upstage parsing and page OCR responses are retained.
"""

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from proofops.adapters.local import spend_guard
from proofops.adapters.local.provider_concurrency import ProviderConcurrency
from proofops.adapters.local.upstage_parse import PARSE_MODEL_PINNED
from proofops.adapters.parsing import upstage_document
from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.analysis_profile import FINALS_I3_POLICY, S2_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_worker import composition


def pin_fixture(output, tenant, run, *, after):
    """Re-pin ONLY the disposable copy; original SQL guards are restored."""
    policy = S2_POLICY if after else FINALS_I3_POLICY
    with sqlite3.connect(output / "state.sqlite3") as db:
        triggers = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        for name, _ in triggers:
            assert name.replace("_", "").isalnum()
            db.execute(f"DROP TRIGGER {name}")
        frozen = json.loads(
            db.execute("SELECT payload FROM run_snapshots WHERE run_id=?", (run,)).fetchone()[0]
        )
        old_hash = frozen["input_hash"]
        frozen["analysis_profile_policy"] = policy
        frozen["analysis_profile_policy_sha256"] = canonical_hash(policy)
        if after:
            limits = frozen["budget_limits"]
            role = next(r for r in limits["roles"] if r["role"] == "tagger")
            delta = policy["tagging_budget"]["max_calls"] - role["max_calls"]
            limits["input_tokens"] += delta * role["max_input_tokens"]
            limits["output_tokens"] += delta * role["max_output_tokens"]
            role["max_calls"] += delta
            db.execute(
                "UPDATE usage_runs SET limits_json=? WHERE run_id=?", (json.dumps(limits), run)
            )
        frozen["input_hash"] = canonical_hash(
            {k: v for k, v in frozen.items() if k != "input_hash"}
        )

        def update(value):
            if isinstance(value, dict):
                return {
                    k: frozen["input_hash"] if k == "input_hash" and v == old_hash else update(v)
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
        for _, sql in triggers:
            db.execute(sql)
    path = output / "settings.json"
    settings = json.loads(path.read_text())
    settings.update(
        analysis_policy_sha256=canonical_hash(policy), budget_limits=frozen["budget_limits"]
    )
    path.write_text(json.dumps(settings))
    return frozen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spend-ledger", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--after", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("s2_hx1_harness", args.harness)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    harness.pin_scratch_policy = lambda output, tenant, run: pin_fixture(
        output, tenant, run, after=args.after
    )
    workers = 16 if args.after else 8
    gate = ProviderConcurrency(workers)
    original_build = composition.build_composition
    # The retained 30-page case has both standard and enhanced responses.
    # Validate every mode's exact PDF bytes and preserve its original parser ID.
    with sqlite3.connect(
        (args.source / "upstage.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        parse_receipts = {
            r["mode"]: r
            for (raw,) in db.execute("SELECT receipt FROM probe_calls WHERE receipt IS NOT NULL")
            for r in [json.loads(raw)]
            if "duration_seconds" in r
        }
    raw_batches = {
        mode: next(
            value
            for path in (args.source / "parse-responses").glob("*-async.json")
            for value in [json.loads(path.read_text())]
            if canonical_hash(value) == receipt["response_sha256"]
        )
        for mode, receipt in parse_receipts.items()
    }
    candidates = read_parser_json(
        next(iter_parser_artifacts(args.source / "parser-prepared", "candidates.json"))
    )
    ids = {c["parser_name"]: UUID(c["parser_run_id"]) for c in candidates}
    original_candidates = upstage_document.candidate_batch

    def candidate_batch(*a, mode, **kw):
        previous = upstage_document.uuid4
        upstage_document.uuid4 = lambda: ids["upstage_async_" + mode]
        try:
            return original_candidates(*a, mode=mode, **kw)
        finally:
            upstage_document.uuid4 = previous

    upstage_document.candidate_batch = candidate_batch

    def build(**kwargs):
        policy = S2_POLICY if args.after else FINALS_I3_POLICY
        os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = policy["verified_read_cache"]["profile"]
        factories = kwargs["provider_factories"]
        llm = factories["llm"]
        parse = factories["parse"]

        def retained_parse(ledger):
            probe = parse(ledger)

            def parse_async(pdf_bytes, *, request_id, mode="standard"):
                receipt = parse_receipts[mode]
                expected = canonical_hash(
                    dict(
                        model=PARSE_MODEL_PINNED,
                        mode=mode,
                        pdf_sha256=sha256(pdf_bytes).hexdigest(),
                        pages=receipt["pages"],
                        bytes_len=len(pdf_bytes),
                        transport="async",
                    )
                )
                if expected != receipt["request_sha256"]:
                    raise ValueError("S2_RETAINED_PARSE_INPUT_CHANGED")
                return receipt | dict(raw_batches=raw_batches[mode])

            probe.parse_async = parse_async
            return probe

        kwargs["provider_factories"] = factories | dict(
            llm=lambda *a, **kw: gate.bind(llm(*a, **kw)), parse=retained_parse
        )
        return original_build(**kwargs)

    composition.build_composition = build
    OriginalGuard = spend_guard.SpendGuard

    class SharedGuard(OriginalGuard):
        def __init__(self, path, **kwargs):
            super().__init__(
                path, **(kwargs | dict(event_id="S2-USD0.6", daily_limit="0.6", event_limit="0.6"))
            )

        def configure_run(self, run_id, **kwargs):
            return super().configure_run(run_id, **(kwargs | dict(run_limit="0.6")))

    spend_guard.SpendGuard = SharedGuard
    sys.argv = [
        "s2-hx1",
        "--source",
        str(args.source),
        "--output",
        str(args.output),
        "--spend-ledger",
        str(args.spend_ledger),
        "--key-file",
        str(args.key_file),
        "--workers",
        str(workers),
    ]
    try:
        harness.main()
        outcome = dict(status="completed", reason=None)
        (args.output / "outcome.json").write_text(json.dumps(outcome))
        started = time.monotonic()
        subprocess.run(
            [sys.executable, "-m", "evaluation.s2_publish", str(args.output)], check=True
        )
        path = args.output / "measurement.json"
        measurement = json.loads(path.read_text())
        measurement["publication_seconds"] = time.monotonic() - started
        measurement["pipeline_and_publication_seconds"] = (
            measurement["seconds"] + measurement["publication_seconds"]
        )
        path.write_text(json.dumps(measurement, indent=2))
    finally:
        path = args.output / "measurement.json"
        if path.is_file():
            measurement = json.loads(path.read_text())
            source_manifest = json.loads((args.source / "pilot.json").read_text())
            measurement["parser"] = (
                f"retained-source-attested-{len(source_manifest['selected_pages'])}-pages"
            )
            measurement["provider_concurrency"] = gate.snapshot()
            measurement["resource_contract"] = dict(cpus=2, memory_bytes=4 * 1024**3)
            path.write_text(json.dumps(measurement, indent=2))


if __name__ == "__main__":
    main()
