"""Authorized S4 local live measurement; USD .40 shared fence, retained parsing/OCR."""

import json
import os
import re
import sys
import time
import traceback
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import S4_POLICY
from proofops_api.hosted_publication import make_handoff

from evaluation.f1_live import source_claim_pages
from evaluation.i1_live import main as live_main
from evaluation.i5_live import I5Budget
from evaluation.k8_authorization import fresh_grants


def main():
    root, out, case, publication_fd = (
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        sys.argv[3],
        int(sys.argv[4]),
    )
    lab = root / "outputs/agent-results/R108-redesign/lab"
    source = out.parent / "live-inputs" / case
    original = OpenAIProbe.complete

    def guarded(probe, *args, **kwargs):
        fence = I5Budget(
            lab / "sprint3/E2E/r108-spend.json",
            {"openai": probe.ledger.resolve()},
            out.parent / "paid-calls.jsonl",
        )
        fence.task, fence.limit_usd = "S4-v13cache", Decimal(".40")
        try:
            return fence.guarded(original, "openai", lambda *a: Decimal(".02"))(
                probe, *args, **kwargs
            )
        except Exception as error:
            code = str(error)
            safe = code if re.fullmatch(r"[A-Z][A-Z0-9_]+", code) else None
            with (out.parent / "live-errors.jsonl").open("a") as log:
                log.write(
                    json.dumps(
                        dict(
                            type=type(error).__name__,
                            code=safe,
                            frames=[
                                dict(file=Path(frame.filename).name, line=frame.lineno)
                                for frame in traceback.extract_tb(error.__traceback__)
                            ],
                        )
                    )
                    + "\n"
                )
            raise

    OpenAIProbe.complete = guarded
    sys.argv = [
        "s4-live",
        "--root",
        str(root),
        "--output",
        str(out),
        "--harness",
        str(lab / "fix/F1/f1_harness.py"),
        "--key-file",
        str(root / ".env.openai.local"),
        "--spend-ledger",
        str(out.parent / "spend.sqlite3"),
    ]
    started = time.monotonic()
    result = live_main(
        claim_pages={case: source_claim_pages(source)},
        workers=8,
        budget=".4",
        event_id="S4-USD0.4",
        integration_policy=S4_POLICY,
        source_states={case: source},
        extraction_batch_calls=100,
        local_grant_factory=lambda snapshot: fresh_grants(
            snapshot, approved_by="authorized-local-operator:speed-S4.md"
        ),
    )
    state = out / case
    measurement = json.loads((state / "measurement.json").read_text())
    complete = (
        result["results"][case]["status"] == "completed"
        and measurement["stages"].get("tag") == "completed"
    )
    (state / "outcome.json").write_text(
        json.dumps(
            dict(
                status="completed" if complete else "partial_blocked",
                reason=None if complete else "S4_STAGE_INCOMPLETE",
                stage_seconds=measurement["stage_seconds"],
                provider_concurrency=result["admission"],
            )
        )
    )
    manifest = json.loads((state / "pilot.json").read_text())
    job = dict(tenant_id=manifest["tenant_id"], run_id=manifest["run_id"], fence=1)
    begin = time.monotonic()
    packet = make_handoff(state, job, manifest["selected_pages"])
    if packet is None:
        raise ValueError("S4_PUBLICATION_HANDOFF_UNAVAILABLE")
    with os.fdopen(os.dup(publication_fd), "wb") as publication:
        publication.write(packet)
    (out / "child-timing.json").write_text(
        json.dumps(
            dict(
                seconds=time.monotonic() - started,
                child_publication_seconds=time.monotonic() - begin,
                status="completed" if complete else "partial_blocked",
                state=str(state),
            )
        )
    )
    # Timing is outside the attested state directory and cannot invalidate pins.
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
