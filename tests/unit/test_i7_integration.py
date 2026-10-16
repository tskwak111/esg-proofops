"""Default integration preserves historical hashes and actual admission settings."""

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_analysis import operator_profiles
from proofops_api.hosted_store import HostedSettings


def test_v7_composes_k8_and_f1_without_rewriting_prior_pins():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I7_POLICY)
    )
    assert policy["integration_profile"] == "finals-20261012-v7"
    for key, value in profiles.FINALS_K8_V3_POLICY.items():
        if key not in {"integration_profile", "max_http_workers", "http_admission"}:
            assert policy[key] == value
    for key in (
        "openai_retry_policy",
        "provider_resilience",
        "http_dispatch_guard",
        "response_uncertainty_policy",
    ):
        assert policy[key] == profiles.FINALS_F1_POLICY[key]
    for old in (
        profiles.FINALS_I5_POLICY,
        profiles.FINALS_I6_POLICY,
        profiles.FINALS_K7_POLICY,
        profiles.FINALS_K8_V3_POLICY,
        profiles.FINALS_T1_POLICY,
        profiles.FINALS_F1_POLICY,
    ):
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(old)) == old
        assert (
            profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(old))
            == old
        )
    assert canonical_hash(profiles.FINALS_I6_POLICY) == (
        "568a110f32d723be3e569b14f12e676035175f19413c855e61d99d02870845b8"
    )
    assert canonical_hash(profiles.FINALS_K8_V3_POLICY) == (
        "3190ea744b0825f0586c835b78c996fa8dc69eef4bc4c6dac3218f161c90e130"
    )
    assert canonical_hash(profiles.FINALS_F1_POLICY) == (
        "84080775f1ce8e055e270f2c7e8b0fe6c05c6e204fd81a3234c68b48b57011f4"
    )


def test_v7_operator_defaults_are_eight_workers_batch100_four_rps_one_run(tmp_path):
    pin = canonical_hash(profiles.FINALS_I7_POLICY)
    policy = profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin)
    config = dict(analysis_policy_sha256=pin)
    operator = operator_profiles(config)
    assert operator["llm_max_workers"] == 8
    assert operator["extract_batch_calls"] == 100
    assert operator_profiles(config | {"llm_max_workers": 16})["llm_max_workers"] == 8
    assert operator_profiles(config | {"extract_batch_calls": 20})["extract_batch_calls"] == 20
    assert policy["provider_resilience"]["requests_per_second"] == 4
    assert policy["provider_resilience"]["consecutive_denials"] == 3
    settings = HostedSettings(tmp_path, "https://localhost", "x" * 32, "i7")
    assert settings.max_active_runs == policy["max_active_runs"] == 1
    prior = operator_profiles({"analysis_policy_sha256": canonical_hash(profiles.FINALS_I6_POLICY)})
    assert prior["llm_max_workers"] == 16 and prior["extract_batch_calls"] == 20
