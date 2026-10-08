"""P7 rejects quota failures without redelivery or losing money reservations."""

import time

import pytest
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_analysis import HostedLunaProbe
from proofops_api.hosted_store import HostedError, HostedStore

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import login
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


MESSAGE = "분석 서비스 한도 초과 — 운영자 확인 필요"


@pytest.mark.parametrize("code", ["OPENROUTER_HTTP_402", "OPENROUTER_HTTP_403"])
def test_quota_failure_is_terminal_retains_reservation_and_cannot_retry(settings, tmp_path, code):
    store, auth, job = job_setup(settings)
    calls = []

    def rejected(body):
        calls.append(body)
        raise ValueError(code)

    probe = HostedLunaProbe("fake-p7", tmp_path / "luna.db", store=store, job=job, post=rejected)
    with pytest.raises(ValueError, match=code):
        probe.complete("x", "{}", request_id="quota")
    run = store.get_run(auth.tenant_id, job["run_id"])
    assert run["status"] == "failed"
    assert run["error_code"] == code
    assert run["error_message"] == MESSAGE
    assert run["retryable"] is False
    assert run["result"] is None and run["result_url"] is None
    assert len(calls) == 1
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    with store.transaction() as db:
        cost = db.execute("SELECT status,bound,actual FROM deletion.costs").fetchone()
        assert tuple(cost) == ("accounting_pending", 11000, None)
    with pytest.raises(HostedError):
        probe._post(probe.request_body("x", "{}", request_id="retry"))
    restarted = HostedStore(settings)
    assert restarted.get_run(auth.tenant_id, job["run_id"])["error_code"] == code
    assert restarted.claim(now=time.time() + 1000) is None
    assert len(calls) == 1


@pytest.mark.parametrize("code", ["OPENROUTER_HTTP_402", "OPENROUTER_HTTP_403"])
def test_runtime_reports_observed_limit_only_without_provider_calls(settings, tmp_path, code):
    store, auth, job = job_setup(settings)
    probe = HostedLunaProbe(
        "fake-p7-secret",
        tmp_path / "luna.db",
        store=store,
        job=job,
        post=lambda body: (_ for _ in ()).throw(ValueError(code)),
    )
    with pytest.raises(ValueError):
        probe._post(probe.request_body("x", "{}", request_id="quota"))
    app = create_hosted_app(settings)
    client, _, _, _ = login(app, store, tenant=auth.tenant_id)
    for _ in range(2):
        response = client.get("/v1/runtime")
        data = response.json()
        assert data["analysis_profile"] == "r108-default"
        assert data["analysis_profile_options"] == ["r108-default", "r108-finals-candidate-v2"]
        assert data["provider_limits"]["openrouter"] == {
            "status": "blocked",
            "error_code": code,
            "remaining_usd": None,
            "source": "observed_http_failure",
            "retryable": False,
            "message": MESSAGE,
        }
        assert "fake-p7-secret" not in response.text
        assert "Authorization" not in response.text
    assert store.claim(now=time.time() + 1000) is None


def test_runtime_quota_unknown_is_not_reported_as_healthy(settings):
    app = create_hosted_app(settings)
    store = app.state.composition
    client, _, _, _ = login(app, store)
    limit = client.get("/v1/runtime").json()["provider_limits"]["openrouter"]
    assert limit["status"] == "unknown" and limit["remaining_usd"] is None
    assert limit["source"] == "not_queried" and limit["error_code"] is None


def test_cancelled_run_is_not_replaced_by_late_quota_failure(settings, tmp_path):
    store, auth, job = job_setup(settings)

    def cancelled(body):
        store.cancel(auth, job["run_id"], now=time.time())
        raise ValueError("OPENROUTER_HTTP_403")

    probe = HostedLunaProbe("fake-p7", tmp_path / "luna.db", store=store, job=job, post=cancelled)
    with pytest.raises(ValueError, match="OPENROUTER_HTTP_403"):
        probe._post(probe.request_body("x", "{}", request_id="late"))
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "cancelled"
    assert store.claim(now=time.time() + 1000) is None


def test_tick_keeps_explicit_quota_error(settings):
    from tests.test_hosted_public import actor, uploaded

    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "quota-tick-00001", now=time.time())

    def rejected(store, job, prepared):
        raise ValueError("OPENROUTER_HTTP_403")

    run = store.tick(now=time.time(), analysis=rejected)
    assert run["status"] == "failed" and run["error_code"] == "OPENROUTER_HTTP_403"
    assert run["error_message"] == MESSAGE
