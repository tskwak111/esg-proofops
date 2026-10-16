"""V11 promotion retains historical pins and uses recovery without reduction."""

import json
import sys

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v11_default_promotes_quality_diagnostics_and_scope_without_reduction():
    from evaluation.e06_scope import POLICY_SHA256, VERSION

    selected = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I10_POLICY)
    )
    assert selected["integration_profile"] == "finals-20261013-v11"
    for key in ("structural_quality_policy", "activity_table_policy", "tagging_prompt_policy"):
        assert selected[key] == profiles.FINALS_Q1_POLICY[key]
    assert (
        selected["http_diagnostic_policy"] == profiles.FINALS_E05_POLICY["http_diagnostic_policy"]
    )
    assert (selected["scope_ranking"], selected["scope_policy_sha256"]) == (VERSION, POLICY_SHA256)
    assert selected["scope_profile"] == "E06"
    assert selected["provider_scheduler"] == profiles.FINALS_C24_POLICY["provider_scheduler"]
    assert selected["replicas"] == 3
    assert selected["provider_resilience"]["consecutive_denials"] == 3
    for prior in (
        profiles.FINALS_C24_POLICY,
        profiles.FINALS_Q1_POLICY,
        profiles.FINALS_E05_POLICY,
    ):
        digest = canonical_hash(prior)
        assert digest != canonical_hash(selected)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == prior
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == prior


def test_hosted_scope_child_uses_v11_and_lazily_binds_discovery_to_tenant(tmp_path, monkeypatch):
    from proofops_api import hosted_scope

    calls = []
    output = tmp_path / "plan.json"

    def inspect(pdf, **kwargs):
        assert kwargs["scope_profile"] == "E06"
        assert kwargs["source_sha256"] == "a" * 64
        assert callable(kwargs["discovery_reader"])
        assert calls == []
        kwargs["discovery_reader"](3)
        return {"plan_sha256": "", "selected_evidence_pages": [1, 3], "source_path": str(pdf)}

    class Reader:
        def __init__(self, pdf, **kwargs):
            calls.append((pdf, kwargs))

        def __call__(self, page):
            return {"physical_page": page}

    monkeypatch.setattr("evaluation.hosted_scope_plan.inspect_streaming", inspect)
    monkeypatch.setattr("evaluation.scope_discovery_ocr.CPUDiscoveryReader", Reader)
    monkeypatch.setattr("resource.setrlimit", lambda *args: None)
    monkeypatch.setattr(
        sys, "argv", ["scope", str(tmp_path / "input.pdf"), str(output), "a" * 64, "tenant-A"]
    )
    hosted_scope.main()
    assert calls[0][1]["tenant_id"] == "tenant-A"
    assert calls[0][1]["source_sha256"] == "a" * 64
    assert json.loads(output.read_text())["selected_evidence_pages"] == [1, 3]
