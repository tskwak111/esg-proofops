"""S5 execution-only and current C3 schema regressions; no network."""

from copy import deepcopy

import pytest
from proofops.application.analysis_profile import FINALS_I26_POLICY
from proofops.application.tagging.c3_request_binding import current_request, request_binding


def test_opt_in_c3_transmits_the_schema_it_validates(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import S5_LIVE_POLICY

    from tests.unit import test_fxb_c3_transport as checks

    monkeypatch.setattr(checks, "FINALS_I22_POLICY", S5_LIVE_POLICY)
    request, result, probe = checks.recorded.__wrapped__(tmp_path)
    assert request["schema_json"] in request["system"]
    checks.test_fresh_authentication_requires_matching_ledger_and_raw_provider_sidecar(
        (request, result, probe)
    )
    assert (
        request_binding(request)["prompt_sha256"]
        != request_binding(current_request(request["identity"], "claim", [], FINALS_I26_POLICY, 1))[
            "prompt_sha256"
        ]
    )


@pytest.mark.parametrize(
    "change",
    [
        "content",
        "provider_id",
        "request_id",
        "wire_sha256",
        "schema_sha256",
        "analysis_policy_sha256",
        "model",
        "signature",
        "missing_ledger",
        "raw_sidecar",
    ],
)
def test_new_c3_binding_retains_all_transport_guards(tmp_path, monkeypatch, change):
    from proofops.application.analysis_profile import S5_LIVE_POLICY

    from tests.unit import test_fxb_c3_transport as checks

    monkeypatch.setattr(checks, "FINALS_I22_POLICY", S5_LIVE_POLICY)
    checks.test_transport_cannot_authenticate_edited_or_unbound_responses(
        checks.recorded.__wrapped__(tmp_path), change
    )


def test_old_c3_requests_keep_the_original_wire_and_new_opt_in_rejects_tampering():
    from proofops.application.analysis_profile import S5_LIVE_POLICY
    from proofops.application.tagging.c3_request_binding import POLICY, SYSTEM

    from tests.unit.test_c2_assembly import case

    inputs, votes = case()
    args = (
        votes[0]["identity"],
        inputs["context"].claim.quote,
        inputs["packet"].to_dict()["c2_sources"],
    )
    old = current_request(*args, FINALS_I26_POLICY, 1)
    assert old["system"] == SYSTEM
    assert request_binding(old)["prompt_sha256"] == POLICY["prompt_sha256"]
    bad = deepcopy(S5_LIVE_POLICY)
    bad["s5_c3_response_binding"]["schema_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="S5_C3_BINDING_POLICY_MISMATCH"):
        current_request(*args, bad, 1)


def test_inventory_parallel_execution_preserves_every_response_and_replays(tmp_path):
    from threading import Barrier

    from proofops.adapters.local.s5_inventory_execution import build_inventory
    from proofops.application.tagging.element_inventory import build_inventory as serial
    from proofops.application.tagging.element_inventory import replay_inventory

    from tests.acceptance.test_tagging import setup
    from tests.integration.test_sc1_scope import responder, selection

    inputs = setup(tmp_path)
    from dataclasses import replace

    from tests.integration.test_claim_source_v3 import synthetic

    _, graph, _ = synthetic("scope " * 2100)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    selected = selection(inputs | dict(original=graph))
    expected = serial(graph, selected, model_sha256="a" * 64, invoke=responder)
    barrier = Barrier(3)

    seen = {}

    def concurrent(request):
        key = request["packet_sha256"]
        seen.setdefault(key, []).append(request["replicate_id"])
        barrier.wait(timeout=5)
        return responder(request)

    actual = build_inventory(
        graph, selected, model_sha256="a" * 64, invoke=concurrent, max_workers=3
    )
    assert actual == expected == replay_inventory(actual, graph)
    assert len(seen) == 3 and all(v == [1, 2, 3] for v in seen.values())


@pytest.mark.parametrize("failure", ["budget", "authorization", "lease"])
def test_parallel_inventory_still_stops_at_safety_fences(tmp_path, monkeypatch, failure):
    from proofops.application.analysis_profile import S5_LIVE_POLICY
    from proofops.application.budget import BudgetExceeded
    from proofops_worker.sc1_inventory import load_inventory

    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection

    live, inputs, calls, _ = runtime(tmp_path, monkeypatch)
    live.snapshot["analysis_profile_policy"] = S5_LIVE_POLICY
    live.runner.max_workers = 4

    def deny(*a, **kw):
        raise BudgetExceeded("offline denied")

    if failure == "budget":
        live.runner.store.usage.reserve_budget = deny
    elif failure == "authorization":
        live._authorize = deny
    else:
        live._check_heartbeat = deny
    result = load_inventory(live, live.graph, selection(inputs))
    assert calls == [] and result["completed_calls"] == 0
    assert all(p["status"] == "uninspected" for p in result["pages"])


def test_new_c3_three_distinct_authenticated_votes_publish_and_replay(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import S5_LIVE_POLICY

    from tests.unit import test_fxb_current_c3 as checks

    monkeypatch.setattr(checks, "FINALS_I22_POLICY", S5_LIVE_POLICY)
    inputs = checks.reviewed_case.__wrapped__(monkeypatch)
    checks.test_three_fresh_current_responses_can_still_publish(inputs, tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        "prompt_sha256",
        "packet_sha256",
        "request_sha256",
        "authenticated",
        "fresh_model_call",
        "replay",
        "missing_receipt",
        "saved_response",
        "cache_reuse",
    ],
)
def test_new_c3_never_confirms_reused_or_unbound_votes(tmp_path, monkeypatch, change):
    from proofops.application.analysis_profile import S5_LIVE_POLICY

    from tests.unit import test_fxb_current_c3 as checks

    monkeypatch.setattr(checks, "FINALS_I22_POLICY", S5_LIVE_POLICY)
    inputs = checks.reviewed_case.__wrapped__(monkeypatch)
    checks.test_current_transport_or_response_binding_mismatch_cannot_publish(
        inputs, tmp_path, change
    )


def test_inventory_fatal_stop_bounds_inflight_and_suppresses_later_windows(tmp_path):
    from threading import Event

    from proofops.adapters.local.s5_inventory_execution import build_inventory
    from proofops.application.tagging.element_inventory import replay_inventory

    from tests.acceptance.test_tagging import setup
    from tests.integration.test_sc1_scope import selection

    inputs = setup(tmp_path)
    graph, selected = inputs["original"], selection(inputs)
    # Split the existing content into additional independent page chunks without
    # introducing evidence. Failed responses keep the selected page uninspected.
    from proofops.application.fxh_policy import POLICY

    selected = selected | dict(fxh_inventory_execution=POLICY)
    # A one-worker stop is also the exact historical serial failure boundary.
    stopped = Event()
    calls = []

    def fail(request):
        calls.append(request)
        stopped.set()
        raise ValueError("PROVIDER_PROCESSING_FAILED")

    result = build_inventory(
        graph, selected, model_sha256="a" * 64, invoke=fail, max_workers=1, stopped=stopped.is_set
    )
    assert len(calls) == 1
    assert result["completed_calls"] == 0 and len(result["raw_responses"]) == 3
    assert result == replay_inventory(result, graph)


def test_parallel_hosted_chunks_keep_separate_money_and_response_receipts(tmp_path, monkeypatch):
    import json
    from dataclasses import replace
    from threading import Barrier

    from proofops.application.analysis_profile import S5_LIVE_POLICY
    from proofops_worker.sc1_inventory import load_inventory

    from tests.integration.test_claim_source_v3 import synthetic
    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection

    live, inputs, calls, events = runtime(tmp_path, monkeypatch)
    _, graph, _ = synthetic("scope " * 2100)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    live.graph = graph
    live.snapshot["analysis_profile_policy"] = S5_LIVE_POLICY
    live.runner.max_workers = 3
    barrier, post = Barrier(3), live.probe._post

    def concurrent(body):
        barrier.wait(timeout=5)
        return post(body)

    monkeypatch.setattr(live.probe, "_post", concurrent)
    selected = selection(inputs | dict(original=graph))
    result = load_inventory(live, graph, selected)
    assert result["planned_calls"] == result["completed_calls"] == len(calls) == 9
    requests = [json.loads(body["messages"][1]["content"]) for body in calls]
    assert len({r["request_id"] for r in requests}) == 9
    assert len({r["provider_response_id"] for r in result["raw_responses"].values()}) == 9
    for name in ("reserve", "dispatch", "settle"):
        assert len([e for e in events if isinstance(e, tuple) and e[0] == name]) == 9
    assert live.probe.summary()["unsettled_calls"] == 0
    assert len(list((live.receipts / "sc1-inventory").glob("*/response.json"))) == 9
    assert load_inventory(live, graph, selected) == result
    assert len(calls) == 9


def test_s5_keeps_occurrence_groups_and_table_source_annotations(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import S5_LIVE_POLICY

    from tests.unit import test_i9_historical_publication as checks

    monkeypatch.setattr(checks, "FINALS_I8_POLICY", S5_LIVE_POLICY)
    checks.test_v8_duplicate_occurrences_survive_v9_default(tmp_path, monkeypatch)
