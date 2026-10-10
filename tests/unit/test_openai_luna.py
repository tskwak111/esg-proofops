"""Direct OpenAI contract; fake HTTP only, no credentials."""

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from proofops.adapters.local import openai
from proofops.adapters.local.decisions import DecisionProbe
from proofops.domain.provenance import canonical_hash


def response(content='{"ok":true}', **usage):
    return dict(
        id="chatcmpl-test",
        model=openai.MODEL,
        choices=[dict(finish_reason="stop", message=dict(content=content))],
        usage=dict(
            prompt_tokens=100,
            completion_tokens=20,
            prompt_tokens_details=dict(cached_tokens=40),
            **usage,
        ),
    )


def test_wire_and_official_token_settlement(tmp_path):
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    sent = []
    probe._post = lambda body: sent.append(body) or response()
    result = probe.complete("Return JSON", "{}", request_id="one", json_mode=True)
    assert sent[0]["model"] == "gpt-6-luna"
    assert sent[0]["reasoning_effort"] == "none"
    assert sent[0]["temperature"] == 0
    assert sent[0]["store"] is False
    assert "provider" not in sent[0] and "max_tokens" not in sent[0]
    assert result["provider"] == "openai"
    assert result["endpoint"] == "https://api.openai.com/v1/chat/completions"
    assert result["model_binding_sha256"] == canonical_hash(openai.WIRE_POLICY)
    assert Decimal(result["cost_with_vat_reserve_usd"]) == Decimal("0.00001804")
    assert probe.summary()["unsettled_calls"] == 0


def test_historical_decisions_cap_is_preserved(tmp_path):
    ledger = tmp_path / "budget.sqlite3"
    old = DecisionProbe(
        "openai", ledger, r108_spend=tmp_path / "spend.json", key_loader=lambda: "fake"
    )
    with sqlite3.connect(old.ledger) as db:
        db.executemany(
            "INSERT INTO probe_calls VALUES (?,?,?,NULL)",
            [(str(i), "old", "0.02") for i in range(150)],
        )
    probe = openai.OpenAIProbe("fake", ledger)
    probe._post = lambda _: pytest.fail("escaped existing USD3 cap")
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        probe.complete("JSON", "{}", request_id="new")
    assert old._total(sqlite3.connect(ledger)) == Decimal("3.00")


def test_expiry_and_uncertain_call_fail_closed(tmp_path, monkeypatch):
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    probe._post = lambda _: (_ for _ in ()).throw(TimeoutError("private"))
    with pytest.raises(ValueError, match="OPENAI_REQUEST_FAILED"):
        probe.complete("JSON", "{}", request_id="pending")
    assert probe.summary()["committed_usd"] == "0.02"
    with pytest.raises(ValueError, match="DUPLICATE_PROBE_REQUEST"):
        probe.complete("JSON", "{}", request_id="pending")
    monkeypatch.setattr(openai, "now", lambda: datetime(2026, 10, 21, tzinfo=UTC))
    with pytest.raises(ValueError, match="PRICE_RECHECK_REQUIRED"):
        probe.complete("JSON", "{}", request_id="expired")


def test_schema_retry_charges_both_attempts(tmp_path):
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    answers = iter([response('{"ok":"bad"}'), response()])
    probe._post = lambda _: next(answers)
    result = probe.complete(
        "JSON",
        "{}",
        request_id="retry",
        json_mode=True,
        schema_json=json.dumps(
            dict(type="object", required=["ok"], properties=dict(ok=dict(type="boolean")))
        ),
    )
    assert len(result["attempts"]) == 2
    assert Decimal(result["cost_with_vat_reserve_usd"]) == Decimal("0.00003608")


def test_extraction_profile_and_finals_provider(tmp_path, monkeypatch):
    from proofops_agent.upstage_extraction import _profile_with_options

    from scripts.finals_demo import pilot_argv

    assert (
        _profile_with_options("gpt-6-luna", wire_policy_version=2).model_sha256
        != _profile_with_options("openai/gpt-6-luna", wire_policy_version=2).model_sha256
    )
    monkeypatch.setenv("PROOFOPS_LLM_PROVIDER", "openai")
    template = [
        "pilot",
        "--pdf",
        "p",
        "--state",
        "s",
        "--pages",
        "66,67",
        "--claim-pages",
        "66,67",
        "--report-year",
        "2024",
        "--period-start",
        "x",
        "--period-end",
        "y",
        "--llm-provider",
        "openrouter",
        "--relation-profile",
        "occurrence-v3",
        "--claim-source-profile",
        "glyph-alignment-v1",
        "--display-text-profile",
        "glyph-joined-display-v1",
    ]
    argv = pilot_argv(
        template, pdf=tmp_path / "p.pdf", state=tmp_path / "s", port=8080, root=tmp_path
    )
    assert argv[argv.index("--llm-provider") + 1] == "openai"
    assert argv[argv.index("--key-file") + 1].endswith(".env.openai.local")


