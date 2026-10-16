"""Money and one-shot boundaries for the coordinator's script; fake HTTP only."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scripts import hf1_validate_live as live


def cases():
    return [
        dict(
            role=role,
            local_schema={"type": "object"},
            body=dict(
                model="gpt-6-luna",
                messages=[dict(role="system", content="Return JSON")],
                response_format={"type": "json_object"},
                max_completion_tokens=1800,
                stream=False,
                store=False,
                reasoning_effort="none",
                service_tier="default",
            ),
        )
        for role in live.ROLES
    ]


@pytest.fixture(autouse=True)
def offline_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 16, tzinfo=UTC)

    monkeypatch.setattr(live, "datetime", Clock)


def test_budget_preflight_and_wire_limits():
    assert sum(live.plan(cases())) < Decimal("0.05")
    for field, value in (
        ("max_completion_tokens", 100000),
        ("tools", [{}]),
        ("model", "other"),
        ("service_tier", "priority"),
    ):
        invalid = deepcopy(cases())
        invalid[0]["body"][field] = value
        with pytest.raises(ValueError, match="WIRE_POLICY"):
            live.plan(invalid)
    invalid = cases()
    invalid[0]["body"]["messages"][0]["content"] = "JSON " + "x" * 16384
    with pytest.raises(ValueError, match="REQUEST_TOO_LARGE"):
        live.plan(invalid)


def test_five_calls_only_and_durable_no_retry(tmp_path, monkeypatch):
    sent = []

    def send(body, key):
        assert (tmp_path / "HF1-LIVE-ATTEMPT.json").exists()
        sent.append(body)
        return 200, json.dumps(
            dict(
                choices=[dict(finish_reason="stop", message=dict(content="{}"))],
                usage=dict(prompt_tokens=20, completion_tokens=5),
            )
        ).encode()

    monkeypatch.setattr(live, "send", send)
    assert live.run(cases(), "fake-offline", tmp_path) == 0
    assert len(sent) == 5
    with pytest.raises(FileExistsError):
        live.run(cases(), "fake-offline", tmp_path)
    assert len(sent) == 5


@pytest.mark.parametrize("failure", ["400", "timeout", "schema"])
def test_first_failure_stops_and_retains_full_reservation(tmp_path, monkeypatch, failure, capsys):
    sent = []

    def send(body, key):
        sent.append(body)
        if failure == "timeout":
            raise TimeoutError("private key must never be printed")
        return (400 if failure == "400" else 200), b'{"private":"not logged"}'

    monkeypatch.setattr(live, "send", send)
    assert live.run(cases(), "fake-offline", tmp_path) == 1
    assert len(sent) == 1
    marker = json.loads((tmp_path / "HF1-LIVE-ATTEMPT.json").read_text())
    assert Decimal(marker["reserved_usd"]) == sum(live.plan(cases()))
    assert "private" not in capsys.readouterr().out


def test_expired_prices_block_before_network_or_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "PRICE_EXPIRES", datetime(2026, 10, 15, tzinfo=UTC))
    monkeypatch.setattr(live, "send", lambda *args: pytest.fail("network forbidden"))
    with pytest.raises(ValueError, match="PRICE_RECHECK_REQUIRED"):
        live.run(cases(), "fake-offline", tmp_path)
    assert not (tmp_path / "HF1-LIVE-ATTEMPT.json").exists()
