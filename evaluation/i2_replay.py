"""I1 v1 versus integrated v2 on the same frozen 8 gold pages and LG 13 pages."""

from proofops.application.analysis_profile import FINALS_I2_J3_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_I2_J3_POLICY, baseline_dir="perf/I1/stage-A-delivery")
