"""I5/H1 same-selection holdout replay under the frozen A scorer."""

import argparse
from pathlib import Path

from proofops.application.analysis_profile import FINALS_I5_POLICY

from evaluation.h1_holdout import CASES
from evaluation.h1_replay import measure

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for company in CASES:
        measure(company, label="holdout", policy=FINALS_I5_POLICY, output_root=args.output)
