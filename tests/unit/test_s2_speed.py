"""S2 must retain complete source proof while avoiding nested duplicate replay."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from proofops.adapters.local import evidence_source_i17 as evidence
from proofops.adapters.local import upstage_ocr_profile_v19 as reader
from proofops.adapters.local import verified_read_cache as cache
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


@pytest.mark.parametrize("native", [True, False])
def test_cold_parse_recomputes_whole_receipt_once(monkeypatch, native):
    source, graph, _ = synthetic("ESG policy 10% achieved")
    monkeypatch.setattr(
        reader.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(
            fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED"))
        ),
    )
    instance = reader.for_run("s2")
    if native:
        receipt = instance.attest_native_sources(graph, source, tenant_id=graph.tenant_id)
        name, policy = "native:" + reader.PROFILE, reader.native_policy()
        original = instance.replay_native_sources
        owner, method = instance, "attest_native_sources"
        monkeypatch.setattr(reader, "for_run", lambda run: instance)
    else:
        receipt = evidence.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
        name, policy = evidence.__name__, evidence.policy()
        original = evidence.replay_evidence_sources
        owner, method = evidence, "attest_evidence_sources"
    expected = original(receipt, graph, source, tenant_id=graph.tenant_id)
    calls = []
    attest = getattr(owner, method)

    def counted(*a, **k):
        calls.append(1)
        return attest(*a, **k)

    monkeypatch.setattr(owner, method, counted)
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v11")
    cache._results.clear()
    args = dict(
        reader_name=name,
        policy=policy,
        receipt=receipt,
        graph=graph,
        source=source,
        tenant_id=graph.tenant_id,
        recompute=lambda *a, **k: pytest.fail("nested replay repeated the complete proof"),
    )
    result = cache.replay_cached(**args)
    assert asdict(result) == asdict(expected)
    assert calls == [1]
    assert cache.replay_cached(**args) == result
    assert calls == [1]
    forged = deepcopy(receipt)
    forged["records"][0]["reason"] = "forged"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        cache.replay_cached(**(args | dict(receipt=forged)))


def test_s2_pin_preserves_p2_and_replica_contract():
    from proofops.application import analysis_profile as profiles

    old = profiles.FINALS_P2_POLICY
    assert canonical_hash(old) == "ee7681d7a980d2bbab4734b53d3dad5e17c52574672661ef5c8c3c10b3d1d38a"
    selected = profiles.FINALS_S2_SPEED_POLICY
    assert selected["replicas"] == old["replicas"] == 3
    assert {
        k: v for k, v in selected.items() if k not in {"integration_profile", "verified_read_cache"}
    } == {k: v for k, v in old.items() if k not in {"integration_profile", "verified_read_cache"}}
    for p in (old, selected):
        pin = canonical_hash(p)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == p
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == p


@pytest.mark.parametrize("execution", ["exact-verified-read-v11", "exact-verified-read-v12"])
def test_s2_stops_after_last_committed_batch_without_extra_source_replay(monkeypatch, execution):
    from proofops_worker.extract_batch import run_batches

    calls = []

    def run_batch(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            return dict(status="committed", pending_after=[], model_processed_after=166)
        return dict(status="complete", pending_after=[])

    runner = SimpleNamespace(run_batch=run_batch)
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", execution)
    assert len(run_batches(runner, tenant_id="tenant", run_id="run", batches=10)) == 1
    assert calls == [1]
    calls.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v10")
    assert len(run_batches(runner, tenant_id="tenant", run_id="run", batches=10)) == 2


@pytest.mark.parametrize("profile", ["s2", "i21"])
def test_s2_hosted_prepare_and_private_handoff(tmp_path, monkeypatch, profile):
    import json
    import sqlite3

    from proofops.application.analysis_profile import FINALS_I21_POLICY, FINALS_S2_SPEED_POLICY
    from proofops_api import hosted_publication as handoff

    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf
    from tests.unit.test_s4_publication_handoff import state

    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(source_pdf())
    config = dict(
        analysis_profile="finals-unattended-v2",
        llm_provider="openai",
        report_year=2025,
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    selected = FINALS_S2_SPEED_POLICY if profile == "s2" else FINALS_I21_POLICY
    selected_reader = reader
    if profile == "i21":
        from proofops.adapters.local import upstage_ocr_profile_v21 as selected_reader
    pin = canonical_hash(selected)
    argv = prepare_argv(
        pdf,
        tmp_path / "prepared",
        graph_tenant := "11111111-1111-4111-8111-111111111111",
        config,
        dict(analysis_profile_sha256=pin),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    path, job, calls, content = state.__wrapped__(tmp_path, monkeypatch)
    snapshot = dict(
        analysis_profile_policy=selected,
        claim_source_policy=selected_reader.claim_source_policy(),
    )
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute("UPDATE run_snapshots SET payload=?", (json.dumps(snapshot),))
    packet = handoff.make_handoff(path, job, [13])
    assert packet is not None
    assert handoff.reuse_handoff(packet, path, job, [13]) == content
    assert calls == [1]
    assert handoff.reuse_handoff(packet, path, job | dict(tenant_id=graph_tenant), [13]) is None


def test_private_policy_snapshots_preserve_full_claim_receipt(monkeypatch):
    from proofops.adapters.local.s2_reader_execution import reader_scope

    source, graph, ref = synthetic("ESG policy 10% achieved")
    calls = []

    def missing(*a, **k):
        calls.append(1)
        raise ValueError("OCR_COLLECTION_UNTRUSTED")

    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: SimpleNamespace(fetch=missing))
    expected = reader.for_run("s2").attest_claim_spans(
        graph, source, (ref,), tenant_id=graph.tenant_id
    )
    with reader_scope(reader, run_id="s2", tenant_id=graph.tenant_id) as instance:
        actual = instance.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
        assert actual == expected
        calls.clear()
        assert (
            instance.recompute_claim_receipt(
                actual, graph, source, (ref,), tenant_id=graph.tenant_id
            )
            == actual
        )
        assert calls == []
    original = reader.claim_source_policy
    with pytest.raises(ValueError, match="S2_READER_POLICY_CHANGED"):
        with reader_scope(reader, run_id="s2", tenant_id=graph.tenant_id):
            monkeypatch.setattr(
                reader, "claim_source_policy", lambda: original() | dict(changed=True)
            )
