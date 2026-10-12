import http.client
import json
import sqlite3
import ssl

import pytest
from proofops.adapters.local.openai import OpenAIProbe

from tests.unit.test_openai_luna import response


def configured(tmp_path):
    from proofops.application.analysis_profile import FINALS_K10_POLICY
    from proofops.domain.provenance import canonical_hash

    probe = OpenAIProbe("fake", tmp_path / "ledger.sqlite3")
    probe.configure_response_policy(
        dict(
            tenant_id="tenant",
            document={"sha256": "a" * 64},
            analysis_profile_policy=FINALS_K10_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_K10_POLICY),
        ),
        role="extract",
    )
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

    RoleProviderConcurrency(
        1, requests_per_second=8, scheduler_policy=FINALS_K10_POLICY["provider_scheduler"]
    ).bind(probe)
    return probe


class FakeConnection:
    def __init__(self, *args, **kwargs):
        self.sock = None
        self.closed = False
        self.sent = 0

    def connect(self):
        self.sock = object()

    def request(self, *args, **kwargs):
        self.sent += 1

    def getresponse(self):
        class Reply:
            status = 200
            will_close = False

            def getheader(self, name):
                return None

            def read(self, limit):
                return json.dumps(response()).encode()

        return Reply()

    def close(self):
        self.closed = True
        self.sock = None


def test_k10_reuses_only_fully_consumed_connections(tmp_path, monkeypatch):
    made = []

    def factory(*args, **kwargs):
        obj = FakeConnection()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    probe = configured(tmp_path)
    for rid in ("first", "second"):
        probe.complete("Return JSON", json.dumps({"case": rid}), request_id=rid, json_mode=True)
    assert len(made) == 1 and made[0].sent == 2


def test_k10_connect_failure_gets_one_fresh_reservation(tmp_path, monkeypatch):
    made = []

    class ConnectFails(FakeConnection):
        def connect(self):
            raise ssl.SSLEOFError("handshake failed")

    def factory(*args, **kwargs):
        obj = ConnectFails() if not made else FakeConnection()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    probe = configured(tmp_path)
    result = probe.complete("Return JSON", "{}", request_id="first", json_mode=True)
    assert len(made) == 2 and made[0].sent == 0 and made[1].sent == 1
    assert result["transport_retries"][0]["dispatch_state"] == "never_sent"
    with sqlite3.connect(probe.ledger) as db:
        rows = db.execute("SELECT state FROM probe_transport_attempts").fetchall()
    assert rows == [("never_sent",), ("settled",)]
    assert probe.summary()["unsettled_calls"] == 0


@pytest.mark.parametrize("failure", [TimeoutError, ssl.SSLEOFError, http.client.RemoteDisconnected])
def test_k10_after_send_never_retries_or_reclaims(tmp_path, monkeypatch, failure):
    made = []

    class Fails(FakeConnection):
        def getresponse(self):
            raise failure("unknown delivery")

    def factory(*args, **kwargs):
        obj = Fails()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    probe = configured(tmp_path)
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("Return JSON", "{}", request_id="first", json_mode=True)
    assert len(made) == 1 and made[0].closed
    assert probe.summary()["committed_usd"] == "0.02"
    diagnostic = json.loads(next(probe._responses.glob("*.http-error.json")).read_text())
    assert diagnostic["request_started"] is True
    assert diagnostic["delivery_state"] == "unknown"


def test_k10_repeated_connect_failure_stops_after_two_attempts(tmp_path, monkeypatch):
    made = []

    class Fails(FakeConnection):
        def connect(self):
            raise TimeoutError("connect")

    def factory(*args, **kwargs):
        obj = Fails()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    probe = configured(tmp_path)
    with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
        probe.complete("Return JSON", "{}", request_id="first", json_mode=True)
    assert len(made) == 2 and all(c.sent == 0 for c in made)
    assert probe.summary()["committed_usd"] == "0"


def test_k10_admission_denied_after_unsent_connect_keeps_attempt_money_consistent(
    tmp_path, monkeypatch
):
    from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
    from proofops.application.analysis_profile import FINALS_K10_POLICY

    probe = configured(tmp_path)
    gate = RoleProviderConcurrency(
        1, requests_per_second=8, scheduler_policy=FINALS_K10_POLICY["provider_scheduler"]
    )
    gate.bind(probe)
    made = []

    class Fails(FakeConnection):
        def connect(self):
            gate.circuit_open = True
            raise TimeoutError("connect")

    def factory(*args, **kwargs):
        obj = Fails()
        made.append(obj)
        return obj

    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    with pytest.raises(ValueError, match="PROVIDER_CIRCUIT_OPEN"):
        probe.complete("Return JSON", "{}", request_id="first", json_mode=True)
    assert len(made) == 1 and made[0].sent == 0
    assert probe.summary()["committed_usd"] == "0"
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("SELECT state FROM probe_transport_attempts").fetchall() == [
            ("never_sent",),
            ("never_sent",),
        ]
