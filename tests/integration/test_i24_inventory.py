"""Offline actual transport/ledger/receipt exercise; HTTP and grant are explicit fixtures."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.budget import BudgetExceeded
from proofops.application.ports.models import ModelBinding
from proofops.application.preflight import Check, Preflight
from proofops.application.tagging.element_inventory import inventory_request, plan_inventory
from proofops.application.tagging.i24_inventory import POLICY, transport_request
from proofops_worker.sc1_inventory import load_inventory

from tests.acceptance.test_tagging import setup
from tests.integration.test_sc1_scope import responder, selection


def runtime(tmp_path, monkeypatch):
    inputs = setup(tmp_path)
    settings = replace(
        inputs["settings"],
        binding=ModelBinding("00000000-0000-4000-8000-000000000001", "tagger", False),
        model_id="gpt-6-luna",
        model_profile="upstage-compact-evidence-ids-v1",
        region="provider-managed-unverified",
        wire_policy_version=2,
    )
    from proofops_agent.upstage_tagging import MODEL_PROFILE

    settings = replace(settings, model_profile=MODEL_PROFILE)
    probe = OpenAIProbe("fake-offline", tmp_path / "budget.sqlite3")
    calls, events = [], []

    def post(body):
        calls.append(body)
        req = json.loads(body["messages"][1]["content"])
        content = responder(req)["raw_response_json"]
        return dict(
            id="fixture-" + req["request_id"],
            model="gpt-6-luna",
            usage=dict(prompt_tokens=100, completion_tokens=50, prompt_tokens_details={}),
            choices=[dict(finish_reason="stop", message=dict(content=content))],
        )

    monkeypatch.setattr(probe, "_post", post)
    allowed = set()

    def authorize(settings, request):
        assert (request["claim_id"], request["packet_sha256"]) in allowed
        events.append("authorize")
        return Preflight(
            True,
            tuple(
                Check(n, "pass", "offline fixture")
                for n in (
                    "runtime_approval",
                    "consent_approval",
                    "model_binding",
                    "document_scope",
                    "document_rights",
                    "data_consent",
                    "tagging_settings",
                    "selected_document_rights",
                )
            ),
            "a" * 64,
            "2026-10-15T00:00:00Z",
        )

    usage = SimpleNamespace(
        reserve_budget=lambda call, **kw: events.append(("reserve", call, kw)) or True,
        mark_dispatched=lambda call: events.append(("dispatch", call)) or True,
        record_usage=lambda call, usage, **kw: events.append(("settle", call, usage)),
    )
    live = SimpleNamespace(
        snapshot=dict(analysis_profile_policy=dict(sc1_inventory_transport=POLICY)),
        graph=inputs["original"],
        settings=settings,
        usage={},
        probe=probe,
        receipts=tmp_path / "receipts",
        resume=None,
        heartbeat_state=None,
        _fence=lambda: events.append("fence"),
        _check_heartbeat=lambda: None,
        _capacity=lambda model: 32768,
        _authorize=authorize,
        allow_packet=lambda claim, packet: allowed.add((claim, packet)),
        account=lambda request: events.append(("account", request)),
        runner=SimpleNamespace(store=SimpleNamespace(usage=usage), clock=lambda: 1),
    )
    return live, inputs, calls, events


def test_actual_wire_receipts_budget_and_immutable_resume(tmp_path, monkeypatch):
    live, inputs, calls, events = runtime(tmp_path, monkeypatch)
    selected = selection(inputs)
    inventory = load_inventory(live, live.graph, selected)
    assert inventory["completed_calls"] == inventory["planned_calls"] == len(calls) == 3
    assert len({v["provider_response_id"] for v in inventory["raw_responses"].values()}) == 3
    assert len([e for e in events if isinstance(e, tuple) and e[0] == "reserve"]) == 3
    for e in events:
        if isinstance(e, tuple) and e[0] == "reserve":
            assert e[2]["max_output_tokens"] == 2 * min(live.settings.max_tokens, 1024)
    assert load_inventory(live, live.graph, selected) == inventory
    assert len(calls) == 3
    assert len(list((live.receipts / "sc1-inventory").glob("*/response.json"))) == 3
    assert live.probe.summary()["unsettled_calls"] == 0
    assert live.usage["sc1_inventory_plan"]["completed_calls"] == 3


@pytest.mark.parametrize("failure", ["budget", "authorization", "lease"])
def test_inventory_failure_stops_dispatch_and_remains_uninspected(tmp_path, monkeypatch, failure):
    live, inputs, calls, events = runtime(tmp_path, monkeypatch)

    def deny(*a, **kw):
        raise BudgetExceeded("offline denied")

    if failure == "budget":
        live.runner.store.usage.reserve_budget = deny
    elif failure == "authorization":
        live._authorize = deny
    else:
        live._check_heartbeat = deny
    inventory = load_inventory(live, live.graph, selection(inputs))
    assert calls == [] and inventory["completed_calls"] == 0
    assert all(p["status"] == "uninspected" for p in inventory["pages"])
    assert not inventory["candidates"]


def test_call_plan_limit_has_no_partial_spend(tmp_path, monkeypatch):
    live, inputs, calls, events = runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "proofops_worker.sc1_inventory.plan_inventory", lambda *a: dict(chunks=[{}] * 101)
    )
    with pytest.raises(BudgetExceeded, match="SC1_INVENTORY_LIMIT_EXCEEDED"):
        load_inventory(live, live.graph, selection(inputs))
    assert calls == []
    assert not any(isinstance(e, tuple) and e[0] == "reserve" for e in events)


@pytest.mark.parametrize(
    "provider_origin",
    [
        dict(saved_response_origin=dict(replay=True, fresh_model_call=False)),
        dict(response_reuse=dict(source_request_id="previous-request")),
    ],
)
def test_request_pin_and_replay_origin_are_not_fresh_votes(tmp_path, monkeypatch, provider_origin):
    live, inputs, _, _ = runtime(tmp_path, monkeypatch)
    chunk = plan_inventory(live.graph, selection(inputs))["chunks"][0]
    req = inventory_request(chunk, 1, live.settings.model_sha256)
    with pytest.raises(ValueError, match="SC1_REQUEST_MISMATCH"):
        transport_request(req | dict(prompt_sha256="b" * 64), live.settings)
    from proofops.application.tagging.grade_required_agreement_policy import DEFAULT_POLICY

    from tests.integration.test_sc1_scope import analyze, case

    (tmp_path / "scope").mkdir()
    inputs, runs, inv = case(tmp_path / "scope")
    record = analyze(inputs, runs, inv, grade_agreement_policy=DEFAULT_POLICY.to_dict())
    assert record["grade_required_agreement_policy_sha256"] == DEFAULT_POLICY.sha256
    replayed = tuple(
        replace(
            r,
            provider_response_json=json.dumps(provider_origin),
        )
        for r in runs
    )
    assert (
        analyze(inputs, replayed, inv, grade_agreement_policy=DEFAULT_POLICY.to_dict())[
            "sc1_confirmation"
        ]
        is None
    )


def test_qt2_preindexed_inventory_rejects_other_graph(tmp_path, monkeypatch):
    from proofops.application.tagging.analysis_scope import InventoryIndex
    from proofops.application.tagging.qt2_inventory import link_inventory

    live, inputs, _, _ = runtime(tmp_path, monkeypatch)
    selected = selection(inputs)
    index = InventoryIndex(load_inventory(live, live.graph, selected), live.graph)
    with pytest.raises(ValueError, match="QT2_INVENTORY_GRAPH_MISMATCH"):
        link_inventory(
            None,
            index,
            replace(live.graph),
            run_id=selected["run_id"],
            tenant_id=live.graph.tenant_id,
            rulepack=None,
        )


def test_inventory_cached_response_is_not_fresh(tmp_path, monkeypatch):
    from proofops_agent.sc1_inventory import SC1InventoryTransport

    live, inputs, calls, _ = runtime(tmp_path, monkeypatch)
    invoke = SC1InventoryTransport.invoke

    def reused(self, request):
        response = invoke(self, request)
        provider = json.loads(response.provider_response_json)
        provider["response_reuse"] = dict(source_request_id="previous-request")
        return replace(response, provider_response_json=json.dumps(provider))

    monkeypatch.setattr(SC1InventoryTransport, "invoke", reused)
    inventory = load_inventory(live, live.graph, selection(inputs))
    assert len(calls) == 3
    assert inventory["completed_calls"] == 0
    assert not inventory["candidates"]
    assert all(p["status"] == "uninspected" for p in inventory["pages"])
