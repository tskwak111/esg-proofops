"""RG1 retained-response DL4/holdout regression; provider transports are forbidden."""

from proofops.application.analysis_profile import FINALS_RG1_POLICY

from evaluation import i10_replay


def main():
    i10_replay.FINALS_I10_POLICY = FINALS_RG1_POLICY
    return i10_replay.main()


if __name__ == "__main__":
    main()
