"""Small authorized 8-worker/4RPS transport sample, never published as K=3 tags."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
from proofops.application.analysis_profile import FINALS_K10_V2_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_analysis import read_key

from evaluation.i9_live import I9Budget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    import sqlite3

    with sqlite3.connect(args.source / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    records = []
    seen = set()
    for path in sorted((args.source / "tagging-receipts").glob("*/elements/*/request.json")):
        record = json.loads(path.read_text())
        previous = json.loads((path.parent / "response.json").read_text())
        if previous["usage"]["status"] != "succeeded":
            continue  # Never use this diagnostic to retry an unknown-delivery slot.
        cid = record["request"]["claim_id"]
        if cid not in seen:
            seen.add(cid)
            records.append((path, record))
        if len(records) == 12:
            break
    assert len(records) == 12
    probe = OpenAIProbe(
        read_key(str(args.root / ".env.openai.local"), "OPENAI_API_KEY"),
        args.output / "probe.sqlite3",
    )
    policy = FINALS_K10_V2_POLICY
    probe.configure_response_policy(
        dict(
            tenant_id=snapshot["tenant_id"],
            document={"sha256": snapshot["document"]["sha256"]},
            analysis_profile_policy=policy,
            analysis_profile_policy_sha256=canonical_hash(policy),
        ),
        role="elements",
    )
    gate = RoleProviderConcurrency(
        8,
        requests_per_second=4,
        resilience_directory=args.output / "provider-events",
        scheduler_policy=policy["provider_scheduler"],
    )
    gate.bind(probe)
    fence = I9Budget(
        args.root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json",
        {"openai": probe.ledger.resolve()},
        args.output.parent / "paid-calls.jsonl",
    )
    fence.task, fence.limit_usd = "K10-v11fix", Decimal("0.5")
    call = fence.guarded(OpenAIProbe.complete, "openai", lambda *a: Decimal(".02"))

    def invoke(entry):
        path, record = entry
        request = record["request"]
        result = dict(
            input_path=str(path),
            input_sha256=canonical_hash(record),
            claim_id=request["claim_id"],
            replica=request["replicate_id"],
        )
        try:
            with probe.response_context(role="elements", replica=request["replicate_id"]):
                response = call(
                    probe,
                    record["wire_system"],
                    record["wire_user_json"],
                    request_id=str(uuid4()),
                    max_tokens=request["max_tokens"],
                    json_mode=True,
                )
            return result | dict(
                status="received",
                provider_request_id=response["provider_request_id"],
                response_sha256=response["response_sha256"],
            )
        except Exception as error:
            return result | dict(status="failed", exception_type=type(error).__name__)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(invoke, records))
    summary = dict(
        workers=8,
        rps=4,
        calls=len(results),
        failures=sum(r["status"] == "failed" for r in results),
        results=results,
        admission=gate.snapshot(),
        spend=probe.summary(),
        inference_mode="fresh-transport-only; no-consensus-or-publication",
        policy_sha256=canonical_hash(policy),
    )
    (args.output / "measurement.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}))


if __name__ == "__main__":
    main()
