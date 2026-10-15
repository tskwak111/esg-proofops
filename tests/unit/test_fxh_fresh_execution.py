"""Regression boundaries from E15: wire size, unlocated inventory and output cap."""

import json
from dataclasses import replace

import pytest
from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import FINALS_I24_POLICY
from proofops.application.fxh_policy import POLICY
from proofops.domain.provenance import canonical_hash


def test_fxh_wire_budget_is_opt_in_and_keeps_hard_bound(tmp_path):
    probe = OpenAIProbe("offline", tmp_path / "ledger.db")
    text = "x" * 20000
    with pytest.raises(ValueError, match="PROBE_REQUEST_TOO_LARGE"):
        probe.request_body("system", text, request_id="test")
    policy = FINALS_I24_POLICY | dict(fxh_runtime=POLICY)
    probe.configure_response_policy(
        dict(
            analysis_profile_policy=policy,
            analysis_profile_policy_sha256=canonical_hash(policy),
            tenant_id="tenant",
            document=dict(sha256="a" * 64),
        ),
        role="elements",
    )
    assert probe.request_body("system", text, request_id="test")
    from proofops.application.tagging.c3_request_binding import POLICY as C3_BINDING

    assert canonical_hash(probe.wire_policy) == C3_BINDING["model_sha256"]
    with pytest.raises(ValueError, match="PROBE_REQUEST_TOO_LARGE"):
        probe.request_body("system", "x" * 33000, request_id="test")
    probe.configure_response_policy(dict(analysis_profile_policy={}), role="elements")
    with pytest.raises(ValueError, match="PROBE_REQUEST_TOO_LARGE"):
        probe.request_body("system", text, request_id="test")


def test_fxh_pin_is_selectable_but_never_becomes_the_default():
    from proofops.application import analysis_profile as profiles

    assert (
        profiles.publication_policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FXH_POLICY)
        )
        == profiles.FXH_POLICY
    )

    assert profiles.policy_for(profiles.V2_PROFILE) != profiles.FXH_POLICY
    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I25_POLICY)
        )
        == profiles.FINALS_I25_POLICY
    )
    assert (
        profiles.policy_for(profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FXH_POLICY))
        == profiles.FXH_POLICY
    )


