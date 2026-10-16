"""I5 retained DL4/LG literal selection replay; no new model votes."""

from proofops.application.analysis_profile import FINALS_I5_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_I5_POLICY, baseline_dir="perf/I4/stage-A-adopted")
