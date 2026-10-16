"""K6 on the frozen eight gold pages plus LG; network-free literal replay."""

from proofops.application.analysis_profile import FINALS_K6_POLICY

from evaluation.i1_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_K6_POLICY, baseline_dir="perf/I4/stage-A-final")
