"""FX6: normalized uncertain delivery preserves publication and reserved money."""

import time
from decimal import Decimal

import pytest
from proofops_api.hosted_store import HostedError

from tests.test_t1_403_retry import setup


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
def test_normalized_uncertainty_retains_fence_and_budget(tmp_path, monkeypatch, provider):
    store, auth, job, _, _ = setup(tmp_path, monkeypatch, cap=".02")

    def uncertain(request):
        raise ValueError("PROCESSING_UNCERTAIN")

    with pytest.raises(HostedError, match="^PROCESSING_UNCERTAIN$"):
        store.dispatch(
            job, provider, "uncertain", "a" * 64, Decimal(".011"), uncertain, now=time.time()
        )
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    store.update_progress(job, "tag", 75)
    with pytest.raises(HostedError, match="DISPATCH_ALREADY_RECORDED"):
        store.dispatch(
            job, provider, "uncertain", "a" * 64, Decimal(".011"), uncertain, now=time.time()
        )
    with pytest.raises(HostedError, match="BUDGET_EXCEEDED"):
        store.dispatch(
            job, provider, "over-budget", "b" * 64, Decimal(".011"), uncertain, now=time.time()
        )
    with store.transaction() as db:
        assert tuple(db.execute("SELECT bound,actual,status FROM deletion.costs").fetchone()) == (
            11000,
            None,
            "accounting_pending",
        )
        assert db.execute("SELECT fence FROM runs").fetchone()[0] == job["fence"]


@pytest.mark.parametrize(
    "provider,error",
    [
        ("upstage", "PROCESSING_UNCERTAIN"),
        ("openai", "RECEIPT_MISMATCH"),
        ("openai", "RECEIPT_BOUND_EXCEEDED"),
        ("openai", "HOSTED_MODEL_MISMATCH"),
        ("openai", "unclassified failure"),
    ],
)
def test_uncertainty_does_not_hide_non_model_or_integrity_failures(
    tmp_path, monkeypatch, provider, error
):
    store, auth, job, _, _ = setup(tmp_path, monkeypatch)

    def fail(request):
        raise ValueError(error)

    with pytest.raises(ValueError, match=error):
        store.dispatch(
            job,
            provider,
            "fatal",
            "a" * 64,
            Decimal(".011"),
            fail,
            now=time.time(),
            allow_model_partial=True,
            allow_response_uncertainty=True,
        )
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.update_progress(job, "tag", 75)


def test_v29d_normalized_failure_is_request_local_without_retry(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import V2_POLICY
    from proofops.domain.provenance import canonical_hash

    from tests.unit.test_openai_luna import response

    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=V2_POLICY,
            analysis_profile_policy_sha256=canonical_hash(V2_POLICY),
        ),
        role="extract",
    )
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(
        1,
        requests_per_second=4,
        scheduler_policy=V2_POLICY["provider_scheduler"],
        resilience_directory=tmp_path / "events",
    )
    gate.bind(probe)
    calls = []

    def fail(body):
        calls.append(body)
        raise ValueError("PROCESSING_UNCERTAIN")

    probe.post = fail
    wire = canonical_hash(probe.wire_policy)
    with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
        probe.complete("JSON", "{}", request_id="uncertain", json_mode=True)
    assert len(calls) == 1
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    probe.post = lambda body: response('{"ok":true}')
    assert probe.complete("JSON", '{"next":true}', request_id="next", json_mode=True)[
        "schema_valid"
    ]
    assert probe.summary()["unsettled_calls"] == 1
    assert canonical_hash(probe.wire_policy) == wire
    with store.transaction() as db:
        assert tuple(
            db.execute(
                "SELECT bound,actual FROM deletion.costs WHERE status='accounting_pending'"
            ).fetchone()
        ) == (11000, None)

    from evaluation.hosted_r108 import provider_failure_blocks_completion

    admission = gate.snapshot() | dict(uncertain_calls=gate.uncertain_calls)
    assert admission["failed_calls"] == gate.uncertain_calls == 1
    assert not provider_failure_blocks_completion(admission, complete=True)
    assert provider_failure_blocks_completion(admission, complete=False)
    restarted = RoleProviderConcurrency(
        1,
        requests_per_second=4,
        scheduler_policy=V2_POLICY["provider_scheduler"],
        resilience_directory=tmp_path / "events",
    )
    assert restarted.uncertain_calls == 1


@pytest.mark.parametrize(
    "failed,uncertain,deferred,circuit",
    [(1, 0, 0, False), (2, 2, 0, False), (3, 0, 1, True), (1, 1, 1, False)],
)
def test_repeated_unknown_and_circuit_failures_stay_partial(failed, uncertain, deferred, circuit):
    from evaluation.hosted_r108 import provider_failure_blocks_completion

    assert provider_failure_blocks_completion(
        dict(
            failed_calls=failed,
            uncertain_calls=uncertain,
            circuit_deferred=deferred,
            circuit_open=circuit,
        ),
        complete=True,
    )


def test_recovered_uncertainty_does_not_mask_a_different_failure():
    from evaluation.hosted_r108 import provider_failure_blocks_completion

    assert provider_failure_blocks_completion(
        dict(failed_calls=2, uncertain_calls=1, circuit_deferred=0, circuit_open=False),
        complete=True,
        recovered=1,
    )


def test_scheduler_does_not_call_never_sent_or_unclassified_errors_uncertain(tmp_path):
    from proofops.adapters.local.openai_connections import OpenAIConnectNotSent
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    gate = RoleProviderConcurrency(1, resilience_directory=tmp_path)
    for error in (OpenAIConnectNotSent({}), ValueError("unclassified")):
        with pytest.raises(type(error)), gate.attempt("extract"):
            raise error
    assert gate.snapshot()["failed_calls"] == 2
    assert gate.uncertain_calls == 0
