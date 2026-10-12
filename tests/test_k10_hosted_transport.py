import http.client
import sqlite3
import ssl

import pytest
from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
from proofops.application.analysis_profile import FINALS_K10_POLICY
from proofops.domain.provenance import canonical_hash

from tests.test_t1_403_retry import costs, setup
from tests.unit.test_k10_transport import FakeConnection


def configure(probe, auth):
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document={"sha256": "a" * 64},
            analysis_profile_policy=FINALS_K10_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_K10_POLICY),
        ),
        role="extract",
    )
    RoleProviderConcurrency(
        1, requests_per_second=8, scheduler_policy=FINALS_K10_POLICY["provider_scheduler"]
    ).bind(probe)


@pytest.mark.parametrize("second_fails", [False, True])
def test_k10_hosted_connect_retry_has_distinct_zero_and_new_reservations(
    tmp_path, monkeypatch, second_fails
):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    made = []

    class Fails(FakeConnection):
        def connect(self):
            raise ssl.SSLEOFError("connect")

    def factory(*args, **kwargs):
        obj = Fails() if not made or second_fails else FakeConnection()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    if second_fails:
        with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
            probe.complete("Return JSON", "{}", request_id="logical", json_mode=True)
    else:
        assert probe.complete("Return JSON", "{}", request_id="logical", json_mode=True)[
            "schema_valid"
        ]
    assert len(made) == 2
    rows = costs(store)
    assert len(rows) == 2 and rows[0][1] == "settled" and rows[0][3] == 0
    assert rows[1][1] == "settled"
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"
    with store.transaction() as db:
        assert db.execute("SELECT status FROM deletion.spend").fetchone()[0] != "accounting_pending"
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("SELECT count(*) FROM probe_transport_attempts").fetchone()[0] == 2


@pytest.mark.parametrize("failure", [TimeoutError, ssl.SSLEOFError, http.client.RemoteDisconnected])
def test_k10_hosted_post_send_unknown_has_no_retry(tmp_path, monkeypatch, failure):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    made = []

    class Fails(FakeConnection):
        def getresponse(self):
            raise failure("unknown delivery")

    def factory(*args, **kwargs):
        obj = Fails()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("Return JSON", "{}", request_id="unknown", json_mode=True)
    assert len(made) == 1
    assert costs(store)[0][1] == "accounting_pending"
    assert probe.summary()["committed_usd"] == "0.02"
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "running"


def test_k10_hosted_retry_admission_denial_has_no_unknown_or_extra_broker_reservation(
    tmp_path, monkeypatch
):
    store, auth, job, probe, _ = setup(tmp_path, monkeypatch, cap=".08")
    configure(probe, auth)
    gate = RoleProviderConcurrency(
        1, requests_per_second=8, scheduler_policy=FINALS_K10_POLICY["provider_scheduler"]
    )
    gate.bind(probe)

    class Fails(FakeConnection):
        def connect(self):
            gate.circuit_open = True
            raise TimeoutError("connect")

    monkeypatch.setattr(http.client, "HTTPSConnection", lambda *a, **k: Fails())
    with pytest.raises(ValueError, match="PROVIDER_CIRCUIT_OPEN"):
        probe.complete("Return JSON", "{}", request_id="denied", json_mode=True)
    assert len(costs(store)) == 1 and costs(store)[0][1] == "settled" and costs(store)[0][3] == 0
    assert probe.summary()["committed_usd"] == "0"
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("SELECT state FROM probe_transport_attempts").fetchall() == [
            ("never_sent",),
            ("never_sent",),
        ]
