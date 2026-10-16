"""Run exactly HX4's six Q2b scopes using the retained evaluator and shared budget.

Use the isolated interpreter from scripts/run_q2_corpus.sh so parser children
load the reviewed checkout. The unchanged Q2b harness supplies Codex Luna only;
its real OpenAI/OpenRouter fence and shared Upstage USD20 ledger stay in force.
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from proofops.application.analysis_profile import FINALS_HX4_COMPLETE_POLICY
from proofops.domain.provenance import canonical_hash

SLUGS = (
    "hold-samsung",
    "hold-sk",
    "report-918caaf1aa",
    "report-c62bfb8d7b",
    "oci",
    "report-806950b4e4",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--select", choices=SLUGS, action="append")
    parser.add_argument("--slug", choices=SLUGS)
    args = parser.parse_args()
    # evaluation is a namespace package; local product modules stay first.
    sys.path.append(str(args.harness.resolve()))
    from evaluation import q2_corpus as corpus

    corpus.V2_POLICY = FINALS_HX4_COMPLETE_POLICY
    if args.slug:
        corpus.run_one(args.output, args.slug)
        return
    if args.output.exists():
        raise ValueError("HX4_OUTPUT_EXISTS_USE_NEW_DIRECTORY")
    manifest = corpus.prepare(args.output)
    before = corpus.read(args.baseline / "manifest.json")
    reports = []
    for slug in SLUGS:
        if args.select and slug not in args.select:
            continue
        record = next(r for r in before["reports"] if r["slug"] == slug)
        record = record | {"retained_state": str(args.baseline / slug / "state")}
        reports.append(record)
    manifest.update(
        reports=reports,
        task="HX4",
        scope="same six Q2b PDF hashes and physical/claim pages",
        baseline_manifest_sha256=canonical_hash(before),
    )
    corpus.write(args.output / "manifest.json", manifest)

    def call(slug):
        folder = args.output / slug
        folder.mkdir()
        with (folder / "run.log").open("w") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "evaluation.hx4_replay",
                    "--harness",
                    str(args.harness),
                    "--baseline",
                    str(args.baseline),
                    "--output",
                    str(args.output),
                    "--slug",
                    slug,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode or not (folder / "summary.json").is_file():
            raise RuntimeError(f"HX4_RUNNER_FAILED:{slug}:{result.returncode}")
        return corpus.read(folder / "summary.json")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(call, r["slug"]) for r in reports]):
            row = future.result()
            print(
                json.dumps(
                    {
                        k: row[k]
                        for k in (
                            "slug",
                            "claims",
                            "source_verified",
                            "stage_statuses",
                            "execution_error",
                            "seconds",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    corpus.aggregate(args.output)
    comparisons = []
    for record in reports:
        slug = record["slug"]
        old = corpus.read(args.baseline / slug / "summary.json")
        new = corpus.read(args.output / slug / "summary.json")
        assert old["selected_pages"] == new["selected_pages"]
        assert old["claim_pages"] == new["claim_pages"]
        fields = (
            "parse_committed",
            "extraction_committed",
            "tagging_committed",
            "claims",
            "source_verified",
            "job_failures",
            "execution_error",
            "seconds",
            "stage_statuses",
        )
        comparisons.append(
            dict(
                slug=slug,
                source_sha256=record["source_sha256"],
                before={k: old[k] for k in fields},
                after={k: new[k] for k in fields},
            )
        )
    corpus.write(args.output / "before-after.json", comparisons)


if __name__ == "__main__":
    main()
