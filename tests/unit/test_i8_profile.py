"""V8 default adoption retains the complete historical replay/publication contract."""

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v8_default_uses_final_k9_without_changing_v7():
    current = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I8_POLICY)
    )
    assert current["integration_profile"] == "finals-20261012-v8"
    assert current == profiles.FINALS_K9_POLICY | dict(integration_profile="finals-20261012-v8")
    assert canonical_hash(profiles.FINALS_I7_POLICY) == (
        "0d10ccb21b953f5c29846438fb72538baf50ebd280c45d89b5adbf727c6c9efb"
    )
    assert canonical_hash(profiles.FINALS_K9_POLICY) == (
        "7c9b238a4b3d10d54f5400f5fda2cd395a52ed476b34865c3309c1f71810e6d5"
    )


def test_v8_preserves_all_finals_publication_and_replay_pins():
    for name in (
        "FINALS_I5_POLICY",
        "FINALS_I6_POLICY",
        "FINALS_I7_POLICY",
        "FINALS_K7_POLICY",
        "FINALS_K8_V3_POLICY",
        "FINALS_F1_POLICY",
        "FINALS_K9_INITIAL_POLICY",
        "FINALS_K9_V2_POLICY",
        "FINALS_K9_V3_POLICY",
        "FINALS_K9_V4_POLICY",
        "FINALS_K9_POLICY",
    ):
        policy = getattr(profiles, name)
        pin = canonical_hash(policy)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy


def test_v8_keeps_live_resource_and_resilience_contracts():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I8_POLICY)
    )
    assert policy["max_http_workers"] == 8
    assert policy["extract_batch_calls"] == 100
    assert policy["max_active_runs"] == 1
    assert policy["provider_resilience"] == profiles.FINALS_I7_POLICY["provider_resilience"]


def test_v8_provider_failure_preserves_pending_charge_and_sibling_call(tmp_path, monkeypatch):
    from tests.test_t1_403_retry import costs, setup, success, wire

    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I8_POLICY)
    )
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=policy,
            analysis_profile_policy_sha256=canonical_hash(policy),
        ),
        role="extract",
    )
    calls = wire(monkeypatch, iter([(403, b"", {}), success()]))
    with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
        probe.complete("JSON", "{}", request_id="failed-v8", json_mode=True)
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    assert probe.complete("JSON", '{"next":true}', request_id="next-v8", json_mode=True)[
        "schema_valid"
    ]
    assert len(calls) == 2
    assert [row[1] for row in costs(store)] == ["accounting_pending", "settled"]
