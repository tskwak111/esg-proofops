"""Control stops retain their identity and settle only proven-unsent attempts."""

import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from proofops.adapters.local.openai_connections import OpenAIConnectNotSent, OpenAIControlNotSent
from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
from proofops.application.analysis_profile import V2_POLICY
from proofops.application.ports.jobs import LeaseLost
from proofops.domain.provenance import canonical_hash
from proofops_api import hosted_sqlite
from proofops_api.hosted_store import HostedError
from proofops_worker.consumer import TagHeartbeatFailed
from proofops_worker.tag_runner import _TagFenceLost

from tests.test_t1_403_retry import setup
from tests.unit.test_openai_luna import response


def configured(tmp_path, monkeypatch):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch)
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=V2_POLICY,
            analysis_profile_policy_sha256=canonical_hash(V2_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(1, scheduler_policy=V2_POLICY["provider_scheduler"])
    gate.bind(probe)
    return store, auth, job, probe


@pytest.mark.parametrize("signal", [TagHeartbeatFailed, _TagFenceLost, LeaseLost])
@pytest.mark.parametrize(
    "boundary", ["pacing", "connect", "request", "response", "post_pacing", "post"]
)
def test_control_stop_delivery_and_broker_fence(tmp_path, monkeypatch, signal, boundary):
    store, auth, job, probe = configured(tmp_path, monkeypatch)
    sent = []
    error = signal()

    def stop(*args, **kwargs):
        raise error

    class Connection:
        sock = None

        def connect(self):
            if boundary == "connect":
                stop()

        def request(self, *args, **kwargs):
            sent.append(1)
            if boundary == "request":
                stop()

        def getresponse(self):
            stop()

        def close(self):
            pass

    monkeypatch.setattr(probe.connection_pool, "take", lambda: (Connection(), "test", False))
    if boundary in {"pacing", "post_pacing"}:
        probe.http_transport_pacing = stop
    if boundary.startswith("post"):

        def post(body):
            sent.append(1)
            stop()

        probe.post = post

    with pytest.raises(signal) as caught:
        probe.complete("JSON", "{}", request_id="control-stop", json_mode=True)
    assert caught.value is error
    never_sent = boundary in {"pacing", "connect", "post_pacing"}
    assert len(sent) == (0 if never_sent else 1)
    with store.transaction(readonly=True) as db:
        row = tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone())
        run = tuple(db.execute("SELECT status,fence FROM runs").fetchone())
    assert row == ((0, "settled") if never_sent else (None, "accounting_pending"))
    assert run == (
        ("running", job["fence"]) if never_sent else ("accounting_pending", job["fence"] + 1)
    )
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("SELECT state FROM probe_transport_attempts").fetchone()[0] == (
            "never_sent" if never_sent else "unknown"
        )
        committed, receipt = db.execute("SELECT committed,receipt FROM probe_calls").fetchone()
    if never_sent:
        assert committed == "0" and '"dispatch_state": "never_sent"' in receipt
        store.renew_lease(job, now=time.time())
    else:
        assert receipt is None
        with pytest.raises(HostedError, match="LEASE_LOST"):
            store.renew_lease(job, now=time.time())


def test_settlement_busy_reproduces_historical_accounting_and_parent_lease_loss(
    tmp_path, monkeypatch
):
    """An alternative reachable cause; does not claim the lost server exception was this one."""
    store, _, job, _, _ = setup(tmp_path, monkeypatch)
    transaction = store.transaction

    @contextmanager
    def busy_settlement(**kwargs):
        if kwargs.get("operation") == "dispatch_settle":
            error = sqlite3.OperationalError("database is locked")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error
        with transaction(**kwargs) as db:
            yield db

    monkeypatch.setattr(store, "transaction", busy_settlement)
    with pytest.raises(sqlite3.OperationalError):
        store.dispatch(
            job,
            "openai",
            "settle-busy",
            "a" * 64,
            Decimal(".011"),
            lambda request: request | dict(actual_usd=".001"),
            now=time.time(),
        )
    with transaction(readonly=True) as db:
        assert tuple(db.execute("SELECT status,fence,error_code FROM runs").fetchone()) == (
            "accounting_pending",
            job["fence"] + 1,
            "ACCOUNTING_PENDING",
        )
        assert tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone()) == (
            None,
            "accounting_pending",
        )
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.renew_lease(job, now=time.time())


