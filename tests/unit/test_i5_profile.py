from argparse import Namespace

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_analysis import operator_profiles


def test_i5_composes_i4_h1_s2_and_keeps_historical_pins():
    policy = profiles.FINALS_I5_POLICY
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy)) == policy
    assert policy["integration_profile"] == "finals-20261012-v5"
    for old in (
        profiles.FINALS_I1_POLICY,
        profiles.FINALS_I2_POLICY,
        profiles.FINALS_I3_POLICY,
        profiles.FINALS_I4_POLICY,
        profiles.FINALS_H1_POLICY,
        profiles.S2_POLICY,
    ):
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(old)) == old
    assert (
        canonical_hash(profiles.FINALS_I4_POLICY)
        == "7381e57fb2ddc2bb75149eb7c0254c366cfb76a8478537f59075800a1ca193fe"
    )
    assert policy["tagging_prompt_policy"] == profiles.FINALS_I4_POLICY["tagging_prompt_policy"]
    assert policy["tagging_budget"] == profiles.S2_POLICY["tagging_budget"]
    assert policy["source"] == "upstage-ocr-page-v12"
    assert policy["verified_read_cache"]["profile"] == "exact-verified-read-v7"
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=canonical_hash(policy)
    )
    profiles.apply_pilot_profile(args)
    assert args.extraction_i4_identity and args.extraction_h1 and args.extraction_i5_tables
    assert args.parser_local_resource_policy == "selected-pdf-h1-v1"
    assert args.claim_source_profile == "upstage-ocr-page-v12"
    assert args.tagging_max_calls == 2000
    config = dict(
        analysis_profile=profiles.V2_PROFILE, analysis_policy_sha256=canonical_hash(policy)
    )
    assert operator_profiles(config)["llm_max_workers"] == 16
    assert operator_profiles(config | dict(llm_max_workers=8))["llm_max_workers"] == 8
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy))
        == policy
    )


def test_i5_hosted_argv_selects_default_budget_and_operator_override(tmp_path):
    from pypdf import PdfWriter

    from evaluation.hosted_r108 import prepare_argv

    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    pdf = tmp_path / "selected.pdf"
    writer.write(pdf)
    config = dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31")
    argv = prepare_argv(
        pdf, tmp_path / "state", "tenant", config, dict(analysis_profile=profiles.V2_PROFILE)
    )
    assert argv[argv.index("--tagging-max-calls") + 1] == "2000"
