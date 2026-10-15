"""Offline regressions for bounded page transport; original proof remains serial."""

from contextvars import ContextVar
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from proofops.adapters.parsing import hx6_upstage as hx6
from proofops.domain.provenance import canonical_hash


def test_four_page_transport_overlaps_and_grounding_waits_for_wave(monkeypatch):
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [])
    barrier = Barrier(4, timeout=5)
    lock = Lock()
    scope = ContextVar("s3_scope", default=None)
    scope.set("tenant-run")
    active = peak = 0
    calls = []

    def call(pages, mode):
        nonlocal active, peak
        assert scope.get() == "tenant-run"
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(pages)
        barrier.wait()
        with lock:
            active -= 1
        return {"raw_batches": [pages[0]], "response_sha256": str(pages[0])}, False

    def candidate(*args, **kwargs):
        assert active == 0  # PDFium/native work never overlaps the next subset wave.
        return SimpleNamespace(
            blocks=[SimpleNamespace(source=SimpleNamespace(raw_text="text"))]
        ), {}

    monkeypatch.setattr(hx6, "candidate_batch", candidate)
    p = SimpleNamespace(claim_physical_pages=tuple(range(1, 9)), mixed_ocr_max_pages=0)
    _, routing, output = hx6.recover(
        None,
        p,
        tuple(range(1, 9)),
        (),
        call,
        config_hash="test",
        claim_layout=True,
        page_workers=4,
    )
    assert peak == 4 and len(calls) == 8
    assert routing["provider_pages"] == list(range(1, 9))
    assert [r["pages"] for r in output["page_records"]] == [[i] for i in range(1, 9)]
    assert output["failed_batches"] == []


@pytest.mark.parametrize("code", ["UPSTAGE_HTTP_401", "BUDGET_EXHAUSTED"])
def test_stop_drains_reserved_wave_and_never_starts_another(monkeypatch, code):
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [])
    monkeypatch.setattr(
        hx6,
        "candidate_batch",
        lambda *a, **k: (
            SimpleNamespace(blocks=[SimpleNamespace(source=SimpleNamespace(raw_text="text"))]),
            {},
        ),
    )
    calls = []

    def call(pages, mode):
        calls.append(pages[0])
        if pages == (1,):
            raise ValueError(code)
        return {"raw_batches": [pages[0]]}, False

    p = SimpleNamespace(claim_physical_pages=tuple(range(1, 9)), mixed_ocr_max_pages=0)
    _, routing, output = hx6.recover(
        None, p, tuple(range(1, 9)), (), call, config_hash="test", claim_layout=True, page_workers=4
    )
    assert sorted(calls) == [1, 2, 3, 4]
    assert routing["provider_pages"] == [2, 3, 4]
    assert routing["unreadable_pages"] == [1, 5, 6, 7, 8]
    assert len(output["failed_batches"]) == 5


def test_new_policy_is_opt_in_and_historical_pins_unchanged():
    from proofops.application import analysis_profile as p

    old_hash = "66669e915909dc62460931410c06215c4e520688523ada7f9bdb0e89724541b7"
    assert canonical_hash(p.FINALS_I23_POLICY) == old_hash
    assert p.policy_for(p.V2_PROFILE, pinned_hash=old_hash) == p.FINALS_I23_POLICY
    new = p.S3_SPEED_POLICY
    assert new["parser_failure_policy"] == "s3_partial-v7"
    assert {
        k: v
        for k, v in new.items()
        if k not in {"integration_profile", "parser_failure_policy", "verified_read_cache"}
    } == {
        k: v
        for k, v in p.FINALS_I23_POLICY.items()
        if k not in {"integration_profile", "parser_failure_policy", "verified_read_cache"}
    }
    for policy in (new, p.FINALS_I23_POLICY, p.FINALS_I21_POLICY):
        pin = canonical_hash(policy)
        assert p.policy_for(p.V2_PROFILE, pinned_hash=pin) == policy
        assert p.publication_policy_for(p.V2_PROFILE, pinned_hash=pin) == policy


