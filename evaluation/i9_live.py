"""I9 USD1.50 fence, reservation telemetry and private warm publication."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryFile

from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.worker_resources import resource_snapshot
from proofops.application.analysis_profile import FINALS_I9_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_publication import MAX_BYTES, make_handoff, reuse_handoff

from evaluation.f1_live import source_claim_pages
from evaluation.i1_live import main as live_main
from evaluation.i5_live import I5Budget
from evaluation.k8_authorization import fresh_grants
from scripts.finals_demo import FinalsBudget

TASK = "I9-integration"
BUDGET = "1.5"
MODULE = "evaluation.i9_live"


class I9Budget(I5Budget):
    def reserve(self, bound):
        started = time.monotonic()
        self.reservation_wait_seconds = 0.0
        self.reservation_polls = 0
        deadline = started + 120
        try:
            while True:
                try:
                    return FinalsBudget.reserve(self, bound)
                except ValueError as error:
                    if str(error) != "R108_FINALS_BUDGET_EXHAUSTED":
                        raise
                    with self.transaction() as (_, entry):
                        active = Decimal(entry["reserved_usd"]) > 0
                        affordable = Decimal(entry["delta_usd"]) + bound <= self.limit_usd
                    if not active or not affordable or time.monotonic() >= deadline:
                        raise
                    begin = time.monotonic()
                    time.sleep(0.05)
                    self.reservation_wait_seconds += time.monotonic() - begin
                    self.reservation_polls += 1
        finally:
            self.reservation_total_seconds = time.monotonic() - started


def child(args):
    root, out = args.root, args.output
    lab = root / "outputs/agent-results/R108-redesign/lab"
    source = lab / "perf/S4/live-inputs" / args.company
    original = OpenAIProbe.complete

    def guarded(probe, *a, **kw):
        fence = I9Budget(
            lab / "sprint3/E2E/r108-spend.json",
            {"openai": probe.ledger.resolve()},
            out.parent / "paid-calls.jsonl",
        )
        fence.task, fence.limit_usd = TASK, Decimal(BUDGET)
        try:
            return fence.guarded(original, "openai", lambda *a: Decimal(".02"))(probe, *a, **kw)
        finally:
            record = dict(
                request_id=kw["request_id"],
                reservation_total_seconds=getattr(fence, "reservation_total_seconds", 0),
                reservation_wait_seconds=getattr(fence, "reservation_wait_seconds", 0),
                reservation_polls=getattr(fence, "reservation_polls", 0),
            )
            with (out / "reservation-events.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")

    OpenAIProbe.complete = guarded
    # The existing canary parser owns these paths; no secret values enter argv/logs.
    sys.argv = [
        "i9-live",
        "--root",
        str(root),
        "--output",
        str(out / "pipeline"),
        "--harness",
        str(lab / "fix/F1/f1_harness.py"),
        "--key-file",
        str(root / ".env.openai.local"),
        "--spend-ledger",
        str(out.parent / "spend.sqlite3"),
    ]
    started = time.monotonic()
    result = live_main(
        claim_pages={args.company: source_claim_pages(source)},
        workers=args.workers,
        requests_per_second=args.rps,
        budget=BUDGET,
        event_id=TASK,
        integration_policy=FINALS_I9_POLICY,
        source_states={args.company: source},
        extraction_batch_calls=100,
        local_grant_factory=lambda snapshot: fresh_grants(
            snapshot, approved_by="authorized-local-operator:int-I9.md"
        ),
    )
    state = out / "pipeline" / args.company
    measurement = json.loads((state / "measurement.json").read_text())
    gate = result["admission"]
    failures = gate["failed_calls"] + gate["circuit_deferred"]
    complete = result["results"][args.company]["status"] == "completed"
    (state / "outcome.json").write_text(
        json.dumps(
            dict(
                status="partial_blocked" if failures or not complete else "completed",
                reason="PROVIDER_PROCESSING_FAILED"
                if failures
                else result["results"][args.company].get("reason"),
                provider_concurrency=gate,
                provider_failures=dict(total=failures),
                stage_seconds=measurement["stage_seconds"],
            )
        )
    )
    manifest = json.loads((state / "pilot.json").read_text())
    job = dict(tenant_id=manifest["tenant_id"], run_id=manifest["run_id"], fence=1)
    begin = time.monotonic()
    packet = make_handoff(state, job, manifest["selected_pages"])
    if packet is None:
        raise ValueError("I9_PUBLICATION_HANDOFF_UNAVAILABLE")
    with os.fdopen(os.dup(args.publication_fd), "wb") as fd:
        fd.write(packet)
    (out / "child-summary.json").write_text(
        json.dumps(
            dict(
                company=args.company,
                workers=args.workers,
                rps=args.rps,
                pipeline_seconds=measurement["seconds"],
                stage_seconds=measurement["stage_seconds"],
                child_publication_seconds=time.monotonic() - begin,
                child_seconds=time.monotonic() - started,
                admission=gate,
                spend=result["spend"],
                policy_sha256=canonical_hash(FINALS_I9_POLICY),
                resource_runtime=resource_snapshot(),
                outcome=json.loads((state / "outcome.json").read_text()),
            ),
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--company", choices=("lgchem", "kakao"), required=True)
    parser.add_argument("--workers", type=int, choices=(8, 12, 16), required=True)
    parser.add_argument("--rps", type=int, choices=(4, 6, 8), required=True)
    parser.add_argument("--publication-fd", type=int)
    args = parser.parse_args()
    if args.publication_fd is not None:
        return child(args)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with TemporaryFile() as fd:
        subprocess.run(
            [
                sys.executable,
                "-m",
                MODULE,
                *sys.argv[1:],
                "--publication-fd",
                str(fd.fileno()),
            ],
            pass_fds=(fd.fileno(),),
            check=True,
        )
        fd.seek(0)
        packet = fd.read(MAX_BYTES + 1)
    state = args.output / "pipeline" / args.company
    manifest = json.loads((state / "pilot.json").read_text())
    job = dict(tenant_id=manifest["tenant_id"], run_id=manifest["run_id"], fence=1)
    begin = time.monotonic()
    content = reuse_handoff(packet, state, job, manifest["selected_pages"])
    if content is None:
        raise ValueError("I9_PARENT_BYTE_PIN_REJECTED")
    published = args.output / "publication-final"
    shutil.copytree(state, published)
    path = published / "result-1.json"
    path.write_bytes(content)
    path.chmod(0o400)
    parent_seconds = time.monotonic() - begin
    (state / "result.json").write_bytes(content)
    summary = json.loads((args.output / "child-summary.json").read_text()) | dict(
        parent_publication_seconds=parent_seconds,
        wall_seconds=time.monotonic() - started,
        packet_bytes=len(packet),
        result_bytes=len(content),
        private_fd=True,
        parent_cold_replay_calls=0,
    )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
