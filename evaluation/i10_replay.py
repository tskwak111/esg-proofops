"""I10 offline DL4/LG13/holdout and Q1 cases with transport forbidden."""

import sys

from proofops.application.analysis_profile import FINALS_I10_POLICY


def main():
    mode = sys.argv.pop(1)
    if mode == "dl4":
        from evaluation.i1_replay import main as replay

        return replay(
            integration_policy=FINALS_I10_POLICY,
            baseline_dir="perf/I9/A-dl4-linux-v2",
            retained_prose_only=True,
        )
    if mode == "cases":
        from evaluation import q1_replay

        q1_replay.FINALS_Q1_POLICY = FINALS_I10_POLICY
        return q1_replay.main()
    from evaluation import i6_replay

    i6_replay.FINALS_I6_POLICY = FINALS_I10_POLICY
    sys.argv.insert(1, mode)
    return i6_replay.main()


if __name__ == "__main__":
    main()
