"""V26 composition and immutable historical/standalone publication pins."""
# ruff: noqa: F811

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v26_pin_has_exact_reviewed_deltas_and_keeps_pins():
    current = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I26_POLICY)
    )
    assert current == profiles.FINALS_I26_POLICY
    assert current["integration_profile"] == "finals-20261016-v26"
    expected = profiles.FXH_POLICY | dict(
        integration_profile="finals-20261016-v26",
        ops2_provider_fallback=profiles.OPS2_POLICY["ops2_provider_fallback"],
        ops2_page_render=profiles.OPS2_POLICY["ops2_page_render"],
    )
    assert current == expected
    assert not any("ch1" in str(value) for value in current.values())
    assert (
        current["direct_certification_policy"]
        == profiles.FINALS_I25_POLICY["direct_certification_policy"]
    )
    assert canonical_hash(profiles.FINALS_I25_POLICY) == (
        "2ed6dc6869c35a152887db1d55629c19a0902e95b8b50b64e5f52af25c86f4c0"
    )
    for policy in (
        profiles.FINALS_I24_POLICY,
        profiles.FINALS_I25_POLICY,
        profiles.FXH_POLICY,
        profiles.OPS2_POLICY,
        current,
    ):
        assert (
            profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(policy))
            == policy
        )


@pytest.mark.parametrize("force_fallback", [False, True])
def test_hosted_c3_uses_primary_even_when_regular_roles_use_fallback(
    settings, tmp_path, monkeypatch, force_fallback
):
    from proofops_api.hosted_analysis import HostedOpenAILunaProbe
    from proofops_api.hosted_ops2 import OPS2Probe

    from tests.test_hosted_hx2 import (
        test_public_default_upload_binding_parse_extract_tag_publication,
    )

    seen = []
    fallback_calls = []
    if force_fallback:
        from tests import test_hosted_hx2 as fixture

        generator = fixture.fake_llm
        init = OPS2Probe.__init__

        def unavailable(body):
            error = ValueError("OPENAI_HTTP_429")
            error.provider_error_code = "billing_not_active"
            raise error

        def fallback(body):
            fallback_calls.append(body["model"])
            return generator(body)

        def offline_init(self, *args, **kwargs):
            kwargs.update(fallback_post=fallback, fallback_key=lambda: "offline-router")
            init(self, *args, **kwargs)

        monkeypatch.setattr(OPS2Probe, "__init__", offline_init)
        monkeypatch.setattr(fixture, "fake_llm", unavailable)

    def inspect_factory(store, job, state, policy, factory, **kwargs):
        probe = factory("", state / "c3-primary-probe.sqlite3", wire_policy_version=2)
        assert isinstance(probe, HostedOpenAILunaProbe)
        assert not isinstance(probe, OPS2Probe)
        assert callable(probe.http_attempt_scope)
        assert callable(probe.http_transport_pacing)
        seen.append(True)
        return dict(status="outside_approved_source", published=False)

    monkeypatch.setattr("evaluation.hosted_c3.publish_current", inspect_factory)
    test_public_default_upload_binding_parse_extract_tag_publication(
        settings, tmp_path, monkeypatch
    )
    assert seen == [True]
    if force_fallback:
        assert len(fallback_calls) >= 3
        assert set(fallback_calls) == {"openai/gpt-6-luna"}
        import json

        outcome = json.loads((tmp_path / "worker/state/outcome.json").read_text())
        failures = outcome["provider_failures"]
        assert failures["failed_calls"] > 0
        assert failures["total"] == failures["recovered_by_fallback"]
        assert failures["unresolved_total"] == 0
        assert outcome["status"] == "completed"


def test_adaptive_page_render_follows_persisted_composed_pin():
    from proofops_api.hosted_reads import _ops2_fit_page

    for policy, expected in (
        (profiles.OPS2_POLICY, True),
        (profiles.FINALS_I26_POLICY, True),
        (profiles.FINALS_I25_POLICY, False),
        (profiles.FXH_POLICY, False),
    ):
        assert (
            _ops2_fit_page(
                dict(
                    analysis_profile=profiles.V2_PROFILE,
                    analysis_profile_sha256=canonical_hash(policy),
                )
            )
            is expected
        )
    assert not _ops2_fit_page({})
    assert not _ops2_fit_page(
        dict(analysis_profile=profiles.V2_PROFILE, analysis_profile_sha256="0" * 64)
    )


# Reuse the real public intake fixture, including its tenant and budget guards.
from tests.test_hosted_hx2 import settings  # noqa: E402,F401
