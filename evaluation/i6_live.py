"""Fresh I6 model runs within one shared USD .80 authorization."""

import json
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_I6_POLICY
from proofops_api.hosted_analysis import read_key

from evaluation.i1_live import main as live_main
from evaluation.i5_live import I5Budget

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"


class I6Budget(I5Budget):
    def __init__(self, spend_path, ledgers=None, events_path=None, **kwargs):
        super().__init__(spend_path, ledgers, events_path, **kwargs)
        self.task, self.limit_usd = "I6-integration", Decimal(".8")


def main():
    case = sys.argv.pop(1)
    out = Path(sys.argv[sys.argv.index("--output") + 1])
    shared = LAB / "sprint3/E2E/r108-spend.json"
    events = out.parent / "paid-calls.jsonl"
    original = OpenAIProbe.complete

    def guarded(probe, *args, **kwargs):
        fence = I6Budget(shared, {"openai": probe.ledger.resolve()}, events)
        return fence.guarded(original, "openai", lambda *a: Decimal(".02"))(probe, *args, **kwargs)

    OpenAIProbe.complete = guarded
    if case in ("sk", "posco", "hyundai"):
        from evaluation.h1_product import main as product

        states = LAB / "fix/A/paid-dec26/states"
        config = {
            "sk": ("SK하이닉스", (19, 23), (19,), ("SK하이닉스",)),
            "posco": ("POSCO홀딩스", (39, 42), (42,), ("POSCO홀딩스",)),
            "hyundai": (
                "현대자동차-p22",
                (22, 41),
                (41,),
                ("현대자동차-extraction-initial-failed",),
            ),
        }
        source, selected, focal, cached = config[case]
        fence = I6Budget(shared, events_path=events)
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
            workers=16,
            output_dir=out,
            probe_factory=factory,
            budget_factory=I6Budget,
            input_state=states / source,
            selected_pages=selected,
            claim_pages=focal,
            cached_states=tuple(states / name for name in cached),
        )
    if case == "lg":
        sources = {"lgchem": LAB / "perf/S2/source-lg"}
        pages = {"lgchem": list(range(1, 14))}
    elif case == "B":
        sources, pages = None, dict(naver=[88], kia=[106])
    else:
        raise ValueError("I6_CASE_UNKNOWN")
    result = live_main(
        claim_pages=pages,
        workers=16,
        budget=".6",
        event_id="I6-USD0.8-" + case,
        integration_policy=FINALS_I6_POLICY,
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
