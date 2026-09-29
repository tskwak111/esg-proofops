import json
import sqlite3
import time
from dataclasses import asdict
from threading import Lock

import pytest
from proofops.adapters.local.openrouter import MODEL, OpenRouterProbe
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile
from proofops_worker.extract_runner import prefetch_packets

SCHEMA = json.dumps(
    {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
)


def response(content, identifier="call", cost=0.001):
    return {
        "id": identifier,
        "model": MODEL,
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cost": cost,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def test_luna_request_receipt_and_distinct_model_identity(tmp_path, monkeypatch):
    probe = OpenRouterProbe("test-key", tmp_path / "budget.sqlite3")
    sent = []
    monkeypatch.setattr(probe, "_post", lambda body: sent.append(body) or response('{"ok":true}'))
    receipt = probe.complete("system", "{}", request_id="one", json_mode=True, schema_json=SCHEMA)
    assert sent[0]["model"] == MODEL
    assert sent[0]["reasoning"] == {"effort": "none"}
    assert sent[0]["temperature"] == 0
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert receipt["provider"] == "openrouter"
    assert receipt["cost_source"] == "usage.cost"
    assert receipt["cost_with_vat_reserve_usd"] == "0.001"
    assert probe.summary()["committed_usd"] == "0.001"
    assert _profile(MODEL).model_sha256 != _profile("solar-pro4").model_sha256
    assert _profile(MODEL).prompt_sha256 == _profile("solar-pro4").prompt_sha256


def test_luna_extraction_receipt_replays_under_frozen_identity(tmp_path, monkeypatch):
    probe = OpenRouterProbe("test-key", tmp_path / "budget.sqlite3")
    sent = []
    content = '{"claims":["회사는 2030년까지 배출량을 20% 줄이기로 했다."]}'
    monkeypatch.setattr(probe, "_post", lambda body: sent.append(body) or response(content))
    extractor = UpstageClaimExtractor(probe, tmp_path / "receipts")
    packet = {
        "tenant_id": "b490d4e4-0192-426c-9dff-c6c7b8c498d3",
        "document_version_id": "35d03dcb-c9d0-40d6-a3d1-8f9dc7322ee1",
        "parse_manifest_id": "62919374-bd2d-4273-85b4-7a1f793b8c14",
        "source_sha256": "c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde",
        "extraction_profile": asdict(extractor.profile),
        "untrusted_document_data": {
            "source_id": "11111111-2222-4333-8444-555555555555",
            "page_num": 25,
            "kind": "paragraph",
            "text": "회사는 2030년까지 배출량을 20% 줄이기로 했다. 일반 산업 설명이다.",
        },
    }
    first = extractor.extract(packet)
    assert extractor.extract(packet) == first
    assert len(sent) == 1
    receipt_dir = next(path for path in (tmp_path / "receipts").iterdir() if path.is_dir())
    raw = json.loads((receipt_dir / "raw_response.json").read_text())
    identity = json.loads((receipt_dir / "identity.json").read_text())
    assert raw["provider"] == "openrouter"
    assert raw["model"] == MODEL
    assert identity == {
        "provider": "openrouter",
        "model": MODEL,
        "model_sha256": extractor.profile.model_sha256,
        "prompt_sha256": extractor.profile.prompt_sha256,
    }
    result = json.loads((receipt_dir / "result.json").read_text())
    assert result["profile"] == asdict(extractor.profile)


def test_invalid_schema_retries_once_and_settles_both_costs(tmp_path, monkeypatch):
    probe = OpenRouterProbe("test-key", tmp_path / "budget.sqlite3")
    answers = iter([response('{"ok":"wrong"}', "first"), response('{"ok":true}', "second")])
    monkeypatch.setattr(probe, "_post", lambda body: next(answers))
    receipt = probe.complete("system", "{}", request_id="one", json_mode=True, schema_json=SCHEMA)
    assert receipt["schema_valid"] is True
    assert [item["provider_request_id"] for item in receipt["attempts"]] == ["first", "second"]
    assert receipt["cost_with_vat_reserve_usd"] == "0.002"
    assert probe.summary() == {
        "limit_usd": "5.00",
        "calls": 1,
        "unsettled_calls": 0,
        "committed_usd": "0.002",
    }


def test_invalid_json_retries_once_then_returns_existing_failure_path(tmp_path, monkeypatch):
    probe = OpenRouterProbe("test-key", tmp_path / "budget.sqlite3")
    attempts = []

    def invalid(body):
        attempts.append(body)
        return response("not-json", str(len(attempts)))

    monkeypatch.setattr(probe, "_post", invalid)
    receipt = probe.complete("system", "{}", request_id="one", json_mode=True, schema_json=SCHEMA)
    assert len(attempts) == 2
    assert receipt["schema_valid"] is False
    assert receipt["content"] == "not-json"
    assert probe.summary()["committed_usd"] == "0.002"


def test_budget_guard_reserves_before_network(tmp_path, monkeypatch):
    probe = OpenRouterProbe("test-key", tmp_path / "budget.sqlite3")
    receipt = json.dumps({"cost_with_vat_reserve_usd": "0.01"})
    with sqlite3.connect(probe.ledger) as db:
        db.executemany(
            "INSERT INTO probe_calls VALUES (?,?,?,?)",
            ((str(i), canonical_hash(i), "0.01", receipt) for i in range(500)),
        )
    monkeypatch.setattr(probe, "_post", lambda body: pytest.fail("network call escaped cap"))
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        probe.complete("system", "{}", request_id="new", json_mode=True, schema_json=SCHEMA)


def test_prefetch_is_bounded_and_returns_source_order():
    packets = [{"untrusted_document_data": {"source_id": str(i)}} for i in range(5)]
    active = peak = 0
    lock = Lock()

    def invoke(packet):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02 if packet["untrusted_document_data"]["source_id"] == "0" else 0.005)
        with lock:
            active -= 1
        return packet["untrusted_document_data"]["source_id"]

    assert list(prefetch_packets(packets, invoke, max_workers=2).items()) == [
        (str(i), str(i)) for i in range(5)
    ]
    assert peak == 2