@pytest.mark.parametrize("bundle", [None, "--r108-finals-candidate", "--r108-finals-candidate-v2"])
def test_fresh_pilot_openai_authorization_and_resume(tmp_path, monkeypatch, bundle):
    import os
    import sys

    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    argv = create_argv(tmp_path) + [
        "--llm-provider",
        "openai",
        "--live-tagging",
        "--live-relations",
    ]
    if bundle:
        argv.append(bundle)
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    saved = json.loads((tmp_path / "state/settings.json").read_text())
    assert saved["tagging_settings"]["model_id"] == "gpt-6-luna"
    assert saved["input_reservation_policy"] == openai.CAPACITY_POLICY
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(tmp_path / "state")])
    assert pilot.main() == 0


def test_transport_fixed_host_size_and_no_redirects(tmp_path, monkeypatch):
    calls = []

    class Connection:
        def __init__(self, host, timeout):
            calls.append((host, timeout))

        def request(self, method, path, **kwargs):
            calls.append((method, path))

        def getresponse(self):
            return self

        def getheader(self, name):
            return None

        def read(self, _limit):
            return b""

        def close(self):
            calls.append("closed")

        status = 302

    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    monkeypatch.setattr(openai.http.client, "HTTPSConnection", Connection)
    with pytest.raises(ValueError, match="OPENAI_HTTP_302"):
        probe._post({})
    assert calls == [("api.openai.com", 90), ("POST", "/v1/chat/completions"), "closed"]
    Connection.status = 200
    Connection.read = lambda self, limit: b"x" * limit
    with pytest.raises(ValueError, match="OPENAI_RESPONSE_TOO_LARGE"):
        probe._post({})
    assert calls.count(("POST", "/v1/chat/completions")) == 2


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, b'{"error":{"message":"private","code":"invalid_api_key"}}', "OPENAI_HTTP_401"),
        (429, b'{"error":{"message":"private","code":"rate_limit_exceeded"}}', "OPENAI_HTTP_429"),
        (
            429,
            b'{"error":{"message":"private quota detail","code":"insufficient_quota"}}',
            "OPENAI_INSUFFICIENT_QUOTA",
        ),
    ],
)
def test_http_quota_errors_are_classified_without_exposing_provider_body(
    tmp_path, monkeypatch, status, body, expected
):
    class Response:
        def __init__(self):
            self.status = status

        def getheader(self, name):
            return None

        def read(self, limit):
            assert limit == 1_048_577
            return body

    class Connection:
        def __init__(self, host, timeout):
            assert host == "api.openai.com" and timeout == 90

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(openai.http.client, "HTTPSConnection", Connection)
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    with pytest.raises(ValueError, match=expected) as error:
        probe._post({})
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "invalid",
    [
        dict(prompt_tokens=-1),
        dict(prompt_tokens=True),
        dict(prompt_tokens=32769),
        dict(prompt_tokens_details=dict(cached_tokens=101)),
        dict(prompt_tokens_details=dict(cache_write_tokens=-1)),
        dict(model="another-model"),
    ],
)
def test_bad_usage_or_binding_retains_reservation(tmp_path, invalid):
    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    data = response()
    if "model" in invalid:
        data.update(invalid)
    else:
        data["usage"].update(invalid)
    probe._post = lambda _: data
    with pytest.raises(ValueError, match="OPENAI_RECEIPT_INVALID_RESERVATION_RETAINED"):
        probe.complete("JSON", "{}", request_id="invalid")
    assert probe.summary()["unsettled_calls"] == 1


def test_concurrent_shared_ledger_duplicate_only_dispatches_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    probe = openai.OpenAIProbe("fake", tmp_path / "budget.sqlite3")
    sent = []
    probe._post = lambda _: sent.append(1) or response()

    def call(_):
        try:
            probe.complete("JSON", "{}", request_id="same")
            return "sent"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(call, range(4)))
    assert result.count("sent") == 1
    assert result.count("DUPLICATE_PROBE_REQUEST") == 3
    assert sent == [1]


def test_cache_write_price_is_not_additive():
    assert openai.token_cost(
        dict(
            prompt_tokens=100,
            completion_tokens=0,
            prompt_tokens_details=dict(cached_tokens=20, cache_write_tokens=30),
        )
    ) == Decimal("0.000009845")


def test_r108_includes_other_task_reservations_before_provider_dispatch(tmp_path):
    from scripts.finals_demo import FinalsBudget
    from tests.unit.test_finals_demo import budget

    base = budget(tmp_path)
    data = json.loads(base.spend_path.read_text())
    data["cumulative_usd"] = "9.97"
    base.spend_path.write_text(json.dumps(data))
    first = FinalsBudget(
        base.spend_path, base.ledgers, base.events_path, task="first", limit_usd="0.25"
    )
    second = FinalsBudget(
        base.spend_path, base.ledgers, base.events_path, task="second", limit_usd="0.25"
    )
    first.reserve(Decimal("0.02"))
    with pytest.raises(ValueError, match="R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED"):
        second.reserve(Decimal("0.02"))
