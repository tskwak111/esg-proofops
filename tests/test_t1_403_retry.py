"""T1 opt-in overload denial recovery, real broker reservations and source fences."""

import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from proofops.adapters.local import openai
from proofops.application.analysis_profile import FINALS_I5_POLICY, FINALS_T1_POLICY, policy_for
from proofops.application.openai_retry import POLICY
from proofops.domain.provenance import canonical_hash
from proofops_api import hosted_analysis
from proofops_api.hosted_store import HostedError, HostedStore

from tests.test_hosted_public import actor, uploaded
from tests.test_hosted_public import settings as base_settings
from tests.unit.test_openai_luna import response


def setup(tmp_path, monkeypatch, *, enabled=True, cap=".03"):
    settings = replace(base_settings.__wrapped__(tmp_path), run_usd=Decimal(cap))
    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "t1-retry-case-001", now=time.time())
    job = store.claim(now=time.time())
    probe = hosted_analysis.HostedOpenAILunaProbe(
        "fake", tmp_path / "probe.sqlite3", store=store, job=job
    )
    policy = FINALS_T1_POLICY if enabled else FINALS_I5_POLICY
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=policy,
            analysis_profile_policy_sha256=canonical_hash(policy),
        ),
        role="extract",
    )
    sleeps = []
    monkeypatch.setattr(hosted_analysis.time, "sleep", sleeps.append)
    return store, auth, job, probe, sleeps


def wire(monkeypatch, replies):
    calls = []

    class Connection:
        def __init__(self, host, timeout):
            self.reply = next(replies)
            self.status = self.reply[0]

        def request(self, method, path, **kwargs):
            calls.append(kwargs)

        def getresponse(self):
            return self

        def getheader(self, name):
            return self.reply[2].get(name.lower())

        def read(self, limit):
            return self.reply[1]

        def close(self):
            pass

    monkeypatch.setattr(openai.http.client, "HTTPSConnection", Connection)
    return calls


def denial(
    *,
    code="server_is_overloaded",
    kind="service_unavailable_error",
    raw=None,
    retry="5",
    request_id="req_abc123",
):
    return (
        403,
        raw if raw is not None else json.dumps(dict(error=dict(code=code, type=kind))).encode(),
        {
            "retry-after": retry,
            "x-request-id": request_id,
        },
    )


def success(content='{"ok":true}'):
    data = response(content)
    data["id"] = "chatcmpl-" + str(uuid4())
    return 200, json.dumps(data).encode(), {"x-request-id": "req_success"}


def costs(store):
    with store.transaction() as db:
        return db.execute(
            "SELECT request_id,status,bound,actual FROM deletion.costs ORDER BY created"
        ).fetchall()


def test_one_delayed_retry_new_broker_reservation_old_denial_retained(tmp_path, monkeypatch):
    store, _, job, probe, sleeps = setup(tmp_path, monkeypatch)
    calls = wire(monkeypatch, iter([denial(), success()]))
    result = probe.complete("Return JSON", "{}", request_id="t1-call", json_mode=True)
    assert result["schema_valid"] is True
    assert len(calls) == 2 and 5 <= sleeps[0] <= 6
    assert calls[0]["body"] == calls[1]["body"]
    assert calls[0]["headers"]["X-Client-Request-Id"] != calls[1]["headers"]["X-Client-Request-Id"]
    rows = costs(store)
    assert [r[1] for r in rows] == ["accounting_pending", "settled"]
    assert rows[0][2:] == (11000, None)
    assert result["transport_retries"][0]["policy_sha256"] == canonical_hash(POLICY)
    sidecars = list(probe.http_error_directory.glob("*.http-error.json"))
    assert len(sidecars) == 1
    diagnostic = json.loads(sidecars[0].read_text())
    assert diagnostic["client_request_id"] == rows[0][0]
    assert diagnostic["local_request_id"] == "t1-call"
    assert canonical_hash(diagnostic) == result["transport_retries"][0]["diagnostic_sha256"]
    assert probe.wire_policy["http_retry_policy_sha256"] == canonical_hash(POLICY)
    with store.transaction() as db:
        assert tuple(
            db.execute("SELECT status,fence FROM runs WHERE run_id=?", (job["run_id"],)).fetchone()
        ) == ("running", job["fence"])
    with pytest.raises(ValueError, match="DUPLICATE_PROBE_REQUEST"):
        probe.complete("Return JSON", "{}", request_id="t1-call", json_mode=True)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "reply",
    [
        denial(raw=b""),
        denial(code="permission_denied"),
        denial(code="insufficient_quota"),
        denial(kind="invalid_request_error"),
        denial(retry=None),
        denial(retry="31"),
        denial(retry="nan"),
        denial(request_id=None),
    ],
)
def test_unclassified_permanent_or_unbounded_denial_never_retry(tmp_path, monkeypatch, reply):
    store, _, _, probe, sleeps = setup(tmp_path, monkeypatch)
    calls = wire(monkeypatch, iter([reply, success()]))
    with pytest.raises(ValueError):
        probe.complete("JSON", "{}", request_id="t1-call", json_mode=True)
    assert len(calls) == 1 and not sleeps
    assert costs(store)[0][1] == "accounting_pending"
    assert probe.summary()["unsettled_calls"] == 1


