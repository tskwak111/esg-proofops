"""S3_UPX boundaries captured on 0d3b3997 before extracting responsibilities."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from proofops.adapters.local import upstage
from proofops.application.analysis_profile import FINALS_I23_POLICY, QT1_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_agent import upstage_extraction as facade

from tests.integration.test_qt1_pipeline import flags, graph
from tests.integration.test_qt1_pipeline import packet as table_packet
from tests.integration.test_upstage_extraction import (
    FakeProbe,
    _extraction_context_graph,
    make_extractor,
)
from tests.integration.test_upstage_probe import response
from tests.unit.test_ta_a1_boundaries import RECEIPT_GOLDENS, receipt_case

TABLE_GOLDENS = {
    "pb1": "563a499355f88ada4f61ab1a2da3ce33a36b509ba9e8854c70d5db31a3dacee3",
    "qt1": "1041f02cdf33bfd1939860f9476b93c83873c567b6b8d6d873807e46244a172b",
}


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*.json"))}


@pytest.mark.parametrize("mode", list(RECEIPT_GOLDENS))
def test_request_bytes_hashes_outputs_and_replay(tmp_path: Path, mode: str) -> None:
    assert canonical_hash(receipt_case(tmp_path, mode)) == RECEIPT_GOLDENS[mode]


@pytest.mark.parametrize("mode,policy", [("pb1", FINALS_I23_POLICY), ("qt1", QT1_POLICY)])
def test_table_receipt_bytes_outputs_and_replay(
    tmp_path: Path, mode: str, policy: dict[str, Any]
) -> None:
    document = graph("kakao")
    block = next(
        b for b in document.blocks if b.source_id == "329e3926-72d9-5f66-8274-1f75f2251b0a"
    )
    probe = FakeProbe(error=AssertionError("table path must not dispatch"))
    extractor = facade.UpstageClaimExtractor(probe, tmp_path, **flags(policy))
    packet = table_packet(document, block)
    output = extractor.extract(packet, context_graph=document)
    files = _files(tmp_path)
    assert (
        canonical_hash(
            dict(
                output=output,
                receipt_bytes={p: sha256(raw).hexdigest() for p, raw in files.items()},
            )
        )
        == TABLE_GOLDENS[mode]
    )
    assert extractor.extract(packet, context_graph=document) == output
    assert _files(tmp_path) == files
    assert not probe.calls
    assert extractor.usage_checkpoint() == 0
    assert all(p.stat().st_mode & 0o777 == 0o400 for p in tmp_path.rglob("*.json"))


def _observe(
    monkeypatch: pytest.MonkeyPatch, owner: Any, name: str, events: list[str], label: str
) -> None:
    original = getattr(owner, name)

    def call(*args: Any, **kwargs: Any) -> Any:
        events.append(label)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, call)


@pytest.mark.parametrize("outcome", ["ok", "timeout", "truncated", "price"])
def test_receipt_guard_reserve_dispatch_settle_order_and_no_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    probe = upstage.UpstageProbe("offline-test-key", tmp_path / "budget.sqlite3")
    extractor, packet = make_extractor(probe, tmp_path)
    events: list[str] = []
    for name, label in [("request_body", "price"), ("_reserve", "reserve"), ("_settle", "settle")]:
        _observe(monkeypatch, probe, name, events, label)
    write = extractor._write

    def record(path: Path, content: str) -> None:
        events.append("write:" + path.name)
        write(path, content)

    def post(body: dict[str, Any]) -> dict[str, Any]:
        events.append("post")
        assert body["max_tokens"] == 1024
        assert body["response_format"] == {"type": "json_object"}
        assert body["temperature"] == 0 and body["stream"] is False
        if outcome == "timeout":
            raise TimeoutError("private transport detail")
        raw = response()
        raw["choices"][0]["message"]["content"] = '{"claims":[]}'
        if outcome == "truncated":
            raw["choices"][0]["finish_reason"] = "length"
        return raw

    monkeypatch.setattr(extractor, "_write", record)
    monkeypatch.setattr(probe, "_post", post)
    if outcome == "price":

        class ExpiredClock:
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                return upstage.PRICE_RECHECK_AT

        monkeypatch.setattr(upstage, "datetime", ExpiredClock)

    expected = ["write:packet.json", "write:request.json", "price"]
    if outcome != "price":
        expected += ["reserve", "post"]
    if outcome == "ok":
        assert extractor.extract(packet) == {"spans": []}
        expected += ["settle", "write:raw_response.json", "write:result.json"]
    else:
        code = {
            "price": "PRICE_RECHECK_REQUIRED",
            "timeout": "UPSTAGE_REQUEST_FAILED",
            "truncated": "MODEL_OUTPUT_TRUNCATED",
        }[outcome]
        with pytest.raises(ValueError, match="^" + code + "$"):
            extractor.extract(packet)
        expected += ["write:failure.json"]
        if outcome == "truncated":
            # The retained truncation proof also revalidates the request price.
            expected += ["price"]
    assert events == expected
    usage = extractor.usage
    assert usage["model_calls"] == (0 if outcome == "price" else 1)
    assert usage["settled_calls"] == (1 if outcome == "ok" else 0)
    assert usage["unsettled_calls"] == (1 if outcome in {"timeout", "truncated"} else 0)
    before = _files(tmp_path / "receipts")
    events.clear()
    if outcome == "ok":
        assert extractor.extract(packet) == {"spans": []}
    else:
        replay_code = {
            "price": "PRICE_RECHECK_REQUIRED",
            "timeout": "PREVIOUS_TRANSPORT_FAILED",
            "truncated": "MODEL_OUTPUT_TRUNCATED",
        }[outcome]
        with pytest.raises(ValueError, match="^" + replay_code + "$"):
            extractor.extract(packet)
    # Truncation proof recomputes request_body, but never reserves or dispatches.
    assert events == (["price"] if outcome == "truncated" else [])
    assert _files(tmp_path / "receipts") == before
    assert extractor.usage == usage


def test_facade_transport_stop_patch_controls_failure_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(facade, "UPSTAGE_TRANSPORT_STOP_CODES", {"BOUNDARY_STOP"})
    extractor, packet = make_extractor(FakeProbe(error=ValueError("BOUNDARY_STOP")), tmp_path)
    for _ in range(2):
        with pytest.raises(ValueError, match="^BOUNDARY_STOP$"):
            extractor.extract(packet)
    assert len(extractor._probe.calls) == 1


def test_facade_receipt_helpers_are_looked_up_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extractor, packet = make_extractor(FakeProbe('{"claims":[]}'), tmp_path)
    extractor.extract(packet)
    result_path = next((tmp_path / "receipts").glob("*/result.json"))
    original = result_path.read_bytes()
    result_path.unlink()
    seen: list[str] = []
    for name in ("canonical_json", "canonical_hash", "asdict"):
        _observe(monkeypatch, facade, name, seen, name)
    assert extractor.extract(packet) == {"spans": []}
    assert result_path.read_bytes() == original
    assert {"canonical_json", "canonical_hash", "asdict"} <= set(seen)


def test_facade_error_patch_reaches_graph_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PatchedError(facade.ExtractionOutputError):
        pass

    extractor = facade.UpstageClaimExtractor(
        FakeProbe(), tmp_path, display_text_profile="glyph-joined-display-v1"
    )
    document, _ = _extraction_context_graph()
    bound = facade.GraphBoundExtractor(extractor, document)
    monkeypatch.setattr(facade, "ExtractionOutputError", PatchedError)
    with pytest.raises(PatchedError, match="DISPLAY_SOURCE_UNAVAILABLE"):
        bound.extract({})


def test_facade_table_hash_and_serializer_patches_remain_effective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = graph("kakao")
    block = next(
        b for b in document.blocks if b.source_id == "329e3926-72d9-5f66-8274-1f75f2251b0a"
    )
    extractor = facade.UpstageClaimExtractor(FakeProbe(), tmp_path, **flags(QT1_POLICY))
    original_hash = facade.canonical_hash
    original_json = facade.canonical_json
    seen: list[str] = []

    def observe(original: Callable[..., str], marker: str) -> Callable[..., str]:
        def call(value: Any) -> str:
            if isinstance(value, dict) and "candidates" in value:
                seen.append(marker)
            return original(value)

        return call

    monkeypatch.setattr(facade, "canonical_hash", observe(original_hash, "hash"))
    monkeypatch.setattr(facade, "canonical_json", observe(original_json, "json"))
    extractor.extract(table_packet(document, block), context_graph=document)
    assert seen == ["hash", "json"]


def _entrypoints() -> list[str]:
    root = Path(facade.__file__).parent
    # Before the split this covers the existing helper package; afterward it
    # also requires every newly introduced module to import first in a process.
    return ["proofops_agent.upstage_extraction"] + [
        "proofops_agent." + str(p.relative_to(root).with_suffix("")).replace("/", ".")
        for pattern in ("extraction_parts/*.py", "upstage_extraction_parts/*.py")
        for p in sorted(root.glob(pattern))
    ]


@pytest.mark.parametrize("first", _entrypoints())
def test_helper_first_import_preserves_public_surface(first: str) -> None:
    code = """
import importlib, sys
assert 'proofops_agent.upstage_extraction' not in sys.modules
importlib.import_module(sys.argv[1])
from proofops_agent.upstage_extraction import UpstageClaimExtractor, GraphBoundExtractor
assert callable(UpstageClaimExtractor.extract)
assert callable(UpstageClaimExtractor._replay_receipt)
assert callable(UpstageClaimExtractor._fail)
assert callable(UpstageClaimExtractor._write)
assert callable(GraphBoundExtractor.extract)
"""
    result = subprocess.run([sys.executable, "-c", code, first], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
