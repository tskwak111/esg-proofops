"""Two hosted subprocess slots retain global budget and document fences."""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

import pytest
from proofops_api.hosted_store import HostedError, HostedSettings, HostedStore

from tests.test_hosted_public import actor, uploaded
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def test_claim_two_slots_and_leave_three_queued(settings):
    store = HostedStore(replace(settings, max_active_runs=2))
    jobs = []
    for _ in range(5):
        auth = actor(store)
        doc = uploaded(store, auth)
        jobs.append(
            store.create_run(auth, doc["document_id"], None, "pa1-queue-0000001", now=time.time())
        )
    with ThreadPoolExecutor(5) as pool:
        claims = list(pool.map(lambda _: store.claim(now=time.time()), range(5)))
    active = [c for c in claims if c]
    assert len(active) == 2
    assert len({c["run_id"] for c in active}) == 2
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM runs WHERE status='queued'").fetchone()[0] == 3
    assert store.budget_totals()["event_reserved_usd"] == "2.500000"


def test_two_slots_never_claim_same_document(settings):
    store = HostedStore(replace(settings, max_active_runs=2))
    auth = actor(store)
    other = actor(store, tenant=auth.tenant_id)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "pa1-first-000001", now=time.time())
    store.create_run(other, doc["document_id"], None, "pa1-second-00001", now=time.time())
    assert store.claim(now=time.time())
    assert store.claim(now=time.time()) is None


@pytest.mark.parametrize("value", [0, 3, True, "2"])
def test_concurrency_ceiling(settings, value):
    with pytest.raises(ValueError, match="HOSTED_RUN_CONCURRENCY_INVALID"):
        replace(settings, max_active_runs=value)


def test_concurrency_env_is_opt_in(settings):
    env = dict(
        APP_ENV="hosted",
        HOSTED_DATA_DIR=str(settings.root),
        APP_ORIGIN=settings.origin,
        HOSTED_SESSION_SECRET=settings.secret,
        HOSTED_EVENT_ID=settings.event_id,
    )
    assert HostedSettings.from_env(env).max_active_runs == 1
    assert HostedSettings.from_env(env | {"HOSTED_MAX_ACTIVE_RUNS": "2"}).max_active_runs == 2


def test_two_runs_parallel_reservations_cannot_overbook(settings):
    store = HostedStore(replace(settings, max_active_runs=2, run_usd=Decimal(".022")))
    for _ in range(2):
        auth = actor(store)
        store.create_run(
            auth, uploaded(store, auth)["document_id"], None, "pa1-budget-00001", now=time.time()
        )
    jobs = [store.claim(now=time.time()) for _ in range(2)]
    release = threading.Event()
    reserved = threading.Event()
    rejected = threading.Event()
    lock = threading.Lock()
    sent = []
    denied = []

    def transport(request):
        with lock:
            sent.append(request)
            if len(sent) == 4:
                reserved.set()
        assert release.wait(5)
        return request | dict(actual_usd="0.001")

    def dispatch(index):
        try:
            return store.dispatch(
                jobs[index % 2],
                "openai",
                f"call-{index}",
                "a" * 64,
                Decimal(".011"),
                transport,
                now=time.time(),
            )
        except HostedError as error:
            with lock:
                denied.append(error.code)
                if len(denied) == 4:
                    rejected.set()
            return error.code

    with ThreadPoolExecutor(8) as pool:
        futures = [pool.submit(dispatch, n) for n in range(8)]
        try:
            assert reserved.wait(3)
            assert rejected.wait(3)
            assert store.budget_totals()["event_reserved_usd"] == "0.044000"
        finally:
            release.set()
        responses = [future.result(3) for future in futures]
    assert len(sent) == 4
    assert responses.count("BUDGET_EXCEEDED") == 4
    for job in jobs:
        store.renew_lease(job, now=time.time())


def test_memory_limit_reaps_analysis_session(settings, tmp_path, monkeypatch):
    from proofops_api import hosted_analysis

    store = HostedStore(replace(settings, max_active_runs=2))
    auth = actor(store)
    store.create_run(
        auth, uploaded(store, auth)["document_id"], None, "pa1-memory-00001", now=time.time()
    )
    job = store.claim(now=time.time())
    monkeypatch.setattr(hosted_analysis, "TWO_SLOT_MEMORY_BYTES", 1)
    with (tmp_path / "lock").open("a+b") as lock:
        with pytest.raises(HostedError, match="ANALYSIS_MEMORY_LIMIT"):
            hosted_analysis.run_analysis_process(
                [sys.executable, "-c", "import time;time.sleep(20)"], store, job, lock
            )


def test_worker_once_uses_both_slots(settings, monkeypatch):
    from scripts.hosted_control import worker_loop

    store = HostedStore(replace(settings, max_active_runs=2))
    barrier = threading.Barrier(2)
    monkeypatch.setattr(store, "maintain", lambda **k: None)
    monkeypatch.setattr(store, "tick", lambda **k: barrier.wait(timeout=3))
    assert sorted(worker_loop(store, once=True)) == [0, 1]