def test_historical_policy_does_not_retry_structured_overload(tmp_path, monkeypatch):
    store, _, _, probe, sleeps = setup(tmp_path, monkeypatch, enabled=False)
    calls = wire(monkeypatch, iter([denial(), success()]))
    with pytest.raises(ValueError, match="OPENAI_HTTP_403"):
        probe.complete("JSON", "{}", request_id="t1-call")
    assert len(calls) == 1 and not sleeps
    assert "http_retry_policy_sha256" not in probe.wire_policy
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I5_POLICY))
        == FINALS_I5_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_T1_POLICY))
        == FINALS_T1_POLICY
    )


def test_repeat_denial_stops_and_does_not_create_third_reservation(tmp_path, monkeypatch):
    store, _, job, probe, sleeps = setup(tmp_path, monkeypatch)
    calls = wire(monkeypatch, iter([denial(), denial(), success()]))
    with pytest.raises(ValueError, match="OPENAI_HTTP_403"):
        probe.complete("JSON", "{}", request_id="t1-call")
    assert len(calls) == 2 and len(sleeps) == 1
    assert [r[1] for r in costs(store)] == ["accounting_pending"] * 2
    with store.transaction() as db:
        assert tuple(
            db.execute("SELECT status,fence FROM runs WHERE run_id=?", (job["run_id"],)).fetchone()
        ) == ("accounting_pending", job["fence"] + 1)


@pytest.mark.parametrize("reason", ["budget", "deleted", "expired", "cancelled"])
def test_retry_rechecks_money_owner_and_source_after_delay(tmp_path, monkeypatch, reason):
    store, auth, job, probe, _ = setup(
        tmp_path, monkeypatch, cap=".015" if reason == "budget" else ".03"
    )
    calls = wire(monkeypatch, iter([denial(), success()]))

    def delay(_):
        if reason == "deleted":
            store.delete_document(auth, job["document_id"], "t1-delete-case-001", now=time.time())
        elif reason in {"expired", "cancelled"}:
            with store.transaction() as db:
                if reason == "expired":
                    db.execute("UPDATE documents SET expires=0")
                else:
                    db.execute("UPDATE runs SET status='cancelled',fence=fence+1")

    monkeypatch.setattr(hosted_analysis.time, "sleep", delay)
    with pytest.raises((ValueError, HostedError)):
        probe.complete("JSON", "{}", request_id="t1-call")
    assert len(calls) == 1
    assert len(costs(store)) == 1


def test_schema_retry_does_not_reset_transport_retry_allowance(tmp_path, monkeypatch):
    store, _, _, probe, sleeps = setup(tmp_path, monkeypatch, cap=".05")
    calls = wire(monkeypatch, iter([denial(), success('{"ok":"bad"}'), denial(), success()]))
    with pytest.raises(ValueError, match="OPENAI_HTTP_403"):
        probe.complete(
            "JSON",
            "{}",
            request_id="t1-call",
            schema_json=json.dumps(
                {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
            ),
        )
    assert len(calls) == 3 and len(sleeps) == 1
    assert len(costs(store)) == 3


def test_price_expiry_during_delay_prevents_second_dispatch(tmp_path, monkeypatch):
    store, _, _, probe, _ = setup(tmp_path, monkeypatch)
    calls = wire(monkeypatch, iter([denial(), success()]))

    def delay(_):
        monkeypatch.setattr(openai, "now", lambda: datetime(2026, 10, 21, tzinfo=UTC))

    monkeypatch.setattr(hosted_analysis.time, "sleep", delay)
    with pytest.raises(ValueError, match="PRICE_RECHECK_REQUIRED"):
        probe.complete("JSON", "{}", request_id="t1-call")
    assert len(calls) == 1 and len(costs(store)) == 1


def test_opt_in_caps_workers_without_changing_v5_or_accepting_mutated_policy(tmp_path):
    profiles = hosted_analysis.operator_profiles(
        dict(
            analysis_profile="finals-unattended-v2",
            llm_max_workers=16,
            analysis_policy_sha256=canonical_hash(FINALS_T1_POLICY),
        )
    )
    assert profiles["llm_max_workers"] == 8
    assert (
        hosted_analysis.operator_profiles(
            dict(llm_max_workers=16, analysis_policy_sha256=canonical_hash(FINALS_I5_POLICY))
        )["llm_max_workers"]
        == 16
    )
    policy = FINALS_T1_POLICY | dict(openai_retry_policy=POLICY | dict(max_retries=2))
    probe = openai.OpenAIProbe("fake", tmp_path / "local.sqlite3")
    with pytest.raises(ValueError, match="OPENAI_RETRY_POLICY_MISMATCH"):
        probe.configure_response_policy(
            dict(
                tenant_id="tenant",
                document=dict(sha256="a" * 64),
                analysis_profile_policy=policy,
                analysis_profile_policy_sha256=canonical_hash(policy),
            ),
            role="extract",
        )
