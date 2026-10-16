"""SC1 optional recovery uses the actual scheduler, broker, transport and receipts."""

import json
from dataclasses import replace

import pytest
from proofops.adapters.local.i27_inventory_execution import Failures, request_scope
from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency
from proofops.application.analysis_profile import FINALS_I27_POLICY
from proofops.application.i27_inventory import POLICY
from proofops.domain.provenance import canonical_hash
from proofops_worker.sc1_inventory import load_inventory

from tests.integration.test_i24_inventory import runtime
from tests.integration.test_sc1_scope import selection
from tests.test_t1_403_retry import costs, setup


def configured_probe(tmp_path, monkeypatch, *, cap=".50"):
    store, auth, job, probe, sleeps = setup(tmp_path, monkeypatch, cap=cap)
    probe.configure_response_policy(
        dict(
            tenant_id=auth.tenant_id,
            document=dict(sha256="a" * 64),
            analysis_profile_policy=FINALS_I27_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_I27_POLICY),
        ),
        role="extract",
    )
    gate = RoleProviderConcurrency(
        2, requests_per_second=8, resilience_directory=tmp_path / "events"
    )
    gate.bind(probe)
    return store, probe, gate, sleeps


@pytest.mark.parametrize(
    "kind,physical,retries", [("recover", 2, 1), ("exhaust", 2, 1), ("timeout", 1, 0)]
)
def test_brokered_transient_attempts_retain_uncertain_money(
    tmp_path, monkeypatch, kind, physical, retries
):
    store, probe, gate, sleeps = configured_probe(tmp_path, monkeypatch)
    bodies = []
    from tests.test_ops2 import response

    def post(body):
        bodies.append(body)
        if kind == "recover" and len(bodies) == 2:
            return response(body)
        if kind == "timeout":
            raise TimeoutError("private timeout")
        raise ValueError("OPENAI_HTTP_503")

    probe.post = post
    failures = Failures()
    with request_scope(
        POLICY, dict(request_id="request", packet_sha256="a" * 64, replicate_id=3), failures
    ) as context:
        if kind == "recover":
            assert probe.complete("JSON", "{}", request_id="request", json_mode=True)[
                "schema_valid"
            ]
        else:
            with pytest.raises(ValueError, match="PROVIDER_PROCESSING_FAILED"):
                probe.complete("JSON", "{}", request_id="request", json_mode=True)
    assert len(bodies) == gate.snapshot()["physical_attempts"] == physical
    assert all(body == bodies[0] for body in bodies)
    assert context["retries"] == retries
    assert sleeps == ([1] if retries else [])
    rows = costs(store)
    assert [row[1] for row in rows] == (
        ["accounting_pending", "settled"]
        if kind == "recover"
        else ["accounting_pending"] * physical
    )
    assert len({row[0] for row in rows}) == physical
    assert failures.summary()["optional_failed_calls"] == (1 if kind == "recover" else physical)


@pytest.mark.parametrize(
    "code", ["OPENAI_HTTP_429", "OPENAI_HTTP_403", "OPENAI_HTTP_401", "billing"]
)
def test_nontransient_failures_not_reclassified_or_retried(tmp_path, monkeypatch, code):
    _, probe, gate, sleeps = configured_probe(tmp_path, monkeypatch)
    error = ValueError("OPENAI_HTTP_503" if code == "billing" else code)
    if code == "billing":
        error.provider_error_code = "billing_not_active"
    probe.post = lambda body: (_ for _ in ()).throw(error)
    failures = Failures()
    with request_scope(
        POLICY, dict(request_id="request", packet_sha256="a" * 64, replicate_id=1), failures
    ):
        with pytest.raises(ValueError):
            probe.complete("JSON", "{}", request_id="request", json_mode=True)
    assert gate.snapshot()["physical_attempts"] == 1
    assert failures.summary()["optional_failed_calls"] == 0
    assert sleeps == []


