"""Exact OCR recomputation reuse binds every input and coalesces cold readers."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class Graph:
    value: str


def test_complete_input_binding_single_flight_and_mutation_isolation(monkeypatch):
    from proofops.adapters.local.verified_read_cache import POLICY, replay_cached

    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", POLICY["profile"])
    entered, release = threading.Event(), threading.Event()
    calls = []

    def recompute(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        if args[0].get("bad"):
            raise ValueError("INVALID_RECEIPT")
        return {"verified": ["literal"]}

    args = dict(
        reader_name="pa1-test",
        policy={"profile": "v6"},
        receipt={"records": []},
        graph=Graph("graph"),
        source=b"source",
        tenant_id="tenant",
        recompute=recompute,
    )
    with ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(replay_cached, **args) for _ in range(4)]
        assert entered.wait(2)
        release.set()
        results = [f.result(3) for f in futures]
    assert len(calls) == 1
    results[0]["verified"].clear()
    assert replay_cached(**args)["verified"] == ["literal"]
    for change in (
        {"source": b"other"},
        {"tenant_id": "other"},
        {"graph": Graph("other")},
        {"receipt": {"records": [{"status": "unknown"}]}},
        {"policy": {"profile": "v5"}},
        {"discovery": Graph("claims")},
        {"reader_name": "other"},
    ):
        replay_cached(**(args | change))
    assert len(calls) == 8
    monkeypatch.setenv("DEVELOPER_DIR", "/other")
    replay_cached(**args)
    assert len(calls) == 9
    for _ in range(2):
        with pytest.raises(ValueError, match="INVALID_RECEIPT"):
            replay_cached(**(args | {"receipt": {"bad": True}}))
    assert len(calls) == 11


def test_unavailable_receipts_and_unpinned_execution_are_recomputed(monkeypatch):
    from proofops.adapters.local.verified_read_cache import POLICY, replay_cached

    calls = []
    args = dict(
        reader_name="pa1-unavailable",
        policy={},
        receipt={"reason": "fallback_reader_unavailable"},
        graph=Graph("graph"),
        source=b"pdf",
        tenant_id="tenant",
        recompute=lambda *a, **k: calls.append(1) or Graph("unchanged"),
    )
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", POLICY["profile"])
    replay_cached(**args)
    replay_cached(**args)
    assert len(calls) == 2
    monkeypatch.delenv("PROOFOPS_VERIFIED_READ_CACHE")
    replay_cached(**(args | {"receipt": {}}))
    replay_cached(**(args | {"receipt": {}}))
    assert len(calls) == 4


def test_warm_native_cache_rechecks_current_reader_policy(monkeypatch):
    from types import SimpleNamespace

    from proofops.adapters.local import claim_source_policies
    from proofops.adapters.local.verified_read_cache import POLICY, replay_cached

    current = {"mode": "upstage-ocr-page-v6", "hash": "original"}
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", POLICY["profile"])
    monkeypatch.setattr(
        claim_source_policies,
        "page_ocr_profile",
        lambda _: SimpleNamespace(native_policy=lambda: current),
    )
    args = dict(
        reader_name="native:upstage-ocr-page-v6",
        policy=dict(current),
        receipt={},
        graph=Graph("warm-native"),
        source=b"pdf",
        tenant_id="tenant",
        recompute=lambda *a, **k: Graph("verified"),
    )
    replay_cached(**args)
    current["hash"] = "tampered"
    with pytest.raises(ValueError, match="NATIVE_PARAGRAPH_POLICY_MISMATCH"):
        replay_cached(**args)
