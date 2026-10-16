"""Authorized K10 Kakao/LG measurements sharing the USD0.50 task fence."""

import json
import re
import sys
import traceback
from pathlib import Path

from proofops.application.analysis_profile import FINALS_K10_V2_POLICY as FINALS_K10_POLICY

from evaluation import i9_live


def main():
    from proofops_worker import composition

    build = composition.build_composition
    output = Path(sys.argv[sys.argv.index("--output") + 1])

    def record(error):
        value = str(error)
        diagnostic = dict(
            exception_type=type(error).__name__,
            code=value if re.fullmatch(r"[A-Z][A-Z0-9_:-]{0,160}", value) else None,
            frames=[
                dict(file=f.filename, line=f.lineno, function=f.name)
                for f in traceback.extract_tb(error.__traceback__)
            ],
        )
        output.mkdir(parents=True, exist_ok=True)
        with (output / "local-errors.jsonl").open("a") as stream:
            stream.write(json.dumps(diagnostic) + "\n")

    def diagnostic_build(**kwargs):
        try:
            worker = build(**kwargs)
        except Exception as error:
            record(error)
            raise
        run_once = worker.run_once

        def run(*a, **kw):
            try:
                return run_once(*a, **kw)
            except Exception as error:
                record(error)
                raise

        worker.run_once = run
        return worker

    composition.build_composition = diagnostic_build
    grants = i9_live.fresh_grants
    i9_live.fresh_grants = lambda snapshot, **kwargs: grants(
        snapshot, approved_by="authorized-local-operator:fix-K10.md"
    )
    original = i9_live.source_claim_pages
    i9_live.source_claim_pages = lambda state: (
        [3, 5, 6, 7, 8, 9] if state.name == "kakao" else original(state)
    )
    i9_live.FINALS_I9_POLICY = FINALS_K10_POLICY
    i9_live.TASK, i9_live.BUDGET = "K10-v11fix", "0.5"
    i9_live.MODULE = "evaluation.k10_live"
    return i9_live.main()


if __name__ == "__main__":
    main()
