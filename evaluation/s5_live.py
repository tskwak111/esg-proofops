"""Authorized LG13 fresh-model trials sharing one USD0.4 task reservation fence."""

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.worker_resources import resource_snapshot
from proofops.application.analysis_profile import FINALS_S5_POLICY
from proofops.domain.provenance import canonical_hash

from evaluation.i1_live import main as live_main
from evaluation.i5_live import I5Budget
from evaluation.k8_authorization import fresh_grants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(8, 12), required=True)
    parser.add_argument("--rps", type=int, choices=(4, 6), required=True)
    args = parser.parse_args()
    root, out = args.root, args.output
    original = OpenAIProbe.complete
    rate_headers = {}

    def guarded(probe, *a, **kw):
        fence = I5Budget(
            root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
            {"openai": probe.ledger.resolve()},
            out / "paid-calls.jsonl",
        )
        fence.task, fence.limit_usd = "S5-pacing", Decimal(".4")
        result = fence.guarded(original, "openai", lambda *a: Decimal(".02"))(probe, *a, **kw)
        rate_headers.update(getattr(probe, "rate_limit_headers", {}))
        return result

    OpenAIProbe.complete = guarded
    source = root / "outputs/agent-results/R108-redesign/lab/perf/S2/source-lg"
    manifest = json.loads((source / "pilot.json").read_text())
    settings = json.loads((source / "settings.json").read_text())
    pages = [
        manifest["selected_pages"][p - 1] for p in settings["extraction_limits"]["claim_pages"]
    ]
    label = f"live-{args.workers}w-{args.rps}rps"
    sys.argv = [
        "s5-live",
        "--root",
        str(root),
        "--output",
        str(out / label),
        "--harness",
        str(root / "outputs/agent-results/R108-redesign/lab/fix/F1/f1_harness.py"),
        "--key-file",
        str(root / ".env.openai.local"),
        "--spend-ledger",
        str(out / "spend.sqlite3"),
    ]
    started = time.monotonic()
    result = live_main(
        claim_pages={"lgchem": pages},
        workers=args.workers,
        requests_per_second=args.rps,
        budget=".4",
        event_id="S5-USD0.4",
        integration_policy=FINALS_S5_POLICY,
        source_states={"lgchem": source},
        extraction_batch_calls=100,
        local_grant_factory=lambda policy: fresh_grants(
            policy, approved_by="authorized-local-operator:speed-S5.md"
        ),
    )
    summary = dict(
        seconds=time.monotonic() - started,
        workers=args.workers,
        rps=args.rps,
        policy_sha256=canonical_hash(FINALS_S5_POLICY),
        admission=result["admission"],
        provider_headers=rate_headers,
        status=result["results"]["lgchem"]["status"],
        spend=result["spend"],
        live_provider_calls=result["dispatches"],
        resource_runtime=resource_snapshot(),
    )
    (out / (label + "-summary.json")).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
