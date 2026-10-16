"""I13 retained-input replay; underlying runners forbid provider access."""

from proofops.application.analysis_profile import FINALS_I13_POLICY

from evaluation import i10_replay


def main():
    i10_replay.FINALS_I10_POLICY = FINALS_I13_POLICY
    return i10_replay.main()


if __name__ == "__main__":
    main()
