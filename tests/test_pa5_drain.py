"""Durable admission fence, restart recovery and bounded operator waiting (no providers)."""

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import RUN_LEASE_SECONDS, HostedError, HostedStore

from tests.test_hosted_public import actor, login, pdf, uploaded
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def admitted(store, auth, key):
    doc = uploaded(store, auth)
    return doc, store.create_run(auth, doc["document_id"], None, key, now=time.time())


def test_drain_persists_blocks_new_admission_and_claim_but_preserves_retries(settings):
    store = HostedStore(settings)
    auth = actor(store)
    doc, run = admitted(store, auth, "pa5-existing-run-key")
    budget = store.budget_totals()
    assert store.drain(now=time.time())["maintenance"]
    restarted = HostedStore(settings)
    assert restarted.control_state(now=time.time())["queued"] == 1
    assert restarted.claim(now=time.time()) is None
    assert (
        restarted.create_run(
            auth, doc["document_id"], None, "pa5-existing-run-key", now=time.time()
        )["run_id"]
        == run["run_id"]
    )
    with pytest.raises(HostedError, match="MAINTENANCE") as error:
        restarted.create_run(auth, doc["document_id"], None, "pa5-new-run-key-01", now=time.time())
    assert error.value.status == 503
    assert restarted.budget_totals() == budget
    restarted.resume(now=time.time())
    assert restarted.claim(now=time.time())["run_id"] == run["run_id"]


def test_running_work_can_finish_during_drain_and_queued_work_waits(settings):
    store = HostedStore(settings)
    auth = actor(store)
    _, first = admitted(store, auth, "pa5-running-run-key")
    job = store.claim(now=time.time())
    _, queued = admitted(store, auth, "pa5-queued-run-key")
    store.drain(now=time.time())
    store.renew_lease(job, now=time.time())
    assert store.claim(now=time.time()) is None
    store.finish(job, "partial_blocked", now=time.time())
    state = store.control_state(now=time.time())
    assert (state["running"], state["queued"]) == (0, 1)
    assert store.get_run(auth.tenant_id, first["run_id"])["status"] == "partial_blocked"
    store.resume(now=time.time())
    assert store.claim(now=time.time())["run_id"] == queued["run_id"]


def test_runtime_and_api_explain_maintenance_without_mutating_existing_runs(settings):
    store = HostedStore(settings)
    client, headers, _, _ = login(create_hosted_app(settings), store)
    doc = client.post(
        "/v1/documents",
        content=pdf(),
        headers=headers
        | {"Content-Type": "application/pdf", "Idempotency-Key": "pa5-http-upload-key"},
    ).json()
    store.drain(now=time.time())
    runtime = client.get("/v1/runtime").json()
    assert runtime["maintenance"] and not runtime["accept_new_runs"]
    assert "점검" in runtime["maintenance_message"]
    response = client.post(
        "/v1/runs",
        json={"document_id": doc["document_id"], "selected_pages": [1, 2]},
        headers=headers | {"Idempotency-Key": "pa5-http-run-key"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MAINTENANCE"
    assert "점검" in response.json()["error"]["message"]
    assert response.headers["Retry-After"] == "60"
    store.resume(now=time.time())
    disabled = create_hosted_app(replace(settings, accept_runs=False))
    from fastapi.testclient import TestClient

    assert not TestClient(disabled).get("/v1/runtime").json()["accept_new_runs"]


def test_wait_idle_is_bounded_and_preserves_queued_work(settings):
    from scripts.hosted_control import wait_idle

    store = HostedStore(settings)
    auth = actor(store)
    _, run = admitted(store, auth, "pa5-wait-run-key")
    job = store.claim(now=time.time())
    store.drain(now=time.time())
    assert wait_idle(store, timeout=0)["status"] == "timeout"
    assert store.get_run(auth.tenant_id, run["run_id"])["status"] == "running"
    store.finish(job, "partial_blocked", now=time.time())
    assert wait_idle(store, timeout=0)["status"] == "idle"


def test_wait_idle_observes_completion_with_monotonic_deadline(settings):
    from scripts.hosted_control import wait_idle

    store = HostedStore(settings)
    auth = actor(store)
    admitted(store, auth, "pa5-wait-later-key")
    job = store.claim(now=time.time())
    store.drain(now=time.time())
    slept = []

    def finish_after_sleep(seconds):
        slept.append(seconds)
        store.finish(job, "partial_blocked", now=time.time())

    assert (
        wait_idle(store, timeout=2, clock=lambda: 10, sleep=finish_after_sleep)["status"] == "idle"
    )
    assert slept == [1]


def test_operator_cli_persists_controls_and_distinguishes_busy_timeout(settings):
    store = HostedStore(settings)
    auth = actor(store)
    admitted(store, auth, "pa5-cli-running-key")
    store.claim(now=time.time())
    env = os.environ | {
        "APP_ENV": "hosted",
        "MODEL_ADAPTER": "disabled",
        "LIVE_DISABLED": "true",
        "HOSTED_DATA_DIR": str(settings.root),
        "APP_ORIGIN": settings.origin,
        "HOSTED_SESSION_SECRET": settings.secret,
        "HOSTED_EVENT_ID": settings.event_id,
        "ANALYSIS_BACKEND": "r108",
        "R108_ACCEPT_NEW_RUNS": "true",
    }

    def invoke(*args):
        return subprocess.run(
            [sys.executable, "scripts/hosted_control.py", *args],
            cwd=Path(__file__).parents[1],
            env=env,
            capture_output=True,
            text=True,
        )

    drained = invoke("drain")
    assert drained.returncode == 0 and json.loads(drained.stdout)["maintenance"]
    busy = invoke("wait-idle", "--timeout", "0")
    assert busy.returncode == 3 and json.loads(busy.stdout)["running"] == 1
    invalid = invoke("wait-idle", "--timeout", "-1")
    assert invalid.returncode == 2
    assert store.control_state(now=time.time())["maintenance"]
    resumed = invoke("resume")
    assert resumed.returncode == 0 and not json.loads(resumed.stdout)["maintenance"]


@pytest.mark.parametrize("dispatched", [False, True])
def test_restart_lease_recovery_reaps_even_when_drained(settings, dispatched):
    store = HostedStore(settings)
    auth = actor(store)
    _, run = admitted(store, auth, "pa5-orphan-run-key")
    now = time.time()
    job = store.claim(now=now)
    if dispatched:
        store.dispatch(
            job,
            "fake",
            "pa5-call",
            "a" * 64,
            Decimal(".2"),
            lambda request: request | {"actual_usd": ".1"},
            now=now,
        )
    store.drain(now=now)
    restarted = HostedStore(settings)
    restarted.maintain(now=now + RUN_LEASE_SECONDS + 1)
    state = restarted.get_run(auth.tenant_id, run["run_id"])
    assert state["status"] == ("accounting_pending" if dispatched else "failed")
    assert state["error_code"] == ("LEASE_EXPIRED" if dispatched else "LEASE_EXPIRED_NO_DISPATCH")
    assert "서버" in state["error_message"]
    assert state["provider_error_code"] is None
    assert restarted.budget_totals()["event_reserved_usd"] == (
        "0.500000" if dispatched else "0.000000"
    )
    assert restarted.claim(now=now + RUN_LEASE_SECONDS + 2) is None
    with pytest.raises(HostedError, match="LEASE_LOST"):
        restarted.renew_lease(job, now=now + RUN_LEASE_SECONDS + 2)
