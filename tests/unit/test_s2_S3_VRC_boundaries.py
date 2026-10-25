"""Lock process-cache bytes, source pins and facade hooks before extraction."""

from __future__ import annotations

import pickle
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from zlib import compress
from zlib import error as ZlibError

import pytest
from proofops.adapters.local import local_raster_reader, pa7_raster_cache
from proofops.adapters.local import receipt_environment_compat as environment
from proofops.adapters.local import upstage_ocr_profile_v13 as v13
from proofops.adapters.local import verified_read_cache as cache
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

if TYPE_CHECKING:
    from collections.abc import Iterator

SOURCE = b"VRC boundary original"
TENANT = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def scope(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(cache, "_results", OrderedDict())
    monkeypatch.setattr(cache, "_inflight", {})
    monkeypatch.setattr(cache, "sys", SimpleNamespace(platform="vrc-boundary"))
    monkeypatch.setenv("DEVELOPER_DIR", "/vrc/toolchain")
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v8")
    monkeypatch.setattr(local_raster_reader, "runtime_policy", lambda: {"runtime": "fixed"})
    monkeypatch.setattr(environment, "read_profile", lambda: "fixed-read-profile")
    graph = CanonicalDocumentGraph(
        TENANT,
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
        sha256(SOURCE).hexdigest(),
        (),
        (),
        (),
        (),
    )
    policy = v13.claim_source_policy()
    receipt = dict(
        schema="claim_source_k7_extension_v1",
        tenant_id=TENANT,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        run_id="vrc-boundary-run",
        policy=policy,
        records=[],
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    return dict(
        reader=v13,
        policy=policy,
        receipt=receipt,
        graph=graph,
        source=SOURCE,
        refs=(),
        tenant_id=TENANT,
    )


def test_v13_path_bytes_hash_and_fresh_key(
    scope: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_path = (
        Path(__file__).resolve().parents[2]
        / "packages/proofops/adapters/local/upstage_ocr_profile_v13.py"
    )
    expected_bytes = expected_path.read_bytes()
    assert Path(v13.__file__).resolve() == expected_path
    assert sha256(expected_bytes).hexdigest() == cache.VERIFIED_READ_V8_POLICY["v13_replay_sha256"]
    reads: list[tuple[Path, bytes]] = []
    hashes: list[bytes] = []
    read_bytes = Path.read_bytes

    def tracked_read(path: Path) -> bytes:
        value = read_bytes(path)
        reads.append((path.resolve(), value))
        return value

    def tracked_hash(value: bytes) -> Any:
        hashes.append(value)
        return sha256(value)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    monkeypatch.setattr(cache, "sha256", tracked_hash)
    key = cache._fresh_key(**scope)
    assert key == "fresh:6c25463f7a075d9d051ed132a7eea53dd25be37b28474b6ffec8d8010da6cda8"
    assert (expected_path, expected_bytes) in reads
    assert expected_bytes in hashes
    cache.remember_fresh_attestation(**scope)
    encoded = compress(canonical_json(scope["receipt"]).encode(), level=1)
    assert cache._results == {key: encoded}
    assert (
        sha256(encoded).hexdigest()
        == "f170ae66055a1240d7a651b40a3927734546c487778cb86deaf4ee6bbaafdd6e"
    )


@pytest.mark.parametrize("change", ("tenant", "source", "graph", "receipt", "transient", "pin"))
def test_fresh_identity_and_pin_fail_closed(
    scope: dict[str, Any], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    assert cache._fresh_key(**scope) is not None
    if change == "tenant":
        scope["tenant_id"] = "00000000-0000-4000-8000-000000000004"
    elif change == "source":
        scope["source"] += b"changed"
    elif change == "graph":
        scope["graph"] = replace(scope["graph"], parse_manifest_id="other")
    elif change == "receipt":
        scope["receipt"]["artifact_sha256"] = "0" * 64
    elif change == "transient":
        scope["receipt"]["reason"] = "render_limit"
        scope["receipt"]["artifact_sha256"] = canonical_hash(
            {k: v for k, v in scope["receipt"].items() if k != "artifact_sha256"}
        )
    else:
        original = Path.read_bytes
        monkeypatch.setattr(
            Path,
            "read_bytes",
            lambda p: original(p) + b"tampered"
            if p.resolve() == Path(v13.__file__).resolve()
            else original(p),
        )
    assert cache._fresh_key(**scope) is None


def test_parse_key_and_compressed_receipt_hooks(
    scope: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "_parse_projection_pinned", lambda *args: True)
    args = {k: scope[k] for k in ("policy", "receipt", "graph", "source", "tenant_id")}
    args["reader_name"] = "boundary-reader"
    key = cache._parse_key(**args)
    assert key == "parse:3ecac9bb9c71d834db6f4318ba9fde92a021b806bd488c4fe9eca03adb7701a5"
    cache.remember_parse_attestation(**args)
    assert cache._results[key] == compress(canonical_json(args["receipt"]).encode(), level=1)
    monkeypatch.setattr(cache, "_project_parse", lambda *args, **kwargs: scope["graph"])
    assert cache._fresh_parse_replay(**args) is scope["graph"]
    cache._results[key] = compress(b"different receipt", level=1)
    assert cache._fresh_parse_replay(**args) is None
    cache._results[key] = b"corrupt zlib"
    with pytest.raises(ZlibError):
        cache._fresh_parse_replay(**args)
    monkeypatch.setattr(cache, "_transient", lambda value: True)
    assert cache._parse_key(**args) is None
    assert cache._fresh_key(**scope) is None


def test_cold_v13_checks_pinned_bytes_before_reader_and_projection(
    scope: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    original = Path.read_bytes
    path = Path(v13.__file__).resolve()
    expected_bytes = path.read_bytes()
    monkeypatch.setattr(
        cache,
        "_project_owned_cells",
        lambda *args, **kwargs: events.append("project") or (None, scope["graph"]),
    )
    from proofops.adapters.local import claim_source_verification

    monkeypatch.setattr(claim_source_verification, "discovery_refs", lambda discovery: ())

    def tracked_read(p: Path) -> bytes:
        value = original(p)
        if p.resolve() == path:
            assert value == expected_bytes
            events.append("pin")
        return value

    def recompute(*args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append("recompute")
        return scope["receipt"]

    @contextmanager
    def bounded(*args: Any, **kwargs: Any) -> Iterator[SimpleNamespace]:
        events.append("reader")
        yield SimpleNamespace(recompute_claim_receipt=recompute)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    monkeypatch.setattr(pa7_raster_cache, "bounded_reader", bounded)
    cache._cold_v13_replay(scope["receipt"], scope["graph"], SOURCE, None, TENANT)
    # Policy construction hashes itself before the explicit replay-pin check.
    assert events == ["pin", "pin", "reader", "recompute", "project"]
    events.clear()
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda p: original(p) + b"tampered" if p.resolve() == path else original(p),
    )
    with pytest.raises(ValueError, match="^OCR_POLICY_OR_RUN_MISMATCH$"):
        cache._cold_v13_replay(scope["receipt"], scope["graph"], SOURCE, None, TENANT)
    assert events == []


def test_whole_replay_key_pickle_bytes_and_bounds(
    scope: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", cache.POLICY["profile"])
    calls: list[str] = []

    def recompute(*args: Any, **kwargs: Any) -> CanonicalDocumentGraph:
        calls.append("read")
        return scope["graph"]

    args = dict(
        reader_name="boundary",
        policy={},
        receipt={},
        graph=scope["graph"],
        source=SOURCE,
        tenant_id=TENANT,
        recompute=recompute,
    )
    assert cache.replay_cached(**args) == scope["graph"]
    encoded = compress(pickle.dumps(scope["graph"], protocol=5), level=1)
    assert cache._results == {
        "7870a19cf75a55c021570d8f72b46253488fa74c629ea97644ad1af3c31cc7da": encoded
    }
    assert (
        sha256(encoded).hexdigest()
        == "e50512d661b579db85fd9cc45f358bfc02d168f5f9ffdaf72ec6ab3cc5770978"
    )
    assert cache.replay_cached(**args) == scope["graph"]
    assert calls == ["read"]
    cache.replay_cached(**(args | {"tenant_id": "other-tenant"}))
    assert calls == ["read", "read"]
    monkeypatch.setattr(cache, "_execution_policy", lambda: {"max_entries": 2})
    monkeypatch.setattr(cache, "POLICY", {"max_bytes": 5})
    cache._results.clear()
    cache._retain("first", b"aa")
    cache._retain("second", b"bb")
    cache._retain("first", b"aa")
    cache._retain("third", b"cc")
    assert list(cache._results) == ["first", "third"]
    cache._retain("large", b"12345")
    assert cache._results == {"large": b"12345"}


def test_policy_and_parse_eligibility_resolve_facade_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = {"profile": "vrc-patched-v3"}
    monkeypatch.setattr(cache, "VERIFIED_READ_V3_POLICY", policy)
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", policy["profile"])
    assert cache._execution_policy() is policy
    assert cache.fresh_execution_enabled()
    assert cache._parse_enabled()
    monkeypatch.setattr(cache, "_execution_policy", lambda: None)
    assert not cache._parse_enabled()
    monkeypatch.setattr(cache, "_parse_enabled", lambda: False)
    assert not cache._parse_projection_pinned("boundary-reader", {})


@pytest.mark.parametrize("facade_first", (False, True), ids=("split-first", "facade-first"))
def test_split_module_import_order_and_reexports(facade_first: bool) -> None:
    import os
    import subprocess
    import sys

    facade = "proofops.adapters.local.verified_read_cache"
    split = "proofops.adapters.local.verified_read_cache_keys"
    modules = (facade, split) if facade_first else (split, facade)
    code = "\n".join(f"import {name}" for name in modules)
    code += f"\nfrom {facade} import ParseReplayArgs, replay_cached, remember_fresh_attestation"
    for name in (
        "fresh_execution_enabled",
        "_execution_policy",
        "_parse_enabled",
        "_parse_projection_pinned",
        "_parse_key",
        "_fresh_key",
    ):
        code += f"\nassert {facade}.{name} is {split}.{name}"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
