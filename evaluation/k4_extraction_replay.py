"""K4 complete-clause replay against the retained I3 eight-page baseline."""

from proofops.application.analysis_profile import FINALS_K4_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_K4_POLICY, baseline_dir="perf/I3/stage-A-delivery")
