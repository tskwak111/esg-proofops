"""C24 raises execution ceilings without reinterpreting historical pins."""

import pytest
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_analysis import operator_profiles


def test_v10_default_changes_only_execution_limits():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_C24_POLICY)
    )
    assert policy["integration_profile"] == "finals-20261012-v10"
    assert policy == profiles.FINALS_I9_POLICY | dict(
        integration_profile="finals-20261012-v10",
        max_http_workers=24,
        provider_scheduler=profiles.FINALS_I9_POLICY["provider_scheduler"]
        | dict(profile="physical-attempt-role-queues-c24-v1", max_workers=24, max_rps=12),
        http_dispatch_guard="physical-attempt-role-queues-c24-v1",
    )
    assert policy["max_active_runs"] == 1
    default = operator_profiles({})
    assert (default["llm_max_workers"], default["llm_requests_per_second"]) == (8, 4)
    assert canonical_hash(policy) != canonical_hash(profiles.FINALS_I9_POLICY)


@pytest.mark.parametrize("workers,rps", [(8, 4), (16, 8), (24, 12)])
def test_v10_operator_accepts_boundary(workers, rps):
    selected = operator_profiles(dict(llm_max_workers=workers, llm_requests_per_second=rps))
    assert (selected["llm_max_workers"], selected["llm_requests_per_second"]) == (workers, rps)


@pytest.mark.parametrize(
    "field,value",
    [
        ("llm_max_workers", 25),
        ("llm_max_workers", True),
        ("llm_max_workers", 0),
        ("llm_requests_per_second", 13),
        ("llm_requests_per_second", True),
    ],
)
def test_v10_operator_rejects_invalid(field, value):
    with pytest.raises(ValueError, match="HOSTED_LLM_(CONCURRENCY|RPS)_INVALID"):
        operator_profiles({field: value})


def test_v9_pin_preserves_publication_and_limits():
    digest = canonical_hash(profiles.FINALS_I9_POLICY)
    assert digest == "b8086e636641355daf812bcbc8d0246a0bb14f57be5d81e77234a8b89f306c31"
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == (
        profiles.FINALS_I9_POLICY
    )
    config = dict(analysis_policy_sha256=digest)
    assert (
        operator_profiles(config | dict(llm_max_workers=16, llm_requests_per_second=8))[
            "llm_max_workers"
        ]
        == 16
    )
    for overrides in (dict(llm_max_workers=17), dict(llm_requests_per_second=9)):
        with pytest.raises(ValueError, match="HOSTED_LLM_(CONCURRENCY|RPS)_INVALID"):
            operator_profiles(config | overrides)


def test_provider_boundaries_and_v9_scheduler_pin():
    from proofops.adapters.local.provider_concurrency import ProviderConcurrency
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    assert ProviderConcurrency(24).snapshot()["limit"] == 24
    with pytest.raises(ValueError, match="CONCURRENCY_INVALID"):
        ProviderConcurrency(25)
    gate = RoleProviderConcurrency(24, requests_per_second=12)
    assert gate.snapshot()["requests_per_second"] == 12
    assert gate.snapshot()["scheduler"] == "physical-attempt-role-queues-c24-v1"
    for kwargs in (dict(workers=25), dict(workers=24, requests_per_second=13)):
        with pytest.raises(ValueError, match="(CONCURRENCY|RPS)_INVALID"):
            RoleProviderConcurrency(**kwargs)
    for kwargs in (dict(workers=17), dict(workers=16, requests_per_second=9)):
        with pytest.raises(ValueError, match="(CONCURRENCY|RPS)_INVALID"):
            RoleProviderConcurrency(
                **kwargs, scheduler_policy=profiles.FINALS_I9_POLICY["provider_scheduler"]
            )


def test_v10_response_policy_accepts_new_scheduler(tmp_path):
    from proofops.adapters.local.openai import OpenAIProbe

    selected = profiles.policy_for(profiles.V2_PROFILE)
    probe = OpenAIProbe("synthetic-test-key", tmp_path / "receipts.sqlite3")
    probe.configure_response_policy(
        dict(
            tenant_id="c24-test",
            document=dict(sha256="a" * 64),
            analysis_profile_policy=selected,
            analysis_profile_policy_sha256=canonical_hash(selected),
        ),
        role="extract",
    )
    assert probe.provider_scheduler == selected["provider_scheduler"]
    assert probe.http_dispatch_guard


def test_24_mixed_role_attempts_share_paced_physical_slots():
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(24, requests_per_second=12)
    barrier = threading.Barrier(24)
    starts = []
    lock = threading.Lock()

    def attempt(role):
        with gate.attempt(role):
            started = gate.pace_transport()
            with lock:
                starts.append(started)
            barrier.wait(timeout=6)
            time.sleep(0.01)

    with ThreadPoolExecutor(24) as pool:
        list(pool.map(attempt, ["extract", "preliminary", "relation", "elements"] * 6))
    snapshot = gate.snapshot()
    assert snapshot["peak"] == 24
    assert snapshot["active"] == 0
    assert snapshot["physical_attempts"] == 24
    assert all(count == 6 for count in snapshot["completed_by_role"].values())
    assert all(b - a >= 1 / 12 for a, b in zip(sorted(starts), sorted(starts)[1:]))
