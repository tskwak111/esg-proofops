import json
import sqlite3

import pytest
from proofops.adapters.parsing.openai_vision import MODEL, OpenAIVisionProbe


def response(status="completed"):
    return dict(
        id="response-fixture",
        model=MODEL,
        status=status,
        usage=dict(input_tokens=500, output_tokens=100),
        output=[
            dict(
                type="message", content=[dict(type="output_text", text=json.dumps({"blocks": []}))]
            )
        ],
    )


def test_reserve_before_generation_and_replay_without_network(tmp_path):
    calls = []
    ledger = tmp_path / "budget.sqlite3"

    def post(path, payload, key):
        calls.append(path)
        assert key == "test-secret"
        if path.endswith("input_tokens"):
            return {"input_tokens": 500}
        with sqlite3.connect(ledger) as db:
            assert db.execute("SELECT state FROM calls").fetchone()[0] == "pending"
        assert payload["model"] == MODEL and payload["store"] is False
        assert "temperature" not in payload and payload["max_output_tokens"] == 8192
        return response()

    probe = OpenAIVisionProbe(ledger, post=post)
    first = probe(b"image", "test-secret")
    assert probe(b"image", "test-secret") == first
    assert calls == ["/v1/responses/input_tokens", "/v1/responses"]
    assert probe.summary()["states"]["completed"] == 1
    assert b"test-secret" not in ledger.read_bytes()
    first["blocks"] = [{"invented": 42}]
    with pytest.raises(ValueError, match="INTEGRITY"):
        probe.validate_result(first)


def test_budget_blocks_before_generation(tmp_path):
    calls = []
    probe = OpenAIVisionProbe(
        tmp_path / "budget.sqlite3",
        post=lambda path, body, key: calls.append(path) or {"input_tokens": 500},
    )
    with sqlite3.connect(probe.ledger) as db:
        db.execute("INSERT INTO calls VALUES ('previous','9.999','pending',NULL)")
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        probe(b"image", "test")
    assert calls == ["/v1/responses/input_tokens"]


@pytest.mark.parametrize("failure", ["timeout", "incomplete", "json"])
def test_failed_generation_is_never_automatically_repeated(tmp_path, failure):
    calls = []

    def post(path, body, key):
        calls.append(path)
        if path.endswith("input_tokens"):
            return {"input_tokens": 500}
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        result = response("incomplete" if failure == "incomplete" else "completed")
        if failure == "json":
            result["output"][0]["content"][0]["text"] = "{"
        return result

    probe = OpenAIVisionProbe(tmp_path / "budget.sqlite3", post=post)
    with pytest.raises((ValueError, TimeoutError)):
        probe(b"image", "test")
    with pytest.raises(ValueError, match="REQUIRES_REVIEW"):
        probe(b"image", "test")
    assert len(calls) == 2


def test_optional_model_preserves_old_profile_hashes():
    from uuid import uuid4

    from proofops.application.ingest.graph_fusion import ParserProfile

    base = ParserProfile(str(uuid4()), parser_mode="docling", table_auxiliary=False)
    assert "vision_model" not in base.invocation_snapshot()
    with pytest.raises(ValueError, match="vision_model"):
        ParserProfile(str(uuid4()), vision_model=MODEL)


def test_unexpected_usage_is_recorded_and_stops_new_generation(tmp_path):
    from decimal import Decimal

    calls = []

    def post(path, body, key):
        calls.append(path)
        if path.endswith("input_tokens"):
            return {"input_tokens": 1}
        raw = response()
        raw["usage"] = dict(input_tokens=100_000, output_tokens=8192)
        return raw

    probe = OpenAIVisionProbe(tmp_path / "budget.sqlite3", post=post)
    with pytest.raises(ValueError, match="RESERVATION_EXCEEDED"):
        probe(b"first-image", "test")
    assert Decimal(probe.summary()["committed_or_reserved_usd"]) > Decimal("0.018")
    with pytest.raises(ValueError, match="RECONCILIATION_REQUIRED"):
        probe(b"second-image", "test")
    assert calls.count("/v1/responses") == 1
