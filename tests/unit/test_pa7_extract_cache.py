"""V9 whole-receipt reuse must preserve native cell ownership and historical pins."""

from copy import deepcopy
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v9 as v9
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import attest_claims
from proofops.adapters.local.native_replay_cache import replay_claims_cached
from proofops.domain.provenance import canonical_hash

from tests.integration.test_batch_attestation_cache import discovery_for
from tests.unit.test_pb1_source import fixture


@pytest.fixture
def fresh(monkeypatch):
    cache._results.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v4")
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
    receipt = v9._extend(base, graph, source.content, (ref,), tenant_id=source.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    calls = []
    monkeypatch.setattr(v9.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(receipt))
    # Isolate the byte-pinned replay tail. The fixture's cell proof above is real.
    monkeypatch.setattr(v9.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v9.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    original = v9.replay_claim_spans
    expected = original(receipt, graph, source.content, discovery, tenant_id=source.tenant_id)
    monkeypatch.setattr(v9, "replay_claim_spans", lambda *a, **k: calls.append(1) or expected)
    published = attest_claims(
        reader=v9,
        graph=graph,
        source=source.content,
        refs=(ref,),
        tenant_id=source.tenant_id,
        run_id=run,
        cache=True,
    )
    args = dict(
        reader=v9,
        policy=v9.claim_source_policy(),
        receipt=published,
        graph=graph,
        source=source.content,
        discovery=discovery,
        tenant_id=source.tenant_id,
    )
    yield args, calls, expected
    cache._results.clear()


def test_fresh_v9_avoids_duplicate_read_and_preserves_every_cell(fresh):
    args, calls, expected = fresh
    result = replay_claims_cached(**args)
    assert calls == []
    assert result == expected
    assert len(result[1].verified_spans) > 1
    assert result[0].claims[0].source_quality == "verified"


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.update(source=a["source"] + b"changed"),
        lambda a: a.update(tenant_id=str(uuid4())),
        lambda a: a["receipt"].update(run_id=str(uuid4())),
        lambda a: a["receipt"]["pb1_cell_proofs"][0].update(status="unresolved"),
        lambda a: a["receipt"]["baseline_receipt"]["records"][0].update(reason="tampered"),
        lambda a: a.update(discovery=replace(a["discovery"], claims=())),
    ],
)
def test_changed_source_scope_receipt_or_ref_order_never_reuses(fresh, change):
    args, calls, _ = fresh
    altered = args | dict(receipt=deepcopy(args["receipt"]))
    change(altered)
    replay_claims_cached(**altered)
    assert calls == [1]


def test_v3_keeps_frozen_execution_and_runtime_drift_misses(fresh, monkeypatch):
    args, calls, _ = fresh
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v3")
    replay_claims_cached(**args)
    assert calls == [1]
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v4")
    monkeypatch.setenv("DEVELOPER_DIR", "changed-runtime")
    replay_claims_cached(**args)
    assert calls == [1, 1]


def test_failed_ownership_cannot_inherit_whole_table_or_span_approval(fresh, monkeypatch):
    from proofops.application.evidence.span_citations import span_verified_graph

    args, _, _ = fresh
    receipt = deepcopy(args["receipt"])
    receipt["records"][0].update(status="unresolved", reason="cell_native_order_unresolved")
    receipt["pb1_cell_proofs"][0].update(status="unresolved", reason="cell_native_order_unresolved")
    ref = args["discovery"].claims[0].source_refs[0]
    graph = span_verified_graph(
        args["graph"], (replace(ref, verification_state="verified"),), "f" * 64
    )
    discovery = replace(
        args["discovery"],
        claims=tuple(replace(c, source_quality="verified") for c in args["discovery"].claims),
    )
    monkeypatch.setattr(v9.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(receipt))
    # Call the original byte-pinned function, bypassing this fixture's replay counter.
    import importlib

    v9_original = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("proofops.adapters.local._pa7_v9_tail", v9.__file__)
    )
    v9_original.__spec__.loader.exec_module(v9_original)
    monkeypatch.setattr(
        v9_original.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(receipt)
    )
    expected = v9_original.replay_claim_spans(
        receipt, graph, args["source"], discovery, tenant_id=args["tenant_id"]
    )
    actual = cache._project_v9(receipt, graph, discovery, args["tenant_id"])
    assert actual == expected
    assert actual[0].claims[0].source_quality == "unverified"


def test_historical_current_policy_and_frozen_reader_bytes_remain_available():
    from hashlib import sha256
    from pathlib import Path

    from proofops.application.analysis_profile import V2_POLICY, V2_PRE_PA7_POLICY, policy_for

    old = "196d611664f355efa58278f58ea24f87f6b2b8fee45269a56158fb96b4d18aee"
    assert canonical_hash(V2_PRE_PA7_POLICY) == old
    assert policy_for("finals-unattended-v2", pinned_hash=old) == V2_PRE_PA7_POLICY
    assert canonical_hash(V2_POLICY) != old
    assert (
        sha256(Path(v9.__file__).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V4_POLICY["v9_replay_sha256"]
    )
