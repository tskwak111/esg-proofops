"""K11 retained extraction replay with provider access forbidden."""

from proofops.application.analysis_profile import FINALS_K11_POLICY

from evaluation import i10_replay


def main():
    i10_replay.FINALS_I10_POLICY = FINALS_K11_POLICY
    return i10_replay.main()


if __name__ == "__main__":
    main()
