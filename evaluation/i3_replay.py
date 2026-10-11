"""I3 combined policy on the same retained 8 gold + LG 13 pages."""

from proofops.application.analysis_profile import FINALS_I3_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_I3_POLICY, baseline_dir="perf/I1/stage-A-delivery")
