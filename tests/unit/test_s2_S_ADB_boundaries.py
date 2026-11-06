"""Offline wire/ledger boundaries frozen before the S_ADB module split."""

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from proofops.adapters.local import openai
from proofops.domain.provenance import canonical_hash


def test_http_helper_can_be_imported_before_public_adapter():
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from proofops.adapters.local import openai_http; "
            "from proofops.adapters.local.openai import OpenAIProbe; "
            "assert OpenAIProbe.request_body is openai_http.request_body",
        ],
        capture_output=True,
        text=True,
    )
    assert child.returncode == 0, child.stderr


def test_wire_reservation_response_bytes_and_settlement(tmp_path, monkeypatch):
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    response = {
        "id": "chatcmpl-boundary",
        "model": "gpt-6-luna",
        "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 40},
        },
    }
    events = []

    class Connection:
        def __init__(self, host, timeout):
            events.append((host, timeout))

        def request(self, method, path, *, body, headers):
            with sqlite3.connect(probe.ledger) as db:
                assert db.execute("SELECT committed,receipt FROM probe_calls").fetchall() == [
                    ("0.02", None)
                ]
            assert body == (
                b'{"model":"gpt-6-luna","messages":[{"role":"system","content":"JSON"},'
                b'{"role":"user","content":"{}"}],"max_completion_tokens":1024,'
                b'"temperature":0,"stream":false,"reasoning_effort":"none","store":false,'
                b'"service_tier":"default","response_format":{"type":"json_object"}}'
            )
            assert headers == {"Authorization": "Bearer fake", "Content-Type": "application/json"}
            events.append((method, path, "reserved"))

        def getresponse(self):
            return self

        def getheader(self, name):
            return "req_boundary" if name == "x-request-id" else None

        def read(self, limit):
            assert limit == 1_048_577
            events.append("read")
            return json.dumps(response).encode()

        def close(self):
            events.append("closed")

        status = 200

    monkeypatch.setattr(openai.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(openai.time, "monotonic", lambda: 123.0)
    receipt = probe.complete("JSON", "{}", request_id="boundary", json_mode=True)
    events.append("settled")
    assert events == [
        ("api.openai.com", 90),
        ("POST", "/v1/chat/completions", "reserved"),
        "read",
        "closed",
        "settled",
    ]
    stored_response = response | {"openai_request_id": "req_boundary"}
    path = probe._responses / (canonical_hash("boundary:0") + ".json")
    assert (
        path.read_bytes()
        == json.dumps(
            {"request_id": "boundary", "attempt": 0, "provider_response": stored_response}
        ).encode()
    )
    assert receipt["response_sha256"] == canonical_hash(stored_response)
    assert receipt["model_binding_sha256"] == canonical_hash(openai.WIRE_POLICY)
    assert receipt["attempts"] == [
        {
            "provider_request_id": "chatcmpl-boundary",
            "cost_usd": "0.000018040",
            "response_sha256": canonical_hash(stored_response),
            "latency_ms": 0.0,
        }
    ]
    assert Decimal(receipt["cost_with_vat_reserve_usd"]) == Decimal("0.00001804")
    with sqlite3.connect(probe.ledger) as db:
        committed, encoded = db.execute("SELECT committed,receipt FROM probe_calls").fetchone()
    assert committed == receipt["cost_with_vat_reserve_usd"]
    assert encoded == json.dumps(
        {k: v for k, v in receipt.items() if k != "content"}, sort_keys=True
    )


def test_public_price_clock_and_retry_clock_stay_live(tmp_path, monkeypatch):
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    probe._post = lambda _: pytest.fail("price guard must run before dispatch")
    expired = datetime(2026, 10, 21, tzinfo=UTC)
    monkeypatch.setattr(openai, "now", lambda: expired)
    with pytest.raises(ValueError, match="PRICE_RECHECK_REQUIRED"):
        probe.complete("JSON", "{}", request_id="expired")
    with pytest.raises(ValueError, match="PRICE_RECHECK_REQUIRED"):
        openai.validate_capacity_policy(openai.CAPACITY_POLICY, model_id=openai.MODEL)
    assert openai._retry_after("Wed, 21 Oct 2026 00:00:05 GMT") == 5.0
    monkeypatch.setattr(openai, "PRICE_RECHECK_AT", datetime(2026, 10, 22, tzinfo=UTC))
    assert openai.validate_capacity_policy(openai.CAPACITY_POLICY, model_id=openai.MODEL) == 32768
    assert probe.summary()["calls"] == 0
