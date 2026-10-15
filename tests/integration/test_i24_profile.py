"""V24 composition and historical pin regression (no model/network calls)."""

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v24_pin_composes_all_and_keeps_v23():
    p = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I24_POLICY)
    )
    assert p["integration_profile"] == "finals-20261015-v24"
    assert p["source"] == "i24_claim_source_v1"
    assert p["fxg_extraction_wire_policy"] == profiles.FXG_POLICY["fxg_extraction_wire_policy"]
    assert p["qt1_table_recovery_policy"] == profiles.QT1_POLICY["qt1_table_recovery_policy"]
    assert (
        p["qt2_contextual_elements_policy"]
        == profiles.QT2_ELEMENTS_POLICY["qt2_contextual_elements_policy"]
    )
    assert (
        p["sc1_scope_confirmation"] == profiles.sc1_inventory_policies[0]["sc1_scope_confirmation"]
    )
    assert p["parser_failure_policy"] == "s3_partial-v7"
    assert p["verified_read_cache"] == profiles.S3_VERIFIED_READ_V13_POLICY
    assert p["grade_required_agreement_policy"]["minimum_present_replicas"] == 3
    old = "66669e915909dc62460931410c06215c4e520688523ada7f9bdb0e89724541b7"
    assert canonical_hash(profiles.FINALS_I23_POLICY) == old
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=old)
        == profiles.FINALS_I23_POLICY
    )
    assert canonical_hash(p) != old


def test_hosted_preparation_still_accepts_v23_pin(tmp_path):
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    old = canonical_hash(profiles.FINALS_I23_POLICY)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(
            report_year=2024,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
        dict(analysis_profile=profiles.V2_PROFILE, analysis_profile_sha256=old),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == old