def test_fxh_current_c3_keeps_authenticated_wire_binding(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import FXH_POLICY

    from tests.unit import test_fxb_c3_transport

    monkeypatch.setattr(test_fxb_c3_transport, "FINALS_I22_POLICY", FXH_POLICY)
    recorded = test_fxb_c3_transport.recorded.__wrapped__(tmp_path)
    test_fxb_c3_transport.test_fresh_authentication_requires_matching_ledger_and_raw_provider_sidecar(
        recorded
    )


def test_c3_original_page_mapping_retains_claim_scope_and_restores_default(tmp_path):
    from types import SimpleNamespace

    from proofops.adapters.local.upstage import UpstageProbe
    from proofops_api.hosted_ocr import HostedOCRStore

    ledger = tmp_path / "upstage.sqlite3"
    UpstageProbe("offline", ledger)
    store = HostedOCRStore(
        ledger,
        tmp_path / "spend.json",
        store=SimpleNamespace(run_options=lambda job: dict(claim_pages=[36])),
        job=dict(tenant_id="tenant", pages=json.dumps([24, 32, 36])),
        local_run_id="run",
    )
    with pytest.raises(ValueError, match="OCR_CLAIM_FALLBACK_SCOPE_INVALID"):
        with store.claim_fallback_scope(36):
            pass
    with store.original_page_scope():
        with store.claim_fallback_scope(36):
            assert store._fallback.active is True
        for page in (24, 32, 3, 99, True):
            with pytest.raises(ValueError, match="OCR_CLAIM_FALLBACK_SCOPE_INVALID"):
                with store.claim_fallback_scope(page):
                    pass
    assert store._fallback_pages == {3}
    with store.claim_fallback_scope(3):
        assert store._fallback.active is True
    with pytest.raises(ValueError, match="OCR_CLAIM_FALLBACK_SCOPE_INVALID"):
        with store.claim_fallback_scope(36):
            pass
    assert store.usage()["calls"] == 0


def test_fxh_unlocated_inventory_is_uninspected_not_tag_input_failure(tmp_path):
    from proofops.application.tagging.element_inventory import build_inventory, plan_inventory

    from tests.acceptance.test_tagging import setup
    from tests.integration.test_sc1_scope import responder, selection

    inputs = setup(tmp_path)
    graph = inputs["original"]
    selected = selection(inputs)
    block = graph.blocks[0]
    # Valid fusion-v3 blocks may retain invalid native geometry with bbox=None.
    candidate = block.candidates[block.winner]
    candidate = replace(candidate, source=replace(candidate.source, native_bbox=(-1, 0, 20, 20)))
    bad = replace(block, candidates=(candidate,))
    graph = replace(graph, blocks=(bad, *graph.blocks[1:]))
    from dataclasses import asdict

    selected["graph_sha256"] = canonical_hash(asdict(graph))
    with pytest.raises(ValueError):
        plan_inventory(graph, selected)
    selected["fxh_inventory_execution"] = POLICY
    plan = plan_inventory(graph, selected)
    assert any("BLOCK_UNLOCATED:" + bad.source_id in p["errors"] for p in plan["pages"])
    assert all(
        s["source_ref"]["source_id"] != bad.source_id for c in plan["chunks"] for s in c["spans"]
    )
    result = build_inventory(graph, selected, model_sha256="a" * 64, invoke=responder)
    assert (
        next(p for p in result["pages"] if p["physical_page"] == bad.page_num)["status"]
        == "uninspected"
    )


def test_fxh_sc1_output_bound_and_policy_identity(tmp_path, monkeypatch):
    from proofops.application.tagging.element_inventory import inventory_request, plan_inventory
    from proofops.application.tagging.i24_inventory import transport_request

    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection

    live, inputs, _, _ = runtime(tmp_path, monkeypatch)
    selected = selection(inputs) | dict(fxh_inventory_execution=POLICY)
    req = inventory_request(
        plan_inventory(live.graph, selected)["chunks"][0], 1, live.settings.model_sha256
    )
    wrapped = transport_request(req, replace(live.settings, max_tokens=4096))
    assert wrapped["max_tokens"] == 4096
    assert canonical_hash(json.loads(wrapped["user_json"])) == canonical_hash(req)


def test_fxh_composed_receipt_replays_and_rejects_nested_tampering(tmp_path, monkeypatch):
    from proofops.adapters.local import fxh_claim_source

    from tests.integration import test_i24_source

    monkeypatch.setattr(test_i24_source, "current", fxh_claim_source)
    test_i24_source.test_composed_replay_uses_retained_pixels_and_rejects_rewritten_receipt(
        tmp_path, monkeypatch
    )


def test_fxh_invalid_settled_chunk_continues_without_absence(tmp_path, monkeypatch):
    from proofops_worker.sc1_inventory import load_inventory

    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection

    live, inputs, calls, _ = runtime(tmp_path, monkeypatch)
    post = live.probe._post
    count = 0

    def malformed(body):
        nonlocal count
        count += 1
        reply = post(body)
        if count <= 2:  # both schema attempts for the first replica are settled
            reply["choices"][0]["message"]["content"] = "{"
        return reply

    monkeypatch.setattr(live.probe, "_post", malformed)
    selected = selection(inputs) | dict(fxh_inventory_execution=POLICY)
    result = load_inventory(live, live.graph, selected)
    assert len(calls) == 4
    assert result["completed_calls"] == 2
    assert all(p["status"] == "uninspected" for p in result["pages"])
    assert live.probe.summary()["unsettled_calls"] == 0


@pytest.mark.parametrize("failure", ["budget", "authorization", "lease"])
def test_fxh_still_stops_on_safety_fences(tmp_path, monkeypatch, failure):
    from proofops.application.budget import BudgetExceeded
    from proofops_worker.sc1_inventory import load_inventory

    from tests.integration.test_i24_inventory import runtime
    from tests.integration.test_sc1_scope import selection

    live, inputs, calls, _ = runtime(tmp_path, monkeypatch)

    def deny(*a, **kw):
        raise BudgetExceeded("offline denied")

    if failure == "budget":
        live.runner.store.usage.reserve_budget = deny
    elif failure == "authorization":
        live._authorize = deny
    else:
        live._check_heartbeat = deny
    result = load_inventory(
        live, live.graph, selection(inputs) | dict(fxh_inventory_execution=POLICY)
    )
    assert calls == [] and result["completed_calls"] == 0
    assert all(p["status"] == "uninspected" for p in result["pages"])


def test_fxh_roi_reuse_preserves_pixels_and_is_scoped(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from proofops.adapters.local import fxh_claim_source as fxh
    from proofops.adapters.local import source_h7

    from tests.integration.test_claim_source_verification import inputs

    source, graph, _ = inputs()
    reads = []
    monkeypatch.setattr(source_h7, "_ocr", lambda png: reads.append(png) or dict(text="exact"))
    page = SimpleNamespace(page_number=1, width=600, height=800)
    box = (70, 60, 300, 100)
    original = fxh.source_fxe.RasterReader(source)
    expected = original.read(page, box)
    original.close()
    fxh.raster.clear()
    token = fxh.raster._pool.set(None)
    try:
        for tenant, run in (
            (graph.tenant_id, "one"),
            (graph.tenant_id, "one"),
            (graph.tenant_id, "two"),
            ("other", "one"),
        ):
            with fxh.raster.scope(tenant, run, fxh.claim_source_policy()):
                reader = fxh._ScopedFXERaster(source)
                assert reader.read(page, box) == expected
                reader.close()
        assert len(reads) == 4  # original + three distinct tenant/run scopes
        assert len(set(reads)) == 1  # exactly the same rendered PNG
    finally:
        fxh.raster._pool.reset(token)
        fxh.raster.clear()
