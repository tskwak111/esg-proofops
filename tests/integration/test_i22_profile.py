"""V22 composes FXA/FXB with v21 execution and preserves historical pins."""

from proofops.adapters.local import claim_source_verification_v4 as prose
from proofops.adapters.local.claim_source_policies import page_ocr_profile, publication_reader
from proofops.application import analysis_profile as profiles
from proofops.application.tagging import fact_assembly_c3_v2 as c3
from proofops.domain.provenance import canonical_hash


def test_v22_default_activates_fixes_and_retains_v21_execution():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I22_POLICY)
    )
    assert policy == profiles.FINALS_I22_POLICY
    assert policy["integration_profile"] == "finals-20261015-v22"
    assert policy["fact_assembly_profile"] == "grade-relevant-unanimity-v2"
    assert policy["direct_certification_policy"] == c3.POLICY
    assert policy["direct_certification_policy_sha256"] == c3.POLICY_HASH
    assert policy["verified_read_cache"] == profiles.VERIFIED_READ_V12_POLICY
    assert not policy["general_certification"]["enabled"]
    assert policy["replicas"] == 3
    changed = {
        "integration_profile",
        "fact_assembly_profile",
        "direct_certification_policy",
        "direct_certification_policy_sha256",
    }
    assert {k: v for k, v in policy.items() if k not in changed} == {
        k: v for k, v in profiles.FINALS_I21_POLICY.items() if k not in changed
    }
    assert canonical_hash(policy) != canonical_hash(profiles.FINALS_I21_POLICY)
    reader = page_ocr_profile(policy["source"])
    assert publication_reader(reader.claim_source_policy()) is reader
    assert reader.claim_source_policy()["prose_policy_sha256"] == canonical_hash(
        prose.claim_source_policy()
    )


def test_v22_registry_preserves_exact_historical_and_standalone_fxb_pins():
    for policy, expected in (
        (
            profiles.FINALS_I20_POLICY,
            "56bbc5fa8c2f1fd9e9c709c82ba473dec20b907e44195256caaf86e8a926ca32",
        ),
        (
            profiles.FINALS_I21_POLICY,
            "5158a121410dd311a9d905500858b58c4e3c2f68379a79429a2db399768c250d",
        ),
        (
            profiles.FINALS_FXB_POLICY,
            "c0c3ba7e9f0465ebd9526d5546052daaa598b1ffe72a333fe855cae003465d2c",
        ),
    ):
        pin = canonical_hash(policy)
        assert pin == expected
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy


def test_hosted_preparation_retains_v21_and_fxb_pins(tmp_path):
    from pypdf import PdfWriter

    from evaluation.hosted_r108 import prepare_argv

    pdf = tmp_path / "selected.pdf"
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.write(pdf)
    for policy in (
        profiles.FINALS_I21_POLICY,
        profiles.FINALS_FXB_POLICY,
        profiles.FINALS_I22_POLICY,
        profiles.FINALS_I23_POLICY,
        profiles.FINALS_FXC_POLICY,
        profiles.FINALS_D2_POLICY,
    ):
        pin = canonical_hash(policy)
        argv = prepare_argv(
            pdf,
            tmp_path / pin,
            "11111111-1111-4111-8111-111111111111",
            dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
            dict(
                pages=[36],
                claim_pages=[36],
                pipeline_profile=profiles.V2_PROFILE,
                analysis_profile_sha256=pin,
            ),
        )
        assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
