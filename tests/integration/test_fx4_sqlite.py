"""FX4: contention must not turn a settled preliminary response into a hold."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from proofops.adapters.local.openai import OpenAIProbe

from tests.unit.test_openai_luna import response


def test_response_settlement_survives_writer_without_resending(tmp_path):
    probe = OpenAIProbe("fake", tmp_path / "luna.sqlite3")
    locked = threading.Event()
    calls = []

    def hold():
        with sqlite3.connect(probe.ledger, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            locked.set()
            time.sleep(6)
            db.commit()

    with ThreadPoolExecutor(1) as pool:

        def post(body):
            calls.append(body)
            pool.submit(hold)
            assert locked.wait(2)
            return response()

        probe._post = post
        result = probe.complete("JSON", "{}", request_id="preliminary-1", json_mode=True)
    assert result["schema_valid"] is True
    assert len(calls) == 1
    assert probe.summary()["unsettled_calls"] == 0


def test_usage_settlement_waits_without_duplicate_charge(tmp_path):
    from tests.acceptance.test_cost import CALL, RUN, TENANT, USAGE, reserve, seeded

    store = seeded(tmp_path / "state.sqlite3")
    assert reserve(store)
    with ThreadPoolExecutor(1) as pool:
        with sqlite3.connect(store.path, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            future = pool.submit(store.record_usage, CALL, USAGE, now=2)
            time.sleep(12)
            db.commit()
        receipt = future.result(timeout=3)
    assert store.record_usage(CALL, USAGE, now=3) == receipt
    assert len(store.ledger(TENANT, RUN)) == 1


def test_commit_retries_in_place_and_failure_rolls_back(tmp_path, monkeypatch):
    import pytest
    from proofops.adapters.local import sqlite_busy

    path = tmp_path / "state.sqlite3"
    with sqlite_busy.connection(path) as db:
        db.execute("CREATE TABLE items (value TEXT)")
    reader = sqlite3.connect(path, check_same_thread=False)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM items").fetchall()
    bodies = []

    def write():
        with sqlite_busy.connection(path) as db:
            db.execute("INSERT INTO items VALUES ('one')")
            bodies.append(1)

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(write)
        time.sleep(0.6)
        reader.rollback()
        future.result(timeout=3)
    reader.close()
    assert bodies == [1]
    with pytest.raises(sqlite3.OperationalError):
        with sqlite_busy.connection(path) as db:
            db.execute("INSERT INTO items VALUES ('rolled back')")
            db.execute("SELECT * FROM missing_private_table")
    with sqlite_busy.connection(path, readonly=True) as db:
        assert db.execute("SELECT * FROM items").fetchall() == [("one",)]


def test_retry_budget_and_non_lock_errors(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from proofops.adapters.local import sqlite_busy

    elapsed = [0.0]

    def sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(
        sqlite_busy, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=sleep)
    )
    for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR, None):
        elapsed[0] = 0
        attempts = []

        def fail():
            attempts.append(1)
            elapsed[0] += 0.25
            error = sqlite3.OperationalError("private secret")
            if code is not None:
                error.sqlite_errorcode = code
            raise error

        with pytest.raises(sqlite3.OperationalError):
            sqlite_busy.retry_busy(fail)
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            assert len(attempts) > 1 and 30 <= elapsed[0] <= 30.25
        else:
            assert attempts == [1]


def test_waiting_nonheartbeat_fence_cannot_accept_expired_lease(tmp_path):
    from tests.acceptance.test_jobs import MESSAGE, seeded

    store = seeded(tmp_path / "state.sqlite3")
    lease = store.claim_job(MESSAGE, owner="worker", now=100, lease_seconds=1)
    with ThreadPoolExecutor(1) as pool:
        with sqlite3.connect(store.path, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            future = pool.submit(store.can_call, lease, now=100)
            time.sleep(1.2)
            db.commit()
        assert future.result(timeout=3) is False


def test_operational_error_receipt_is_held_and_sanitized(tmp_path, monkeypatch):
    import json

    from tests.integration.test_local_tag_runner import TENANT
    from tests.integration.test_unattended_pipeline import setup

    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)

    def fail(*_):
        raise sqlite3.OperationalError("no such table: sk-private-token /private/customer.pdf")

    runner.preliminary = fail
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    envelope = runner.tags.load_snapshot(TENANT, run_id)
    claim = envelope["claims"][0]
    assert claim["reason"] == "PRELIMINARY_UNEXPECTED_OperationalError"
    assert claim["status"] == "failed" and claim["decision"] is None
    assert claim["sqlite_error"]["message_summary"] == "no such table: [redacted]"
    assert "private" not in json.dumps(envelope)


def test_preliminary_count_arrives_before_elements_and_terminal_count(tmp_path, monkeypatch):
    from tests.integration.test_local_tag_runner import TENANT
    from tests.integration.test_unattended_pipeline import setup

    service, run_id, runner, _, _ = setup(tmp_path, monkeypatch)
    events = []
    runner.claim_stage_progress = lambda claim, total, stage: events.append((claim, stage))
    runner.claim_progress = lambda claim, total: events.append((claim, "terminal"))
    invoke = runner.transport.invoke

    def observed(request):
        assert (request["claim_id"], "preliminary") in events
        assert (request["claim_id"], "terminal") not in events
        return invoke(request)

    runner.transport.invoke = observed
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    first = events[0][0]
    assert [stage for claim, stage in events if claim == first] == [
        "preliminary",
        "relation",
        "elements",
        "terminal",
    ]


def test_cache_registry_and_accounting_reads_wait_for_exclusive_writer(tmp_path):
    from proofops.adapters.local.model_response_cache import ModelResponseCache
    from proofops.adapters.local.tag_cache import SQLiteImmutableCacheClient
    from proofops.adapters.local.upstage import request_usage
    from proofops.application.registry import Registry

    path = tmp_path / "state.sqlite3"
    registry = Registry.sqlite(path)
    tags = SQLiteImmutableCacheClient(path)
    model_cache = ModelResponseCache(path)
    probe = OpenAIProbe("fake", path)
    calls = [
        lambda: tags.get("missing"),
        lambda: model_cache.claim("key", path, "claim-1"),
        registry._load,
        lambda: request_usage(path, ["missing"]),
        probe.summary,
    ]
    try:
        with ThreadPoolExecutor(len(calls)) as pool:
            with sqlite3.connect(path, isolation_level=None) as db:
                db.execute("BEGIN EXCLUSIVE")
                futures = [pool.submit(call) for call in calls]
                time.sleep(0.6)
                assert not any(f.done() for f in futures)
                db.commit()
            results = [f.result(timeout=4) for f in futures]
        assert results[:3] == [None, None, None]
        assert results[-1]["calls"] == 0
    finally:
        registry.close()
