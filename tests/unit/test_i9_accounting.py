"""I9 hosted reservations and denial publication retain both money fences."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
from proofops.application.analysis_profile import FINALS_I9_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_store import HostedError

from tests.test_t1_403_retry import costs, setup, wire


def test_hosted_one_dollar_envelope_reserves_16_without_waiting(tmp_path, monkeypatch):
    """The broker denies over-budget work; it has no reservation polling queue."""
    store, _, job, _, _ = setup(tmp_path, monkeypatch, cap="1")
    store.dispatch(
        job,
        "upstage-parse",
        "settled-parsing",
        "a" * 64,
        Decimal(".824"),
        lambda request: request | dict(actual_usd=".824"),
        now=time.time(),
    )
    ready = threading.Barrier(17)
    release = threading.Event()

    def transport(request):
        ready.wait(timeout=10)
        assert release.wait(timeout=10)
        return request | dict(actual_usd=".0003")

    with ThreadPoolExecutor(16) as pool:
        futures = [
            pool.submit(
                store.dispatch,
                job,
                "openai",
                f"parallel-{i}",
                "b" * 64,
                Decimal(".011"),
                transport,
                now=time.time(),
                allow_model_partial=True,
            )
            for i in range(16)
        ]
        try:
            ready.wait(timeout=10)
            with store.transaction() as db:
                total = db.execute(
                    "SELECT sum(CASE WHEN status='settled' THEN actual ELSE bound END) "
                    "FROM deletion.costs WHERE run_id=?",
                    (job["run_id"],),
                ).fetchone()[0]
            assert total == 1_000_000
            with pytest.raises(HostedError, match="BUDGET_EXCEEDED"):
                store.dispatch(
                    job,
                    "openai",
                    "overflow",
                    "c" * 64,
                    Decimal(".011"),
                    transport,
                    now=time.time(),
                    allow_model_partial=True,
                )
        finally:
            release.set()
        assert all(future.result()["actual_usd"] == ".0003" for future in futures)


def test_v9_denial_circuit_and_partial_publication_keep_uncertain_cost(tmp_path, monkeypatch):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_I9_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_I9_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(
        16, requests_per_second=8, resilience_directory=tmp_path / "events"
    )
    gate.bind(probe)
    calls = wire(monkeypatch, iter([(403, b"", {})] * 3))
    for i in range(3):
        with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
            probe.complete("JSON", json.dumps(dict(i=i)), request_id=f"failed-{i}", json_mode=True)
    with pytest.raises(ValueError, match="^PROVIDER_CIRCUIT_OPEN$"):
        probe.complete("JSON", "{}", request_id="unsent", json_mode=True)
    assert len(calls) == 3
    assert all(row[1] == "accounting_pending" and row[2] == 11_000 for row in costs(store))
    state = tmp_path / "publication"
    state.mkdir()
    (state / "outcome.json").write_text(
        json.dumps(
            dict(
                status="partial_blocked",
                reason="PROVIDER_PROCESSING_FAILED",
                provider_failures=dict(total=3),
            )
        )
    )
    store.publish_analysis(job, state, "partial_blocked", "PROVIDER_PROCESSING_FAILED")
    result = store.get_result(auth.tenant_id, job["run_id"])
    assert result["pipeline"]["provider_failures"]["total"] == 3
    assert sum(Decimal(row[2]) for row in costs(store)) == 33_000
