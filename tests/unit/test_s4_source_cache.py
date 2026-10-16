"""v13 fresh reuse keeps every native ownership and identity guard."""

from copy import deepcopy
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v11 as previous
from proofops.adapters.local import upstage_ocr_profile_v13 as v13
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import attest_claims
from proofops.adapters.local.native_replay_cache import replay_claims_cached
from proofops.domain.provenance import canonical_hash

from tests.integration.test_batch_attestation_cache import discovery_for
from tests.unit.test_pb1_source import fixture


@pytest.fixture
def fresh(monkeypatch):
    cache._results.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v8")
    graph, source, ref = fixture()
    discovery = discovery_for(graph, (ref,))
    run = str(uuid4())
    base = dict(
        tenant_id=source.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        run_id=run,
        source_sha256=source.sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        policy=v6.claim_source_policy(),
        records=[dict(ref=asdict(ref), status="unresolved", reason="table_grid_unresolved")],
    )
    receipt = previous._extend(base, graph, source.content, (ref,), tenant_id=source.tenant_id)
    receipt.update(schema="claim_source_k7_extension_v1", policy=v13.claim_source_policy())
    receipt["artifact_sha256"] = canonical_hash(
        {k: v for k, v in receipt.items() if k != "artifact_sha256"}
    )
    monkeypatch.setattr(v13.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v13.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    expected = v13.replay_claim_spans(
        receipt, graph, source.content, discovery, tenant_id=source.tenant_id
    )
    from proofops.adapters.local import pa7_raster_cache

    monkeypatch.setattr(pa7_raster_cache, "attest", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v13.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(receipt))
    calls = []
    monkeypatch.setattr(v13, "replay_claim_spans", lambda *a, **k: calls.append(1) or expected)
    monkeypatch.setattr(cache, "_cold_v13_replay", lambda *a, **k: calls.append(1) or expected)
    published = attest_claims(
        reader=v13,
        graph=graph,
        source=source.content,
        refs=(ref,),
        tenant_id=source.tenant_id,
        run_id=run,
        cache=True,
    )
    yield (
        dict(
            reader=v13,
            policy=v13.claim_source_policy(),
            receipt=published,
            graph=graph,
            source=source.content,
            discovery=discovery,
            tenant_id=source.tenant_id,
        ),
        calls,
        expected,
    )
    cache._results.clear()


def test_fresh_v13_is_byte_identical_without_second_reader(fresh):
    args, calls, expected = fresh
    assert replay_claims_cached(**args) == expected
    assert calls == []


@pytest.mark.parametrize("field", ["source", "tenant", "run", "proof", "refs", "runtime"])
def test_changed_scope_receipt_or_runtime_cannot_reuse(fresh, field, monkeypatch):
    args, calls, _ = fresh
    args = args | dict(receipt=deepcopy(args["receipt"]))
    if field == "source":
        args["source"] += b"changed"
    elif field == "tenant":
        args["tenant_id"] = str(uuid4())
    elif field == "run":
        args["receipt"]["run_id"] = str(uuid4())
    elif field == "proof":
        args["receipt"]["pb1_cell_proofs"][0]["status"] = "unresolved"
    elif field == "refs":
        args["discovery"] = replace(args["discovery"], claims=())
    else:
        monkeypatch.setenv("DEVELOPER_DIR", "changed")
    args["receipt"]["artifact_sha256"] = canonical_hash(
        {k: v for k, v in args["receipt"].items() if k != "artifact_sha256"}
    )
    replay_claims_cached(**args)
    assert calls == [1]


def test_v7_does_not_silently_admit_v13(fresh, monkeypatch):
    args, calls, _ = fresh
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v7")
    replay_claims_cached(**args)
    assert calls == [1]


def test_cold_recompute_checks_whole_receipt_before_projecting(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from proofops.adapters.local import pa7_raster_cache

    graph, source, ref = fixture()
    discovery = discovery_for(graph, (ref,))
    base = dict(
        tenant_id=source.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=source.sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        run_id=str(uuid4()),
        policy=v6.claim_source_policy(),
        records=[dict(ref=asdict(ref), status="unresolved", reason="table_grid_unresolved")],
    )
    receipt = previous._extend(base, graph, source.content, (ref,), tenant_id=source.tenant_id)
    receipt.update(schema="claim_source_k7_extension_v1", policy=v13.claim_source_policy())
    receipt["artifact_sha256"] = canonical_hash(
        {k: v for k, v in receipt.items() if k != "artifact_sha256"}
    )
    recomputed = deepcopy(receipt)
    calls = []

    def recompute(stored, current_graph, original, refs, *, tenant_id):
        assert current_graph == graph and original == source.content
        assert tenant_id == source.tenant_id and tuple(refs) == (ref,)
        calls.append(1)
        return deepcopy(recomputed)

    @contextmanager
    def bounded(*a, **kw):
        yield SimpleNamespace(recompute_claim_receipt=recompute)

    monkeypatch.setattr(pa7_raster_cache, "bounded_reader", bounded)
    result = cache._cold_v13_replay(receipt, graph, source.content, discovery, source.tenant_id)
    assert result[0].claims[0].source_quality == "verified" and calls == [1]
    recomputed["records"][0]["status"] = "unresolved"
    with pytest.raises(ValueError, match="OCR_CLAIM_RECEIPT_MISMATCH"):
        cache._cold_v13_replay(receipt, graph, source.content, discovery, source.tenant_id)


def test_v13_raw_reader_keeps_inherited_heading_guard_and_frozen_bytes(monkeypatch):
    from hashlib import sha256
    from pathlib import Path

    from proofops.adapters.local import pa7_raster_cache, upstage_ocr_profile_v12

    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v8")
    monkeypatch.setattr(v13.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    before = [
        sha256(Path(r.__file__).read_bytes()).hexdigest()
        for r in (previous, upstage_ocr_profile_v12, v13)
    ]
    with pa7_raster_cache.bounded_reader(
        v13, tenant_id=str(uuid4()), run_id=str(uuid4())
    ) as reader:
        assert reader._claim_receipt.__func__.__globals__["super"]
        assert (
            reader._claim_receipt.__func__.__code__
            == upstage_ocr_profile_v12.Reader._claim_receipt.__code__
        )
    assert before == [
        sha256(Path(r.__file__).read_bytes()).hexdigest()
        for r in (previous, upstage_ocr_profile_v12, v13)
    ]


def test_unresolved_cell_and_transient_receipt_never_gain_verification(fresh):
    args, _, _ = fresh
    receipt = deepcopy(args["receipt"])
    receipt["records"][0]["status"] = "unresolved"
    receipt["pb1_cell_proofs"][0]["status"] = "unresolved"
    receipt["artifact_sha256"] = canonical_hash(
        {k: v for k, v in receipt.items() if k != "artifact_sha256"}
    )
    cache.remember_fresh_attestation(
        reader=args["reader"],
        policy=args["policy"],
        receipt=receipt,
        graph=args["graph"],
        source=args["source"],
        tenant_id=args["tenant_id"],
        refs=args["discovery"].claims[0].source_refs,
    )
    result = cache.reuse_fresh_attestation(**(args | dict(receipt=receipt)))
    assert result[0].claims[0].source_quality == "unverified"
    assert all(r.verification_state != "verified" for r in result[0].claims[0].source_refs)
    receipt["records"][0]["reason"] = "local_raster_read_unresolved"
    assert cache.reuse_fresh_attestation(**(args | dict(receipt=receipt))) is None


@pytest.mark.parametrize("field", ["graph", "reader", "document", "manifest"])
def test_additional_identity_changes_keep_original_replay(fresh, monkeypatch, field):
    args, calls, _ = fresh
    args = args | dict(receipt=deepcopy(args["receipt"]))
    if field == "graph":
        args["graph"] = replace(args["graph"], blocks=args["graph"].blocks[:-1])
    elif field == "reader":
        policy = args["reader"].claim_source_policy()
        monkeypatch.setattr(args["reader"], "claim_source_policy", lambda: policy | {"drift": True})
    else:
        key = "document_version_id" if field == "document" else "parse_manifest_id"
        args["receipt"][key] = str(uuid4())
    replay_claims_cached(**args)
    assert calls == [1]


def test_optimization_binding_failure_runs_unchanged_verifier(fresh, monkeypatch):
    args, calls, expected = fresh
    cache._results.clear()

    def unavailable(*a, **kw):
        raise ValueError("PA7_RASTER_READER_BINDING_MISMATCH")

    monkeypatch.setattr(cache, "_cold_v13_replay", unavailable)
    assert replay_claims_cached(**args) == expected
    assert calls == [1]


def test_explicit_s4_policy_keeps_v7_default_and_historical_hash():
    from proofops.application.analysis_profile import (
        FINALS_I7_POLICY,
        S4_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )

    assert (
        canonical_hash(FINALS_I7_POLICY)
        == "0d10ccb21b953f5c29846438fb72538baf50ebd280c45d89b5adbf727c6c9efb"
    )
    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I7_POLICY)) == FINALS_I7_POLICY
    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(S4_POLICY)) == S4_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(S4_POLICY)) == S4_POLICY
