"""PI1 intake, FIFO, per-user processing and money guards; no provider network."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import pytest
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import HostedError, HostedSettings, HostedStore, digest

from tests.test_hosted_public import actor, login, pdf, uploaded
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def enqueue(store, auth, index):
    doc = store.upload(auth, pdf(), f"pi1-upload-key-{index:04}", now=time.time())
    return store.create_run(
        auth, doc["document_id"], [1], f"pi1-run-key-{index:04}", now=time.time()
    )


def test_one_invitation_five_reports_fifo_complete(settings, monkeypatch, tmp_path):
    settings = replace(settings, user_active_runs=5)
    store = HostedStore(settings)
    app = create_hosted_app(settings)
    client, headers, tenant, _ = login(app, store)
    started, release = threading.Event(), threading.Event()
    order = []

    def snapshot(source, tenant_id, pages):
        return json.dumps(
            dict(
                tenant_id=tenant_id,
                page_map=pages,
                source_hashes={"outcome.json": digest((source / "outcome.json").read_bytes())},
                result=dict(
                    schema="r108-hosted-result-v1",
                    claims=[],
                    reviews=[],
                    hold_reasons=[],
                    page_map=pages,
                    pipeline={"status": "completed"},
                ),
            )
        ).encode()

    monkeypatch.setattr("proofops_api.hosted_results.result_snapshot", snapshot)

    def analysis(control, job, prepared):
        assert prepared.is_file()
        order.append(job["run_id"])
        control.update_progress(job, "extract", 30)
        if len(order) == 1:
            started.set()
            assert release.wait(5)
        control.dispatch(
            job,
            "fake",
            "mock-call",
            "a" * 64,
            Decimal(".2"),
            lambda request: request | {"actual_usd": ".1"},
            now=time.time(),
        )
        state = tmp_path / job["run_id"]
        state.mkdir()
        (state / "outcome.json").write_text('{"status":"completed","provider_calls":0}')
        control.publish_analysis(job, state, "completed", None)

    runs = []
    with ThreadPoolExecutor(1) as pool:
        try:
            for i in range(5):
                response = client.post(
                    "/v1/documents",
                    content=pdf(),
                    headers=headers
                    | {
                        "Content-Type": "application/pdf",
                        "Idempotency-Key": f"pi1-http-upload-{i}",
                    },
                )
                assert response.status_code == 201, response.text
                response = client.post(
                    "/v1/runs",
                    json={"document_id": response.json()["document_id"], "selected_pages": [1]},
                    headers=headers | {"Idempotency-Key": f"pi1-http-run-key-{i}"},
                )
                assert response.status_code == 202, response.text
                runs.append(response.json())
                if i == 0:
                    future = pool.submit(store.tick, now=time.time(), analysis=analysis)
                    assert started.wait(3)
            states = [client.get(run["status_url"]).json() for run in runs]
            assert [r["status"] for r in states] == ["running"] + ["queued"] * 4
            assert [r["queue_position"] for r in states[1:]] == [1, 2, 3, 4]
            assert states[0]["user_active_count"] == 5
            assert states[0]["user_processing_count"] == 1
            assert store.claim(now=time.time()) is None
            assert store.budget_totals()["event_reserved_usd"] == "2.500000"
        finally:
            release.set()
        assert future.result(5)["status"] == "completed"
    for expected in runs[1:]:
        done = store.tick(now=time.time(), analysis=analysis)
        assert done["run_id"] == expected["run_id"] and done["status"] == "completed"
    assert order == [r["run_id"] for r in runs]
    assert all(
        client.get(r["result_url"] or r["status_url"] + "/result").status_code == 200 for r in runs
    )
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    outsider, other_headers, _, _ = login(app, store)
    for run in runs:
        assert outsider.get(run["status_url"]).status_code == 404
        assert outsider.get(run["status_url"] + "/result").status_code == 404
        assert (
            outsider.post(
                "/v1/runs",
                json={"document_id": run["document_id"], "selected_pages": [1]},
                headers=other_headers | {"Idempotency-Key": "pi1-cross-tenant-run"},
            ).status_code
            == 404
        )
    assert client.get("/v1/session").json()["tenant_id"] == tenant
    runtime = client.get("/v1/runtime").json()["limits"]
    assert runtime["user_active_runs"] == 5 and runtime["daily_runs"] == 10


@pytest.mark.parametrize("user_limit,expected", [(1, 1), (5, 2)])
def test_excess_user_work_queues_and_other_users_can_use_slot(settings, user_limit, expected):
    store = HostedStore(replace(settings, max_active_runs=2, user_active_runs=user_limit))
    auth = actor(store)
    first, second = [enqueue(store, auth, i) for i in range(2)]
    assert store.claim(now=time.time())["run_id"] == first["run_id"]
    job = store.claim(now=time.time())
    if expected == 1:
        assert job is None
        assert store.get_run(auth.tenant_id, second["run_id"])["status"] == "queued"
        other = actor(store)
        third = enqueue(store, other, 2)
        assert store.claim(now=time.time())["run_id"] == third["run_id"]
    else:
        assert job["run_id"] == second["run_id"]
    assert store.claim(now=time.time()) is None


def test_same_user_concurrent_intake_preserves_eight_queue_cap_and_idempotency(settings):
    store = HostedStore(replace(settings, user_daily_runs=20, daily_runs=20, run_usd=Decimal(".1")))
    auth = actor(store)
    doc = uploaded(store, auth)

    def request(i):
        try:
            return store.create_run(
                auth, doc["document_id"], [1], f"pi1-race-key-{i:04}", now=time.time()
            )
        except HostedError as error:
            return error.code

    with ThreadPoolExecutor(10) as pool:
        responses = list(pool.map(request, range(10)))
    accepted = [r for r in responses if isinstance(r, dict)]
    assert len(accepted) == 8 and responses.count("QUEUE_FULL") == 2
    index = next(i for i, r in enumerate(responses) if isinstance(r, dict))
    assert request(index)["run_id"] == responses[index]["run_id"]
    assert store.budget_totals()["event_reserved_usd"] == "0.800000"


def test_accounting_pending_counts_but_does_not_block_next_user_run(settings):
    store = HostedStore(settings)  # default user processing limit one
    auth = actor(store)
    first = enqueue(store, auth, 0)
    job = store.claim(now=time.time())

    def timeout(_):
        raise TimeoutError("mock uncertain response")

    with pytest.raises(TimeoutError):
        store.dispatch(job, "fake", "uncertain", "a" * 64, Decimal(".2"), timeout, now=time.time())
    second = enqueue(store, auth, 1)
    pending = store.get_run(auth.tenant_id, first["run_id"])
    assert pending["status"] == "accounting_pending"
    assert pending["user_active_count"] == 2 and pending["user_processing_count"] == 0
    next_job = store.claim(now=time.time())
    assert next_job["run_id"] == second["run_id"]
    store.finish(next_job, "partial_blocked", now=time.time())
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    with store.transaction() as db:
        assert tuple(db.execute("SELECT status,bound,actual FROM deletion.costs").fetchone()) == (
            "accounting_pending",
            200000,
            None,
        )
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.dispatch(job, "fake", "new-call", "b" * 64, Decimal(".1"), timeout, now=time.time())


def test_user_slot_limit_spans_tenants_but_does_not_block_other_users(settings):
    store = HostedStore(replace(settings, max_active_runs=2))
    first_auth = actor(store)
    same_user = actor(store, user=first_auth.user_sub)
    first = enqueue(store, first_auth, 0)
    second = enqueue(store, same_user, 1)
    assert store.claim(now=time.time())["run_id"] == first["run_id"]
    assert store.claim(now=time.time()) is None
    with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
        store.get_run(same_user.tenant_id, first["run_id"])
    third = enqueue(store, actor(store), 2)
    assert store.claim(now=time.time())["run_id"] == third["run_id"]
    assert store.get_run(same_user.tenant_id, second["run_id"])["status"] == "queued"


def test_same_user_same_document_exclusion_with_finals_user_limit(settings):
    store = HostedStore(replace(settings, max_active_runs=2, user_active_runs=5))
    auth = actor(store)
    doc = uploaded(store, auth)
    for i in range(2):
        store.create_run(auth, doc["document_id"], [1], f"pi1-same-document-{i}", now=time.time())
    first = store.claim(now=time.time())
    assert store.claim(now=time.time()) is None
    store.finish(first, "partial_blocked", now=time.time())
    assert store.claim(now=time.time())["document_id"] == doc["document_id"]


@pytest.mark.parametrize("field", ["day_usd", "event_usd"])
def test_queue_admission_cannot_bypass_money_cap(settings, field):
    store = HostedStore(replace(settings, **{field: Decimal("1")}))
    auth = actor(store)
    enqueue(store, auth, 0)
    enqueue(store, auth, 1)
    with pytest.raises(HostedError, match="BUDGET_EXCEEDED"):
        enqueue(store, auth, 2)
    assert store.budget_totals()["event_reserved_usd"] == "1.000000"


@pytest.mark.parametrize("limit", [3, 10, 11])
def test_global_daily_limit_configurable_without_ignoring_settled_runs(settings, limit):
    store = HostedStore(replace(settings, daily_runs=limit, user_daily_runs=20))
    auth = actor(store)
    for i in range(limit):
        enqueue(store, auth, i)
        store.finish(store.claim(now=time.time()), "partial_blocked", now=time.time())
    with pytest.raises(HostedError, match="DAILY_RUN_LIMIT"):
        enqueue(store, actor(store), limit)
    assert store.budget_totals()["event_reserved_usd"] == "0.000000"


@pytest.mark.parametrize("field", ["user_active_runs", "daily_runs"])
@pytest.mark.parametrize("value", [0, -1, True, "5"])
def test_new_limits_fail_closed(settings, field, value):
    with pytest.raises(ValueError):
        replace(settings, **{field: value})


def test_env_defaults_and_overrides(settings):
    env = dict(
        APP_ENV="hosted",
        HOSTED_DATA_DIR=str(settings.root),
        APP_ORIGIN=settings.origin,
        HOSTED_SESSION_SECRET=settings.secret,
        HOSTED_EVENT_ID=settings.event_id,
    )
    default = HostedSettings.from_env(env)
    assert (default.user_active_runs, default.daily_runs) == (1, 10)
    finals = HostedSettings.from_env(
        env | {"HOSTED_USER_ACTIVE_RUNS": "5", "HOSTED_DAILY_RUNS": "12"}
    )
    assert (finals.user_active_runs, finals.daily_runs) == (5, 12)
