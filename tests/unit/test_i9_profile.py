"""I9 integrates execution improvements while retaining prior evidence policies."""

from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v9_operator_controls_apply_to_the_current_default():
    from proofops_api.hosted_analysis import operator_profiles

    for workers, rps in ((8, 4), (12, 6), (16, 8)):
        configured = operator_profiles(dict(llm_max_workers=workers, llm_requests_per_second=rps))
        assert configured["llm_max_workers"] == workers
        assert configured["llm_requests_per_second"] == rps
    default = operator_profiles({})
    assert (default["llm_max_workers"], default["llm_requests_per_second"]) == (8, 4)


def test_v9_pin_composes_v8_s4_s5_without_domain_changes():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I9_POLICY)
    )
    assert policy["integration_profile"] == "finals-20261012-v9"
    expected = (
        profiles.FINALS_I8_POLICY
        | {key: profiles.S4_POLICY[key] for key in ("verified_read_cache", "publication_handoff")}
        | {
            key: profiles.FINALS_S5_POLICY[key]
            for key in (
                "provider_scheduler",
                "http_dispatch_guard",
                "http_admission",
                "max_http_workers",
                "worker_resources",
            )
        }
        | dict(integration_profile="finals-20261012-v9")
    )
    assert policy == expected
    assert policy["provider_resilience"]["consecutive_denials"] == 3


def test_v9_retains_historical_publication_and_replay():
    for name, expected_hash in (
        ("FINALS_I8_POLICY", "55675a8ada572b8012eae78d51d479df67112a7aa4fb0eb03baa22cdc6817d1a"),
        ("S4_POLICY", "8a9c6cd4be88ffa739e688e36ee8fc701d29fcce3650bb1ff8d9b6c66ae2f619"),
        ("FINALS_S5_POLICY", "f6e2bb3307eab80b60a06dce0b9e8f48d632cb2f37a9bf80597734e9e6b8dbf7"),
    ):
        policy = getattr(profiles, name)
        assert canonical_hash(policy) == expected_hash
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=expected_hash) == policy
        assert (
            profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=expected_hash)
            == policy
        )
