"""I7 frozen DL4/LG and holdout selections, with transports forbidden."""

import sys

from proofops.application.analysis_profile import FINALS_I7_POLICY

from evaluation import i6_replay


def main():
    i6_replay.FINALS_I6_POLICY = FINALS_I7_POLICY
    if sys.argv[1] == "dl4":
        from evaluation.i1_replay import main as replay

        sys.argv.pop(1)
        return replay(integration_policy=FINALS_I7_POLICY, baseline_dir="perf/I6/A-linux")
    return i6_replay.main()


if __name__ == "__main__":
    main()