def test_unsent_schema_retry_does_not_release_prior_delivered_logical_budget(tmp_path, monkeypatch):
    store, _, job, probe = configured(tmp_path, monkeypatch)
    sent = []

    def pacing():
        if sent:
            raise TagHeartbeatFailed()

    def post(body):
        sent.append(1)
        return response("not JSON")

    probe.http_transport_pacing = pacing
    probe.post = post
    with pytest.raises(TagHeartbeatFailed):
        probe.complete("JSON", "{}", request_id="schema-stop", json_mode=True)
    assert sent == [1]
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("SELECT committed,receipt FROM probe_calls").fetchone() == ("0.02", None)
        assert [r[0] for r in db.execute("SELECT state FROM probe_transport_attempts")] == [
            "response_received",
            "never_sent",
        ]
    with store.transaction(readonly=True) as db:
        assert tuple(db.execute("SELECT status,fence FROM runs").fetchone()) == (
            "running",
            job["fence"],
        )
        rows = db.execute("SELECT actual,status FROM deletion.costs ORDER BY created").fetchall()
    assert rows[0][0] > 0 and rows[0][1] == "settled"
    assert tuple(rows[1]) == (0, "settled")


@pytest.mark.parametrize("boundary", ["acquire", "commit"])
@pytest.mark.parametrize("outcome", ["success", "control_unsent", "connect_unsent", "failure"])
@pytest.mark.parametrize("release_after", [15, 29])
def test_dispatch_accounting_survives_busy_beyond_ten_seconds(
    tmp_path, monkeypatch, boundary, outcome, release_after
):
    store, _, job, _, _ = setup(tmp_path, monkeypatch)
    clock = [0.0]
    armed = []
    calls = []
    writes = []
    connect = sqlite3.connect
    error = {
        "control_unsent": OpenAIControlNotSent(TagHeartbeatFailed()),
        "connect_unsent": OpenAIConnectNotSent({}),
        "failure": TagHeartbeatFailed(),
    }.get(outcome)

    def sleep(seconds):
        clock[0] += seconds

    def busy():
        if armed and clock[0] < release_after:
            exc = sqlite3.OperationalError("database is locked")
            exc.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise exc

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if boundary == "acquire" and sql == "BEGIN IMMEDIATE":
                busy()
            if armed and sql.startswith("UPDATE deletion.costs"):
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
        armed.append(True)
        if error is not None:
            raise error
        return request | dict(actual_usd=".001")

    def dispatch():
        return store.dispatch(
            job,
            "openai",
            "slow-accounting",
            "a" * 64,
            Decimal(".011"),
            transport,
            now=time.time(),
            allow_connect_not_sent=True,
        )

    if error is None:
        assert dispatch()["actual_usd"] == ".001"
    else:
        with pytest.raises(type(error)) as caught:
            dispatch()
        assert caught.value is error
    assert release_after <= clock[0] < 30
    assert len(calls) == len(writes) == 1  # Neither transport nor transaction body is replayed.
    with store.transaction(readonly=True) as db:
        cost = tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone())
        run = tuple(db.execute("SELECT status,fence FROM runs").fetchone())
        spend = db.execute("SELECT status FROM deletion.spend").fetchone()[0]
    if outcome == "failure":
        assert cost == (None, "accounting_pending")
        assert run == ("accounting_pending", job["fence"] + 1)
        assert spend == "accounting_pending"
        with pytest.raises(HostedError, match="LEASE_LOST"):
            store.renew_lease(job, now=time.time())
    else:
        assert cost == (1000 if outcome == "success" else 0, "settled")
        assert run == ("running", job["fence"])
        store.renew_lease(job, now=time.time())
