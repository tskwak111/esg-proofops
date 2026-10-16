"""Authenticated I4 raw selections through K6 restoration and Python guards."""

from proofops.application.analysis_profile import FINALS_K6_POLICY

from evaluation.k4_replay import main

if __name__ == "__main__":
    main(inputs_dir="perf/I4/native-final/stage-B", integration_policy=FINALS_K6_POLICY)