@pytest.mark.parametrize("code,attempts", [("UPSTAGE_HTTP_503", 2), ("UPSTAGE_REQUEST_TIMEOUT", 1)])
def test_parallel_transport_keeps_retry_boundary_and_native_fallback(monkeypatch, code, attempts):
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [1])
    monkeypatch.setattr(hx6, "sleep", lambda *a: None)
    calls = []

    def call(pages, mode):
        calls.append(pages)
        raise ValueError(code)

    p = SimpleNamespace(claim_physical_pages=(1,), mixed_ocr_max_pages=0)
    _, routing, output = hx6.recover(
        None, p, (1,), (), call, config_hash="test", claim_layout=True, page_workers=4
    )
    assert len(calls) == attempts
    assert routing["local_pages"] == [1]
    assert output["failed_batches"] == [dict(mode="standard", pages=[1], error_code=code)]


def test_parallel_parser_roundtrip_preserves_source_and_rejects_tampering(tmp_path):
    import io
    import json
    from dataclasses import replace
    from hashlib import sha256
    from uuid import uuid4

    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
    from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
    from pypdf import PdfReader

    from deploy.public.offline_fixture import fake_parse, source_pdf

    pdf = source_pdf()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(pdf).hexdigest(), "v1", pdf
    )
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2),
        claim_physical_pages=(1, 2),
        java_executable="/opt/homebrew/opt/openjdk@21/bin/java",
        parser_mode="mixed-v1",
        local_resource_policy="selected-pdf-h6-v2",
        failure_policy="s3_partial-v7",
    )

    class Provider:
        def parse_async(self, content, **kwargs):
            assert len(PdfReader(io.BytesIO(content)).pages) == 1
            raw = [fake_parse(content, "standard")]
            return dict(raw_batches=raw, response_sha256=canonical_hash(raw))

    parser = OpenDataLoaderParser(tmp_path / "parser", upstage_probe=Provider())
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert {b.page_num for b in graph.blocks} == {1, 2}
    assert all(b.quality != "verified" for b in graph.blocks)
    assert (
        parser.load_verified(source, profile, tenant_id=source.tenant_id).to_dict()
        == graph.to_dict()
    )
    with pytest.raises(ParseFailure):
        parser.load_verified(
            replace(source, content=pdf + b"changed"), profile, tenant_id=source.tenant_id
        )
    manifest = next((tmp_path / "parser" / source.tenant_id).rglob("manifest.json"))
    data = json.loads(manifest.read_bytes())
    data["parser_profile"]["failure_policy"] = "partial-v6"
    manifest.chmod(0o600)
    manifest.write_text(json.dumps(data))
    with pytest.raises(ParseFailure):
        parser.load_verified(source, profile, tenant_id=source.tenant_id)


def test_terminal_failure_later_in_wave_prevents_earlier_page_retry(monkeypatch):
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [])
    monkeypatch.setattr(hx6, "sleep", lambda *a: None)
    monkeypatch.setattr(
        hx6,
        "candidate_batch",
        lambda *a, **k: (
            SimpleNamespace(blocks=[SimpleNamespace(source=SimpleNamespace(raw_text="text"))]),
            {},
        ),
    )
    calls = []

    def call(pages, mode):
        calls.append(pages[0])
        if pages == (1,):
            raise ValueError("UPSTAGE_HTTP_503")
        if pages == (4,):
            raise ValueError("UPSTAGE_HTTP_401")
        return {"raw_batches": [pages[0]]}, False

    p = SimpleNamespace(claim_physical_pages=tuple(range(1, 9)), mixed_ocr_max_pages=0)
    _, routing, output = hx6.recover(
        None, p, tuple(range(1, 9)), (), call, config_hash="test", claim_layout=True, page_workers=4
    )
    assert sorted(calls) == [1, 2, 3, 4]
    assert routing["provider_pages"] == [2, 3]
    assert len(output["failed_batches"]) == 6
