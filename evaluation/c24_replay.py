"""C24 offline replay of the frozen DL4/LG inputs against v9; no transport."""

from proofops.application.analysis_profile import FINALS_C24_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_C24_POLICY, baseline_dir="perf/I9/A-dl4-linux-v2")
