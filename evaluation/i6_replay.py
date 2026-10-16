"""I6 frozen selections through the merged policies; providers are forbidden."""

import argparse
import sys
from pathlib import Path

from proofops.application.analysis_profile import FINALS_I6_POLICY

from evaluation.h1_holdout import CASES
from evaluation.h1_replay import measure
from evaluation.i1_replay import main as dl4_main
from evaluation.k6_holdout_replay import main as coverage_main


def main():
    mode = sys.argv.pop(1)
    if mode == "dl4":
        dl4_main(integration_policy=FINALS_I6_POLICY, baseline_dir="perf/I5/A-final")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if mode != "holdout":
        raise ValueError("I6_REPLAY_MODE_UNKNOWN")
    for company in CASES:
        measure(company, label="base", policy=FINALS_I6_POLICY, output_root=args.output)
    coverage_main(policy=FINALS_I6_POLICY, output=args.output, baseline_root=args.output / "base")


if __name__ == "__main__":
    main()
