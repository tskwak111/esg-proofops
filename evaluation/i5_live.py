"""I5 fresh-model canaries with one shared USD .60 task fence."""

import json
import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_I5_POLICY
from proofops_api.hosted_analysis import read_key

from evaluation.i1_live import main as live_main
from evaluation.i4_live import I4Budget

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"


class I5Budget(I4Budget):
    def __init__(self, spend_path, ledgers=None, events_path=None, **kwargs):
        super().__init__(spend_path, events_path)
        self.task = "I5-integration"
        self.ledgers = ledgers or {}

    def reserve(self, bound):
        # Wait for active reservations to settle; never reclaim uncertainty or
        # exceed either task/shared ceiling. This changes no provider retry rule.
        deadline = time.monotonic() + 120
        while True:
            try:
                return super().reserve(bound)
            except ValueError as error:
                if str(error) != "R108_FINALS_BUDGET_EXHAUSTED":
                    raise
                with self.transaction() as (_, entry):
                    active = Decimal(entry["reserved_usd"]) > 0
                    affordable = Decimal(entry["delta_usd"]) + bound <= self.limit_usd
                if not active or not affordable or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)


def main():
    case = sys.argv.pop(1)
    out = Path(sys.argv[sys.argv.index("--output") + 1])
    shared = LAB / "sprint3/E2E/r108-spend.json"
    events = out.parent / "paid-calls.jsonl"
    original = OpenAIProbe.complete

    def guarded(probe, *args, **kwargs):
        fence = I5Budget(shared, {"openai": probe.ledger.resolve()}, events)
        return fence.guarded(original, "openai", lambda *a: Decimal(".02"))(probe, *args, **kwargs)

    OpenAIProbe.complete = guarded
    if case == "hyundai":
        from evaluation.h1_product import main as product

        fence = I5Budget(shared, events_path=events)
        original_total = OpenAIProbe._total

        def task_total(probe, db):
            original_total(probe, db)
            with fence.transaction() as (_, entry):
                return Decimal(entry["delta_usd"])

        OpenAIProbe._total = task_total

        def factory():
            return OpenAIProbe(
                read_key(str(ROOT / ".env.openai.local"), "OPENAI_API_KEY"),
                ROOT / ".local/openai/budget.sqlite3",
            ), fence

        out.mkdir(parents=True, exist_ok=False)
        return product(
            workers=int(os.environ.get("I5_CANARY_WORKERS", "16")),
            output_dir=out,
            probe_factory=factory,
            budget_factory=I5Budget,
        )
    if case == "lg":
        sources = {"lgchem": LAB / "perf/S2/source-lg"}
        pages = {"lgchem": list(range(1, 14))}
    elif case == "B":
        sources, pages = None, dict(naver=[88], kia=[106])
    else:
        raise ValueError("I5_CASE_UNKNOWN")
    result = live_main(
        claim_pages=pages,
        workers=16,
        budget=".6",
        event_id="I5-USD0.6",
        integration_policy=FINALS_I5_POLICY,
        source_states=sources,
        extraction_batch_calls=100 if case == "lg" else None,
    )
    if case == "lg" and result["results"]["lgchem"]["status"] == "completed":
        (out / "lgchem/outcome.json").write_text(json.dumps(dict(status="completed", reason=None)))
        started = time.monotonic()
        subprocess.run(
            [sys.executable, "-m", "evaluation.s2_publish", str(out / "lgchem")], check=True
        )
        path = out / "lgchem/measurement.json"
        measurement = json.loads(path.read_text())
        measurement["publication_seconds"] = time.monotonic() - started
        measurement["pipeline_and_publication_seconds"] = (
            measurement["seconds"] + measurement["publication_seconds"]
        )
        path.write_text(json.dumps(measurement, indent=2))
    return 0 if all(r["status"] == "completed" for r in result["results"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
