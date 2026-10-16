from argparse import Namespace

from proofops.application.analysis_profile import (
    FINALS_I3_POLICY,
    FINALS_I5_POLICY,
    FINALS_I6_POLICY,
    S2_POLICY,
    apply_pilot_profile,
    policy_for,
    publication_policy_for,
)
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_analysis import operator_profiles


def test_s2_private_pin_selects_16_and_claim_budget_but_preserves_i3():
    pin = canonical_hash(S2_POLICY)
    config = dict(analysis_profile="finals-unattended-v2", analysis_policy_sha256=pin)
    assert operator_profiles(config)["llm_max_workers"] == 16
    assert operator_profiles(config | dict(llm_max_workers=8))["llm_max_workers"] == 8
    assert operator_profiles(dict(analysis_profile="finals-unattended-v2"))["llm_max_workers"] == 8
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I3_POLICY))
        == FINALS_I3_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I6_POLICY))
        == FINALS_I6_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I5_POLICY))
        == FINALS_I5_POLICY
    )
    assert publication_policy_for("finals-unattended-v2", pinned_hash=pin) == S2_POLICY
    assert canonical_hash(FINALS_I3_POLICY) == (
        "830ce06b7dec224b15be7a60d9813bd08038e5a229709193e6c621a9e18f92e3"
    )
    args = Namespace(analysis_profile="finals-unattended-v2", analysis_policy_sha256=pin)
    apply_pilot_profile(args)
    assert args.tagging_max_calls == 2000
    assert args.claim_source_profile == "upstage-ocr-page-v11"


def test_hosted_argv_passes_s2_pin_and_2000_calls(tmp_path):
    from pypdf import PdfWriter

    from evaluation.hosted_r108 import prepare_argv

    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    pdf = tmp_path / "selected.pdf"
    writer.write(pdf)
    config = dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31")
    pin = canonical_hash(S2_POLICY)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "tenant",
        config,
        dict(
            analysis_profile="finals-unattended-v2",
            analysis_profile_sha256=pin,
        ),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    assert argv[argv.index("--tagging-max-calls") + 1] == "2000"
