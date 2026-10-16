"""K7 frozen selections through the merged policies; providers are forbidden."""

import argparse
import sys
from pathlib import Path

from proofops.application.analysis_profile import FINALS_K7_POLICY

from evaluation.i1_replay import main as dl4_main
from evaluation.k6_holdout_replay import main as coverage_main


def main():
    mode = sys.argv.pop(1)
    if mode == "dl4":
        dl4_main(integration_policy=FINALS_K7_POLICY, baseline_dir="perf/I6/A-linux")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if mode != "holdout":
        raise ValueError("I6_REPLAY_MODE_UNKNOWN")
    # Reuse I6's immutable final source decisions. K7 changes no selection rule;
    # reprocess the same candidate spans and independently audit the native PDF.
    # Fresh K7 source admission is tested separately on the four Hyundai rows.
    root = Path("/path/to/ESG_ProofOps/outputs/agent-results/R108-redesign/lab")
    coverage_main(
        policy=FINALS_K7_POLICY,
        output=args.output,
        baseline_root=root / "perf/I6/holdout/holdout",
    )


if __name__ == "__main__":
    main()
