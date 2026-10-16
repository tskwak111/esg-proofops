"""v12 fresh reuse keeps every native ownership and identity guard."""

from copy import deepcopy
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v11 as previous
from proofops.adapters.local import upstage_ocr_profile_v12 as v12
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import attest_claims
from proofops.adapters.local.native_replay_cache import replay_claims_cached
from proofops.domain.provenance import canonical_hash

from tests.integration.test_batch_attestation_cache import discovery_for
from tests.unit.test_pb1_source import fixture


@pytest.fixture
def fresh(monkeypatch):
    cache._results.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v7")
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
    receipt.update(schema="claim_source_h1_extension_v1", policy=v12.claim_source_policy())
    receipt["artifact_sha256"] = canonical_hash(
        {k: v for k, v in receipt.items() if k != "artifact_sha256"}
    )
    monkeypatch.setattr(v12.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v12.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    expected = v12.replay_claim_spans(
        receipt, graph, source.content, discovery, tenant_id=source.tenant_id
    )
    from proofops.adapters.local import pa7_raster_cache

    monkeypatch.setattr(pa7_raster_cache, "attest", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v12.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(receipt))
    calls = []
    monkeypatch.setattr(v12, "replay_claim_spans", lambda *a, **k: calls.append(1) or expected)
    monkeypatch.setattr(cache, "_cold_v12_replay", lambda *a, **k: calls.append(1) or expected)
    published = attest_claims(
        reader=v12,
        graph=graph,
        source=source.content,
        refs=(ref,),
        tenant_id=source.tenant_id,
        run_id=run,
        cache=True,
    )
    yield (
        dict(
            reader=v12,
            policy=v12.claim_source_policy(),
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


def test_fresh_v12_is_byte_identical_without_second_reader(fresh):
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


def test_v5_does_not_silently_admit_v12(fresh, monkeypatch):
    args, calls, _ = fresh
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v5")
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
    receipt.update(schema="claim_source_h1_extension_v1", policy=v12.claim_source_policy())
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
    result = cache._cold_v12_replay(receipt, graph, source.content, discovery, source.tenant_id)
    assert result[0].claims[0].source_quality == "verified" and calls == [1]
    recomputed["records"][0]["status"] = "unresolved"
    with pytest.raises(ValueError, match="OCR_CLAIM_RECEIPT_MISMATCH"):
        cache._cold_v12_replay(receipt, graph, source.content, discovery, source.tenant_id)
