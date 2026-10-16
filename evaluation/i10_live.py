"""I10 authorized LG13 timing, sharing one USD0.80 fence with focal probes."""

from proofops.application.analysis_profile import FINALS_I10_POLICY

from evaluation import i9_live


def main():
    i9_live.FINALS_I9_POLICY = FINALS_I10_POLICY
    i9_live.TASK, i9_live.BUDGET = "I10-integration", "0.8"
    i9_live.MODULE = "evaluation.i10_live"
    return i9_live.main()


if __name__ == "__main__":
    main()
