"""HF8: one normalized provider failure must not stop unrelated preliminary work."""

import json
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.application.provider_resilience import POLICY
from proofops_api import hosted_sqlite

from tests.test_hosted_hf7 import configured
from tests.unit.test_openai_luna import response


def test_request_failure_is_a_hold_without_stopping_sibling_requests(tmp_path, monkeypatch):
    from tests.integration.test_upstage_preliminary_transport import configured as preliminary

    transport, probe, calls, request, *_ = preliminary(tmp_path, monkeypatch)
    probe.provider_resilience = POLICY
    complete = probe.complete
    failed = []

    def failure(*args, **kwargs):
        failed.append(kwargs["request_id"])
        raise ValueError("OPENAI_REQUEST_FAILED")

    monkeypatch.setattr(probe, "complete", failure)
    result = transport.invoke(request)
    assert result.usage.error_code == "PROVIDER_PROCESSING_FAILED"
    assert not list(transport._receipts.glob("transport-stop*.json"))
    retained = (transport._receipts / request["request_id"] / "response.json").read_bytes()
    with pytest.raises(ValueError, match="TAGGING_RECEIPT_EXISTS"):
        transport.invoke(request)
    assert failed == [request["request_id"]]
    assert (transport._receipts / request["request_id"] / "response.json").read_bytes() == retained
    monkeypatch.setattr(probe, "complete", complete)
    result = transport.invoke(request | dict(request_id=str(uuid4())))
    assert result.usage.status == "succeeded" and len(calls) == 1


@pytest.mark.parametrize("error_code", ["OPENAI_HTTP_429", "BUDGET_EXHAUSTED"])
def test_terminal_transport_stops_are_preserved(tmp_path, monkeypatch, error_code):
    from tests.integration.test_upstage_preliminary_transport import configured as preliminary

    transport, probe, calls, request, *_ = preliminary(tmp_path, monkeypatch)
    probe.provider_resilience = POLICY

    def failure(*args, **kwargs):
        raise ValueError(error_code)

    monkeypatch.setattr(probe, "complete", failure)
    assert transport.invoke(request).usage.error_code == error_code
    assert transport.invoke(request | dict(request_id=str(uuid4()))).usage.error_code == (
        "UPSTREAM_UNAVAILABLE"
    )
    assert calls == []


def test_reservation_failure_retains_original_diagnostic_without_cost_or_retry(
    tmp_path, monkeypatch
):
    store, auth, job, probe = configured(tmp_path, monkeypatch)
    transaction = store.transaction
    failed = []
    calls = []

    @contextmanager
    def reserve_failure(**kwargs):
        if kwargs.get("operation") == "dispatch_reserve" and not failed:
            failed.append(1)
            error = sqlite3.OperationalError("private SQL and credentials must not be copied")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error
        with transaction(**kwargs) as db:
            yield db

    def post(body):
        calls.append(body)
        return response()

    monkeypatch.setattr(store, "transaction", reserve_failure)
    probe.post = post
    with pytest.raises(ValueError, match="^OPENAI_REQUEST_FAILED$"):
        probe.complete("JSON", "{}", request_id="failed", json_mode=True)
    assert calls == []
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0
        assert tuple(db.execute("SELECT status,fence FROM runs").fetchone()) == (
            "running",
            job["fence"],
        )
    (path,) = list((probe.ledger.parent / "dispatch-failures").glob("*.json"))
    diagnostic = json.loads(path.read_text())
    assert diagnostic["phase"] == "reservation"
    assert diagnostic["exception_type"] == "OperationalError"
    assert diagnostic["sqlite_errorcode"] == sqlite3.SQLITE_BUSY
    assert "reserve_failure" in diagnostic["location"]
    assert "private SQL" not in path.read_text() and path.stat().st_mode & 0o077 == 0
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("SELECT state FROM probe_transport_attempts").fetchone()[0] == "unknown"
        assert db.execute("SELECT committed,receipt FROM probe_calls").fetchone() == ("0.02", None)
    with pytest.raises(ValueError, match="DUPLICATE_PROBE_REQUEST"):
        probe.complete("JSON", "{}", request_id="failed", json_mode=True)
    assert probe.complete("JSON", '{"next":1}', request_id="next", json_mode=True)["schema_valid"]
    assert len(calls) == 1
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"


def test_probe_failure_outside_broker_keeps_diagnostic(tmp_path, monkeypatch):
    _, _, _, probe = configured(tmp_path, monkeypatch)

    @contextmanager
    def failed_admission():
        raise ValueError("private scheduler detail")
        yield

    monkeypatch.setattr(probe, "physical_attempt_scope", failed_admission)
    with pytest.raises(ValueError, match="^OPENAI_REQUEST_FAILED$"):
        probe.complete("JSON", "{}", request_id="queue-failure", json_mode=True)
    (path,) = list((probe.ledger.parent / "dispatch-failures").glob("*.json"))
    diagnostic = json.loads(path.read_text())
    assert diagnostic["phase"] == "probe_attempt"
    assert diagnostic["exception_type"] == "ValueError"
    assert "failed_admission" in diagnostic["location"]
    assert "private scheduler detail" not in path.read_text()


