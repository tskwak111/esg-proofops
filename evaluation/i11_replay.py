"""I11 retained-input DL4/holdout/quality replay; providers are forbidden."""

from proofops.application.analysis_profile import FINALS_I11_POLICY

from evaluation import i10_replay


def main():
    i10_replay.FINALS_I10_POLICY = FINALS_I11_POLICY
    return i10_replay.main()


if __name__ == "__main__":
    main()
