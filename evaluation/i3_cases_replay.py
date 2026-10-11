"""Revalidate R1 saved votes under combined K1/K2; source repair stays separate."""

from proofops.application.analysis_profile import FINALS_I3_POLICY

from evaluation.k2_replay import main

if __name__ == "__main__":
    main(integration_policy=FINALS_I3_POLICY)
