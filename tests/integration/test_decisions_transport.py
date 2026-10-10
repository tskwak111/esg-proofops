"""Real reservation ledgers with fake HTTP; tests never load keys or call providers."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from proofops.adapters.local.decisions import DecisionProbe
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.application.tagging.decisions import preliminary_questions

from tests.unit.test_decision_profiles import preliminary_answers


def configured(tmp_path, provider="openai"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    spend = tmp_path / "r108-spend.json"
    if not spend.exists():
        spend.write_text(json.dumps(dict(limit_usd="10.00", cumulative_usd="1.60", executions=[])))
    ledger = tmp_path / provider / "budget.sqlite3"
    if provider == "openrouter":
        OpenRouterProbe("fake", ledger)
    probe = DecisionProbe(provider, ledger, r108_spend=spend, key_loader=lambda: "fake")
    calls = []

    def post(body):
        calls.append(body)
        answers = preliminary_answers()
        return dict(
            model=probe.model,
            answers=answers,
            usage=dict(input_tokens=100, output_tokens=0, cost=0.0000042),
        )

    probe._post = post
    return probe, calls, spend


def test_wire_reservation_pins_and_free_saved_replay(tmp_path):
    for provider in ("openai", "openrouter"):
        probe, calls, spend = configured(tmp_path, provider)
        result = probe.decide(
            {"quote": "원문"}, preliminary_questions(), request_id=provider + "-1"
        )
        assert len(calls) == 1
        assert "temperature" not in calls[0]
        assert ("input" if provider == "openai" else "state") in calls[0]
        assert result["answers"]["track"]["choice"] == "goal"
        assert result["receipt"]["response_sha256"]
        before = spend.read_bytes()
        probe._post = lambda _: pytest.fail("replay made a paid call")
        assert (
            probe.decide({"quote": "원문"}, preliminary_questions(), request_id=provider + "-1")
            == result
        )
        assert spend.read_bytes() == before
        with pytest.raises(ValueError, match="DECISION_REQUEST_MISMATCH"):
            probe.decide(
                {"quote": "different"}, preliminary_questions(), request_id=provider + "-1"
            )


def test_pending_call_never_retried_and_retains_both_caps(tmp_path):
    probe, _, spend = configured(tmp_path)
    probe._post = lambda _: (_ for _ in ()).throw(TimeoutError("secret text"))
    with pytest.raises(ValueError, match="DECISION_REQUEST_FAILED"):
        probe.decide({}, preliminary_questions(), request_id="pending")
    with pytest.raises(ValueError, match="DECISION_PENDING_CALL"):
        probe.decide({}, preliminary_questions(), request_id="pending")
    with sqlite3.connect(probe.ledger) as db:
        assert db.execute("select committed from probe_calls").fetchone()[0] == "0.02"
    assert Decimal(json.loads(spend.read_text())["cumulative_usd"]) == Decimal("1.62")


def test_shared_r108_and_provider_caps_before_http(tmp_path):
    probe, calls, spend = configured(tmp_path)
    data = json.loads(spend.read_text())
    data["cumulative_usd"] = "9.99"
    spend.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="R108_BUDGET_EXHAUSTED"):
        probe.decide({}, preliminary_questions(), request_id="cap")
    assert calls == []


def test_concurrent_duplicate_dispatches_only_once(tmp_path):
    probe, calls, _ = configured(tmp_path)

    def run(_):
        try:
            return probe.decide({}, preliminary_questions(), request_id="same")
        except ValueError as error:
            assert str(error) == "DECISION_PENDING_CALL"

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, range(4)))
    assert len(calls) == 1


def test_saved_response_hash_tampering_fails_closed(tmp_path):
    probe, _, _ = configured(tmp_path)
    result = probe.decide({}, preliminary_questions(), request_id="tamper")
    with sqlite3.connect(probe.ledger) as db:
        receipt = json.loads(db.execute("select receipt from probe_calls").fetchone()[0])
    path = probe.responses / receipt["response_file"]
    data = json.loads(path.read_text())
    data["answers"]["track"]["choice"] = "management"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="DECISION_RECEIPT_MISMATCH"):
        probe.decide({}, preliminary_questions(), request_id="tamper")
    assert result["receipt"]["policy_sha256"]


def test_lease_loss_before_http_is_propagated(tmp_path):
    from proofops.application.ports.jobs import LeaseLost

    probe, calls, _ = configured(tmp_path)

    def lost():
        raise LeaseLost("LEASE_LOST")

    with pytest.raises(LeaseLost):
        probe.decide({}, preliminary_questions(), request_id="lost", before_dispatch=lost)
    assert calls == []


def test_provider_cost_parse_failure_retains_reservation_with_safe_code(tmp_path):
    probe, _, _ = configured(tmp_path, "openrouter")
    probe._post = lambda _: dict(
        model=probe.model,
        answers=preliminary_answers(),
        usage=dict(input_tokens=100, output_tokens=0, cost="not-a-price"),
    )
    with pytest.raises(ValueError, match="DECISION_USAGE_INVALID_RESERVATION_RETAINED"):
        probe.decide({}, preliminary_questions(), request_id="bad-cost")


@pytest.mark.parametrize("provider,rows", [("openai", 150), ("openrouter", 250)])
def test_provider_ceiling_preserves_historical_pending_calls(tmp_path, provider, rows):
    probe, calls, _ = configured(tmp_path, provider)
    with sqlite3.connect(probe.ledger) as db:
        db.executemany(
            "INSERT INTO probe_calls VALUES (?,?,?,NULL)",
            [(f"old-{n}", "old-signature", "0.02") for n in range(rows)],
        )
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        probe.decide({}, preliminary_questions(), request_id="over-cap")
    assert calls == []