def test_skipped_database_diagnostic_explains_size_cap(tmp_path, monkeypatch):
    from proofops_api import hosted_diagnostics

    from tests.test_hosted_hf6 import captured, seed

    store, _, job, _ = configured(tmp_path, monkeypatch)
    directory = store.document_dir(job["tenant_id"], job["document_id"])

    def full(*args):
        error = sqlite3.OperationalError("private database path")
        error.sqlite_errorcode = sqlite3.SQLITE_FULL
        raise error

    monkeypatch.setattr(hosted_diagnostics, "_database", full)
    with hosted_diagnostics.analysis_workspace(store, job, directory) as workspace:
        state = seed(workspace)
        (state / "outcome.json").write_text('{"status":"partial_blocked"}')
    (saved,) = captured(store)
    manifest = json.loads((saved / "manifest.json").read_text())
    assert manifest["skipped"] == 1
    (failure,) = manifest["database_failures"]
    assert failure["file"] == "state.sqlite3"
    assert failure["sqlite_errorcode"] == sqlite3.SQLITE_FULL
    assert failure["exception_type"] == "OperationalError"
    assert "private database path" not in json.dumps(manifest)


@pytest.mark.parametrize("boundary", ["acquire", "commit"])
@pytest.mark.parametrize("release_after", [15, 29, 31])
def test_reservation_busy_has_bounded_wait_without_replay(
    tmp_path, monkeypatch, boundary, release_after
):
    store, _, job, _ = configured(tmp_path, monkeypatch)
    clock = [0.0]
    armed = [False]
    calls, writes, errors = [], [], []
    connect = sqlite3.connect

    def sleep(seconds):
        clock[0] += seconds

    def busy():
        if armed[0] and clock[0] < release_after:
            error = sqlite3.OperationalError("private SQL and credentials")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            errors.append(error)
            raise error

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if boundary == "acquire" and sql == "BEGIN IMMEDIATE":
                busy()
            if sql.startswith("INSERT INTO deletion.costs"):
                writes.append(sql)
            return super().execute(sql, *args, **kwargs)

        def commit(self):
            if boundary == "commit":
                busy()
            return super().commit()

    monkeypatch.setattr(
        hosted_sqlite, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)
    )
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=Connection))

    def transport(request):
        calls.append(request)
        armed[0] = False
        return request | dict(actual_usd=".001")

    def dispatch():
        return store.dispatch(
            job,
            "openai",
            "reserve-busy",
            "a" * 64,
            Decimal(".011"),
            transport,
            now=time.time(),
            diagnostic_context=dict(state=tmp_path),
        )

    with store.transaction(readonly=True) as db:
        before_run = tuple(db.execute("SELECT * FROM runs").fetchone())
        before_spend = tuple(db.execute("SELECT * FROM deletion.spend").fetchone())
    armed[0] = True
    if release_after > 30:
        with pytest.raises(sqlite3.OperationalError) as caught:
            dispatch()
        assert caught.value is errors[-1]  # Propagate the original exhausted BUSY.
        assert clock[0] == 30 and calls == []
        armed[0] = False
        with store.transaction(readonly=True) as db:
            assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0
            assert tuple(db.execute("SELECT * FROM runs").fetchone()) == before_run
            assert tuple(db.execute("SELECT * FROM deletion.spend").fetchone()) == before_spend
        path = tmp_path / "dispatch-failures/reserve-busy.json"
        diagnostic = json.loads(path.read_text())
        assert diagnostic["phase"] == "reservation"
        assert diagnostic["exception_type"] == "OperationalError"
        assert diagnostic["sqlite_errorcode"] == sqlite3.SQLITE_BUSY
        assert "busy" in diagnostic["location"]
        assert "private SQL" not in path.read_text() and path.stat().st_mode & 0o077 == 0
        assert len(writes) == (1 if boundary == "commit" else 0)
    else:
        assert dispatch()["actual_usd"] == ".001"
        assert release_after <= clock[0] < 30
        assert len(calls) == len(writes) == 1
        with store.transaction(readonly=True) as db:
            assert tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone()) == (
                1000,
                "settled",
            )
            assert tuple(db.execute("SELECT * FROM runs").fetchone()) == before_run
            assert tuple(db.execute("SELECT * FROM deletion.spend").fetchone()) == before_spend
        assert not (tmp_path / "dispatch-failures").exists()
    store.renew_lease(job, now=time.time())
