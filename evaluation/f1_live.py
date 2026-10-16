"""Authorized F1 fresh-model Linux runs on byte-checked retained parsing."""

import json
import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_F1_POLICY
from proofops_api import hosted_ocr
from proofops_api.hosted_analysis import read_key

from evaluation.i1_live import main
from evaluation.i5_live import I5Budget


class F1OCRBudget:
    """Both existing money fences cover missing OCR in disposable local fixtures."""

    def __init__(self, shared, grant, run, events, *, task="F1-resilience", limit=".8"):
        self.shared, self.grant, self.run, self.events = shared, grant, run, events
        self.task, self.limit = task, Decimal(limit)

    def run_options(self, job):
        return {}

    def dispatch(self, job, provider, call_id, input_sha, bound, transport, **kwargs):
        fence = I5Budget(self.shared, {}, self.events)
        fence.task, fence.limit_usd = self.task, self.limit
        fence.reserve(bound)
        reserved = sent = False
        charged = Decimal(0)
        error = None
        try:
            self.grant.reserve(self.run, provider, call_id, bound)
            reserved = True
            request = dict(request_id=call_id, provider=provider, input_sha256=input_sha)
            sent = True
            response = transport(request)
            if any(response.get(k) != v for k, v in request.items()):
                raise ValueError("F1_OCR_RECEIPT_MISMATCH")
            charged = Decimal(response["actual_usd"])
            if not 0 <= charged <= bound:
                raise ValueError("F1_OCR_COST_INVALID")
            self.grant.settle(call_id, charged)
            return response
        except Exception as exc:
            error = type(exc).__name__
            charged = bound if sent else Decimal(0)
            if reserved:
                self.grant.settle(call_id, None if sent else "0")
            raise
        finally:
            with fence.transaction() as (data, entry):
                entry["reserved_usd"] = str(Decimal(entry["reserved_usd"]) - bound)
                entry["delta_usd"] = str(Decimal(entry["delta_usd"]) + charged)
                data["cumulative_usd"] = str(Decimal(data["cumulative_usd"]) + charged)
            with self.events.open("a") as stream:
                stream.write(
                    json.dumps(
                        dict(
                            provider=provider,
                            call_id=call_id,
                            committed_usd=str(charged),
                            unsettled=bool(sent and error),
                            error=error,
                        )
                    )
                    + "\n"
                )


def source_claim_pages(source_state):
    from proofops.application.claim_scope import validate_extraction_limits

    manifest = json.loads((source_state / "pilot.json").read_text())
    settings = json.loads((source_state / "settings.json").read_text())
    limits = settings["extraction_limits"]
    validate_extraction_limits(limits, list(range(1, len(manifest["selected_pages"]) + 1)))
    return [manifest["selected_pages"][page - 1] for page in limits["claim_pages"]]


def run(
    *,
    integration_policy=FINALS_F1_POLICY,
    task="F1-resilience",
    limit=".8",
    local_grant_factory=None,
):
    root = Path(sys.argv[sys.argv.index("--root") + 1])
    output = Path(sys.argv[sys.argv.index("--output") + 1])
    case = sys.argv.pop(1)
    if case not in {"kakao", "lgchem"}:
        raise ValueError("F1_CASE_UNKNOWN")
    source_state = (
        root
        / "outputs/agent-results/R108-redesign/lab/perf/S2"
        / ("source-kakao" if case == "kakao" else "source-lg")
    )
    pages = source_claim_pages(source_state)
    original = OpenAIProbe.complete
    shared = root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"
    from proofops.adapters.local.spend_guard import SpendGuard

    grant = SpendGuard(
        Path(sys.argv[sys.argv.index("--spend-ledger") + 1]),
        event_id="F1-USD0.8",
        daily_limit=".8",
        event_limit=".8",
    )
    ocr_run = "F1-ocr-" + str(uuid4())
    grant.configure_run(ocr_run, day=time.strftime("%Y-%m-%d", time.gmtime()), run_limit=".8")
    budget = F1OCRBudget(
        shared, grant, ocr_run, output.parent / "ocr-calls.jsonl", task=task, limit=limit
    )
    os.environ["UPSTAGE_API_KEY"] = read_key(str(root / ".env.upstage.local"), "UPSTAGE_API_KEY")

    class MissingOCR(hosted_ocr.HostedOCRStore):
        def __init__(self, ledger):
            manifest = json.loads((ledger.parent / "pilot.json").read_text())
            job = dict(
                tenant_id=manifest["tenant_id"], pages=json.dumps(manifest["selected_pages"])
            )
            super().__init__(
                ledger,
                ledger.parent / "f1-ocr-bookkeeping.json",
                store=budget,
                job=job,
                local_run_id=manifest["run_id"],
            )

    # The frozen reader still validates the exact tenant/PDF/PNG/policy/one-page
    # collection. Existing trusted OCR is reused; only genuinely missing pages
    # are bought. Imported source ledgers and snapshots remain untouched.
    hosted_ocr.ReplayOCRStore = MissingOCR

    def guarded(probe, *a, **kw):
        fence = I5Budget(
            shared, {"openai": probe.ledger.resolve()}, output.parent / "paid-calls.jsonl"
        )
        fence.task, fence.limit_usd = task, Decimal(limit)
        return fence.guarded(original, "openai", lambda *a: Decimal(".02"))(probe, *a, **kw)

    OpenAIProbe.complete = guarded
    result = main(
        claim_pages={case: pages},
        workers=8,
        budget=".8",
        event_id="F1-USD0.8",
        integration_policy=integration_policy,
        local_grant_factory=local_grant_factory,
        source_states={case: source_state},
        extraction_batch_calls=100,
    )
    state = output / case
    gate = result["admission"]
    failures = dict(
        failed_calls=gate["failed_calls"],
        deferred_calls=gate["circuit_deferred"],
        total=gate["failed_calls"] + gate["circuit_deferred"],
    )
    measurement = json.loads((state / "measurement.json").read_text())
    stages = measurement["stages"]
    partial = bool(failures["total"] or stages.get("tag") != "completed")
    stage_reason = result["results"][case].get("reason")
    if partial and not stage_reason:
        stage_reason = "R108_" + stages.get("tag", "NOT_RUN").upper()
    outcome = dict(
        status="partial_blocked" if partial else "completed",
        reason="PROVIDER_PROCESSING_FAILED"
        if failures["total"]
        else stage_reason
        if partial
        else None,
        provider_failures=failures,
        stage_seconds=measurement["stage_seconds"],
        provider_concurrency=gate,
        analysis_policy_sha256=measurement["analysis_policy_sha256"],
    )
    (state / "outcome.json").write_text(json.dumps(outcome))
    subprocess.run([sys.executable, "-m", "evaluation.s2_publish", str(state)], check=True)
    print(
        json.dumps(
            dict(case=case, outcome=outcome, result_published=(state / "result.json").is_file())
        ),
        flush=True,
    )


if __name__ == "__main__":
    run()
