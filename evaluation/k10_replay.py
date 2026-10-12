"""K10 DL4/holdout retained-input replay with provider access forbidden."""

from proofops.application.analysis_profile import FINALS_K10_V2_POLICY as FINALS_K10_POLICY

from evaluation import i10_replay


def main():
    i10_replay.FINALS_I10_POLICY = FINALS_K10_POLICY
    return i10_replay.main()


if __name__ == "__main__":
    main()