def test_inventory_failed_chunk_has_reason_other_chunks_continue_and_cold_replay(
    tmp_path, monkeypatch
):
    from tests.integration.test_claim_source_v3 import synthetic

    (tmp_path / "inventory").mkdir()
    (tmp_path / "hosted").mkdir()
    live, inputs, calls, events = runtime(tmp_path / "inventory", monkeypatch)
    store, probe, gate, _ = configured_probe(tmp_path / "hosted", monkeypatch)
    _, graph, _ = synthetic("scope " * 2100)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    live.graph = graph
    # Exercise optional recovery without deadline (the separate RB3 tests cover it).
    live.snapshot["analysis_profile_policy"].update(i27_sc1_optional_transient=POLICY)
    live.probe = probe
    from tests.integration.test_sc1_scope import responder

    observed = []
    failed_packet = []

    def post(body):
        request = json.loads(body["messages"][1]["content"])
        observed.append(request)
        if not failed_packet:
            failed_packet.append(request["packet_sha256"])
        if request["packet_sha256"] == failed_packet[0] and request["replicate_id"] == 3:
            raise ValueError("OPENAI_HTTP_503")
        return dict(
            id="reply-" + request["request_id"],
            model="gpt-6-luna",
            usage=dict(prompt_tokens=100, completion_tokens=50),
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(content=responder(request)["raw_response_json"]),
                )
            ],
        )

    probe.post = post
    selected = selection(inputs | dict(original=graph))
    inventory = load_inventory(live, graph, selected)
    assert inventory["planned_calls"] == 9
    assert inventory["completed_calls"] == 8
    assert len(observed) == 10
    assert len([c for c in inventory["chunks"] if c["errors"]]) == 1
    failed = [v for v in inventory["raw_responses"].values() if v.get("status") == "failed"]
    assert len(failed) == 1 and failed[0]["reason"] == "SC1_OPTIONAL_TRANSIENT_UNINSPECTED"
    assert failed[0]["i27_sc1_failure"]["degraded"]
    assert len([r for r in costs(store) if r[1] == "accounting_pending"]) == 2
    live.probe.i27_inventory_failures = Failures()
    assert load_inventory(live, graph, selected) == inventory
    assert len(observed) == 10
    assert live.usage["i27_sc1_failures"]["optional_failed_calls"] == 2


@pytest.mark.parametrize("kind", ["exhaust", "timeout"])
def test_hosted_optional_sc1_failure_completes_with_uncertain_costs(tmp_path, monkeypatch, kind):
    from tests import test_hosted_hx2 as fixture
    from tests.test_hosted_public import settings

    generator = fixture.fake_llm
    requests = []

    def fail_inventory(body):
        request = json.loads(body["messages"][1]["content"])
        # CF1 compacts the wire; chunk/request IDs remain in authenticated receipts.
        if "spans" in request.get("untrusted_document_data", {}) and request.get("packet_sha256"):
            requests.append((request["packet_sha256"], request["replicate_id"]))
            if kind == "timeout":
                raise TimeoutError("offline SC1 timeout")
            raise ValueError("OPENAI_HTTP_503")
        return generator(body)

    monkeypatch.setattr(fixture, "fake_llm", fail_inventory)
    fixture.test_public_default_upload_binding_parse_extract_tag_publication(
        settings.__wrapped__(tmp_path), tmp_path, monkeypatch
    )
    outcome = json.loads((tmp_path / "worker/state/outcome.json").read_text())
    assert requests
    assert outcome["status"] == "completed"
    failures = outcome["provider_failures"]
    assert failures["optional_inventory_failures"] == failures["failed_calls"] > 0
    assert failures["unresolved_total"] == 0
    assert outcome["ops2_provider_fallback"]["triggered_by"] is None
    assert all(r["degraded"] for r in outcome["i27_sc1_failures"]["requests"])


def test_retry_rechecks_budget_and_cannot_degrade_a_money_stop(tmp_path, monkeypatch):
    from proofops.application.budget import BudgetExceeded

    store, probe, gate, _ = configured_probe(tmp_path, monkeypatch, cap=".015")
    probe.post = lambda body: (_ for _ in ()).throw(ValueError("OPENAI_HTTP_503"))
    failures = Failures()
    with request_scope(
        POLICY, dict(request_id="budget", packet_sha256="a" * 64, replicate_id=1), failures
    ) as context:
        with pytest.raises(BudgetExceeded):
            probe.complete("JSON", "{}", request_id="budget", json_mode=True)
    assert gate.snapshot()["physical_attempts"] == 1
    assert context["terminal_code"] is None
    assert [r[1] for r in costs(store)] == ["accounting_pending"]
