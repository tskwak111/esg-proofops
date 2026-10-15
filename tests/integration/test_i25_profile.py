"""V25 composition, hosted assignment and historical replay contracts."""

from proofops.application import analysis_profile as profiles
from proofops.application.tagging.analysis_scope import analyze_scope, replay_scope
from proofops.application.tagging.v1_activity_links import policy_from_profile
from proofops.domain.provenance import canonical_hash


def test_v25_composes_each_reviewed_delta_and_keeps_every_old_pin():
    current = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I25_POLICY)
    )
    assert current == profiles.FINALS_I25_POLICY
    assert current["integration_profile"] == "finals-20261015-v25"
    for policy in (profiles.V1_ACTIVITY_POLICY, profiles.QT1_V25_POLICY, profiles.V3_POLICY):
        pin = canonical_hash(policy)
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    for policy in (profiles.V1_ACTIVITY_POLICY, profiles.QT1_V25_POLICY, profiles.V3_POLICY):
        for key, value in policy.items():
            if key != "integration_profile" and value != profiles.FINALS_I24_POLICY.get(key):
                assert current[key] == value
    for key, value in profiles.FINALS_I24_POLICY.items():
        if key not in {
            "integration_profile",
            "tagging_prompt_profile",
            "tagging_prompt_policy",
            "tagging_prompt_policy_sha256",
            "hold_display",
        }:
            assert current[key] == value
    old = "775e8d04aaed82bd86c002402f3b80fdabd7206e69a1e768403cbc0644638501"
    assert canonical_hash(profiles.FINALS_I24_POLICY) == old
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=old)
        == profiles.FINALS_I24_POLICY
    )
    assert canonical_hash(current) != old


def test_hosted_current_and_explicit_v24_are_retained(tmp_path):
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    for selected in (profiles.policy_for(profiles.V2_PROFILE), profiles.FINALS_I24_POLICY):
        settings = dict(
            analysis_profile=profiles.V2_PROFILE,
            analysis_profile_sha256=canonical_hash(selected),
        )
        argv = prepare_argv(
            pdf,
            tmp_path / "state",
            "11111111-1111-4111-8111-111111111111",
            dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"),
            settings,
        )
        assert argv[argv.index("--analysis-policy-sha256") + 1] == canonical_hash(
            selected or profiles.FINALS_I25_POLICY
        )


def test_v25_inventory_activity_link_replays_e2_and_preserves_safety_hold(tmp_path):
    from tests.integration.test_r19_activity_links import scope_inputs

    inputs = scope_inputs(tmp_path)
    policy = profiles.FINALS_I25_POLICY
    before = analyze_scope(**inputs)
    inputs.update(
        v1_activity_policy=policy_from_profile(policy),
        grade_agreement_policy=policy["grade_required_agreement_policy"],
    )
    result = analyze_scope(**inputs)
    assert before["sc1_confirmation"] is None
    assert result["sc1_confirmation"]["evidence_grade"] == "E2"
    assert next(e for e in result["sc1_elements"] if e["element_id"] == "M2")["state"] == "present"
    replay_inputs = {
        k: v for k, v in inputs.items() if k not in {"v1_activity_policy", "grade_agreement_policy"}
    }
    assert replay_scope(result, **replay_inputs) == result
    held = analyze_scope(**(inputs | dict(prior_projection={"grade_basis": "retag_required"})))
    assert held["sc1_confirmation"] is None
    assert "SC1_EXISTING_SAFETY_HOLD" in held["reasons"]
