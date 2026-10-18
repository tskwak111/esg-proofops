"""Saved Hyundai retry + real worker/SQLite accounting; provider HTTP is offline."""

import json
import socket
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from uuid import UUID

import pytest
from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.local import openai
from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.service import RawTagResponse
from proofops_worker.live_tagging import LiveTaggingRuntime

SAVED = json.loads(
    (Path(__file__).parents[1] / "fixtures/hf5/hyundai-preliminary-retry.json").read_text()
)


def runtime_for(tmp_path, monkeypatch, *, output_limit=None, model_id="gpt-6-luna"):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(openai, "now", lambda: datetime(2026, 10, 18, tzinfo=UTC))
    request = SAVED["request"]
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.auth = SimpleNamespace(tenant_id=request["tenant_id"])
    runtime.graph = SimpleNamespace(document_version_id=str(UUID(int=801)))
    runtime.snapshot = dict(
        run_id=str(UUID(int=802)),
        input_reservation_policy_hash=request["input_reservation_policy_sha256"],
    )
    runtime.lease = SimpleNamespace(message=SimpleNamespace(job_id=str(UUID(int=803))))
    limits = SAVED["budget_limits"]
    budget = BudgetLimits(
        limits["input_tokens"],
        limits["output_tokens"] if output_limit is None else output_limit,
        tuple(RoleLimit(**r) for r in limits["roles"]),
        limits["max_attempts"],
    )
    store = LocalSQLiteUsageStore(tmp_path / "usage.sqlite3")
    store.create_budget(
        runtime.auth.tenant_id,
        runtime.snapshot["run_id"],
        runtime.graph.document_version_id,
        budget,
    )
    runtime.runner = SimpleNamespace(
        store=SimpleNamespace(
            usage=store,
            jobs=SimpleNamespace(can_call=lambda *a, **k: True, heartbeat=lambda *a, **k: None),
        ),
        clock=lambda: 1792246763,
        max_workers=1,
    )
    runtime.receipts = tmp_path / "receipts"
    runtime.allowed_packets = set()
    runtime.resume = None
    runtime._account_lock = Lock()
    runtime.s2_call_allowance = 2000
    runtime.s2_reserved_calls = set()
    runtime.account = lambda request_id: None
    runtime.probe = openai.OpenAIProbe("offline-only", tmp_path / "probe.sqlite3")
    settings = SimpleNamespace(
        binding=ModelBinding(**request["binding"]),
        model_id=model_id,
        model_profile=request["model_profile"],
        region=request["region"],
        model_sha256="a" * 64,
        rendered_system=request["system_prompt"],
        temperature=request["temperature"],
        max_tokens=request["max_tokens"],
        wire_policy_version=2,
    )
    return runtime, settings, store


def source_calls(runtime, settings, transport, records, *, prefix="preliminary", claim_id=None):
    return runtime._source_replicas(
        prefix,
        SimpleNamespace(claim_id=claim_id or SAVED["request"]["claim_id"]),
        json.loads(SAVED["request"]["user_json"]),
        settings,
        transport,
        records,
        # Accounting replay only: saved classification is not new semantic evidence.
        lambda value: (value, value),
    )


@pytest.mark.parametrize("prefix", ["preliminary", "relation"])
def test_saved_retry_does_not_poison_next_source_replica(tmp_path, monkeypatch, prefix):
    runtime, settings, store = runtime_for(tmp_path, monkeypatch)
    sent = []

    def post(body):
        sent.append(body)
        answer = deepcopy(SAVED["provider_responses"][0 if len(sent) == 1 else 1])
        answer["id"] = f"offline-{len(sent)}"
        return answer

    monkeypatch.setattr(runtime.probe, "_post", post)

    def invoke(request):
        result = runtime.probe.complete(
            SAVED["wire_system"],
            SAVED["wire_user_json"],
            request_id=request["request_id"],
            max_tokens=request["max_tokens"],
            json_mode=True,
        )
        return RawTagResponse(
            result["content"],
            TokenUsage(
                result["input_tokens"],
                result["output_tokens"],
                0,
                0,
                1,
                "succeeded",
                result["provider_request_id"],
            ),
            False,
        )

    transport = SimpleNamespace(
        may_dispatch=lambda: True,
        count_input_tokens=lambda *a, **k: 32768,
        invoke=invoke,
    )
    records = {}
    assert source_calls(runtime, settings, transport, records, prefix=prefix) is not None
    rows = store.cost_data(runtime.auth.tenant_id, runtime.snapshot["run_id"])
    assert len(rows) == 3
    assert sorted(r["ledger"]["usage"]["output_tokens"] for r in rows) == [94, 94, 1118]
    assert all(r["reservation"]["max_output_tokens"] == 2048 for r in rows)
    assert len(sent) == 4
    assert all(body["max_completion_tokens"] == 1024 for body in sent)
    assert runtime.probe.summary()["unsettled_calls"] == 0
    assert "BUDGET_EXHAUSTED" not in json.dumps(records)


def test_178_claim_accounting_replay_has_no_budget_holds(tmp_path, monkeypatch):
    runtime, settings, store = runtime_for(tmp_path, monkeypatch)
    calls = []

    def invoke(request):
        calls.append(request["request_id"])
        return RawTagResponse(
            '{"accounting_replay":true}',
            TokenUsage(6598, 1118 if len(calls) == 1 else 94, 0, 0, 1, "succeeded", calls[-1]),
            False,
        )

    transport = SimpleNamespace(
        may_dispatch=lambda: True,
        count_input_tokens=lambda *a, **k: 32768,
        invoke=invoke,
    )
    records = {}
    for i in range(178):
        assert (
            source_calls(runtime, settings, transport, records, claim_id=str(UUID(int=1000 + i)))
            is not None
        )
    assert len(calls) == 534
    assert "BUDGET_EXHAUSTED" not in json.dumps(records)
    rows = store.cost_data(runtime.auth.tenant_id, runtime.snapshot["run_id"])
    assert len(rows) == 534 and all(r["state"] == "settled" for r in rows)


@pytest.mark.parametrize("fault", ["real_overrun", "unknown_usage", "total_limit"])
def test_source_budget_still_stops_unsafe_calls(tmp_path, monkeypatch, fault):
    runtime, settings, _ = runtime_for(
        tmp_path,
        monkeypatch,
        output_limit=2048 if fault == "total_limit" else None,
    )
    sent = []

    def invoke(request):
        sent.append(request)
        usage = TokenUsage(
            100, 2049 if fault == "real_overrun" else 1, 0, 0, 1, "succeeded", "offline"
        )
        if fault == "unknown_usage":
            usage = replace(
                usage,
                input_tokens=None,
                output_tokens=None,
                status="failed",
                error_code="MODEL_TIMEOUT",
            )
        return RawTagResponse('{"ok":true}', usage, False)

    transport = SimpleNamespace(
        may_dispatch=lambda: True,
        count_input_tokens=lambda *a, **k: 32768,
        invoke=invoke,
    )
    records = {}
    assert source_calls(runtime, settings, transport, records) is None
    assert len(sent) == 1
    if fault != "unknown_usage":
        assert "BUDGET_EXHAUSTED" in json.dumps(records)
    else:
        rows = runtime.runner.store.usage.cost_data(
            runtime.auth.tenant_id, runtime.snapshot["run_id"]
        )
        assert rows[0]["ledger"]["usage"]["output_tokens"] is None
        assert rows[0]["reservation"]["max_output_tokens"] == 2048
