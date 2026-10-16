"""Exercise H1 boundaries on the same retained LG/NAVER/Kia regression inputs."""

from proofops.application.analysis_profile import FINALS_H1_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_H1_POLICY, baseline_dir="perf/I1/stage-A-delivery")
