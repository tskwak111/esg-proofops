"""V28 adds only RB4 memory policies to the complete immutable v27 pin."""

import pytest
from proofops.application import analysis_profile as profiles
from proofops.application.rb4_memory import enabled, publication_enabled
from proofops.domain.provenance import canonical_hash


def test_v28_composition_and_v27_replay():
    current = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I28_POLICY)
    )
    assert current == profiles.FINALS_I28_POLICY
    assert current == profiles.FINALS_I27_POLICY | dict(
        integration_profile="finals-20261016-v28",
        rb4_memory=profiles.RB4_STREAM_POLICY["rb4_memory"],
        rb4_publication_digest=profiles.RB4_STREAM_POLICY["rb4_publication_digest"],
    )
    assert current["source"] == "s5_claim_source_v1"
    assert enabled({"analysis_profile_policy": current})
    assert publication_enabled(current)
    for policy, digest in (
        (
            profiles.FINALS_I27_POLICY,
            "fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804",
        ),
        (
            profiles.RB4_STREAM_POLICY,
            "d9599dbe30aa9fd53852b938b0055a1ac3b79932d7f498b045c820b301dfe013",
        ),
    ):
        assert canonical_hash(policy) == digest
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == policy
    assert not enabled({"analysis_profile_policy": profiles.FINALS_I27_POLICY})
    assert not publication_enabled(profiles.FINALS_I27_POLICY)


@pytest.mark.parametrize("selected", [profiles.FINALS_I27_POLICY, profiles.FINALS_I28_POLICY])
def test_hosted_child_preserves_integrated_pins(tmp_path, selected):
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(selected)
    config = dict(
        analysis_profile=profiles.V2_PROFILE,
        analysis_policy_sha256=pin,
        llm_provider="openai",
        report_year=2025,
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    args = prepare_argv(
        pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256=pin)
    )
    assert args[args.index("--analysis-policy-sha256") + 1] == pin
    with pytest.raises(ValueError, match="PIN_MISMATCH"):
        prepare_argv(
            pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256="0" * 64)
        )
