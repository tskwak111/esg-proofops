"""Whole fresh parse proofs and one cold EV1 read preserve the frozen tail."""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local import evidence_source_ocr_v1 as ev1
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import verified_read_cache as cache
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_claim_source_verification import inputs


@pytest.fixture
def setup(monkeypatch):
    cache._results.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v3")
    source, graph, ref = inputs()
    yield source, graph, ref
    cache._results.clear()


def test_native_fresh_whole_proof_is_reused_but_changed_source_is_not(setup):
    source, graph, _ = setup
    receipt = dict(
        run_id="pa3",
        reader_policy=v6.native_policy(),
        records=[dict(source_id=graph.blocks[0].source_id, status="verified")],
    )
    args = dict(
        reader_name="native:upstage-ocr-page-v6",
        policy=v6.native_policy(),
        receipt=receipt,
        graph=graph,
        source=source,
        tenant_id=TENANT,
    )
    cache.remember_parse_attestation(**args)
    calls = []
    fast = cache.replay_cached(**args, recompute=lambda *a, **k: calls.append(1) or graph)
    assert calls == []
    assert fast.blocks[0].quality == "verified"
    assert graph.blocks[0].quality == "unverified"
    cache.replay_cached(
        **(args | dict(source=source + b"changed")),
        recompute=lambda *a, **k: calls.append(1) or graph,
    )
    assert calls == [1]


def evidence_fixture(graph, ref):
    base = dict(
        policy=ev1.policy(),
        physical_pages=[1],
        tables=[],
        records=[dict(kind="paragraph", status="verified", ref=asdict(ref))],
    )
    base["artifact_sha256"] = canonical_hash(base)
    wrapped = dict(
        base, run_id="pa3", page_collections=[], rendered_reader_profile="upstage-ocr-page-v4"
    )
    wrapped["artifact_sha256"] = canonical_hash(
        {k: v for k, v in wrapped.items() if k != "artifact_sha256"}
    )
    return base, wrapped


def test_fresh_evidence_keeps_base_receipt_identity_and_is_mutation_isolated(setup, monkeypatch):
    source, graph, ref = setup
    base, wrapped = evidence_fixture(graph, ref)
    args = dict(
        reader_name=ev1.__name__,
        policy=ev1.policy(),
        receipt=wrapped,
        graph=graph,
        source=source,
        tenant_id=TENANT,
    )
    cache.remember_parse_attestation(**args)
    result = cache.replay_cached(**args, recompute=lambda *a, **k: pytest.fail("duplicate OCR"))
    assert result.verified_spans[0].quote == ref.quote
    assert result.span_receipt_sha256 == base["artifact_sha256"]
    assert result.span_receipt_sha256 != wrapped["artifact_sha256"]
    forged = deepcopy(wrapped)
    forged["records"][0]["status"] = "unresolved"
    monkeypatch.setattr(
        ev1.Reader,
        "_evidence_reader",
        lambda *a, **k: (
            SimpleNamespace(attest_evidence_sources=lambda *a, **k: deepcopy(base)),
            {},
        ),
    )
    monkeypatch.setattr(ev1.v4.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    with pytest.raises(ValueError, match="EVIDENCE_SOURCE_RECEIPT_MISMATCH"):
        cache.replay_cached(**(args | dict(receipt=forged)), recompute=lambda *a, **k: graph)


def test_cold_evidence_compares_whole_receipt_once_then_projects(setup, monkeypatch):
    source, graph, ref = setup
    base, wrapped = evidence_fixture(graph, ref)
    calls = []

    def attest(*a, **k):
        calls.append(1)
        return deepcopy(base)

    monkeypatch.setattr(
        ev1.Reader,
        "_evidence_reader",
        lambda *a, **k: (SimpleNamespace(attest_evidence_sources=attest), {}),
    )
    monkeypatch.setattr(ev1.v4.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    args = dict(
        reader_name=ev1.__name__,
        policy=ev1.policy(),
        receipt=wrapped,
        graph=graph,
        source=source,
        tenant_id=TENANT,
        recompute=lambda *a, **k: pytest.fail("second read"),
    )
    result = cache.replay_cached(**args)
    assert calls == [1]
    assert result.span_receipt_sha256 == base["artifact_sha256"]
    cache._results.clear()
    with pytest.raises(ValueError, match="EVIDENCE_SOURCE_RECEIPT_MISMATCH"):
        cache.replay_cached(**(args | dict(receipt=dict(wrapped, artifact_sha256="changed"))))


def test_transient_and_historical_proofs_keep_original_reader(setup, monkeypatch):
    source, graph, _ = setup
    calls = []
    args = dict(
        reader_name="native:upstage-ocr-page-v6",
        policy=v6.native_policy(),
        receipt=dict(run_id="pa3", records=[], reason="ocr_reader_unavailable"),
        graph=graph,
        source=source,
        tenant_id=TENANT,
    )
    cache.remember_parse_attestation(**args)
    for _ in range(2):
        cache.replay_cached(**args, recompute=lambda *a, **k: calls.append(1) or graph)
    assert calls == [1, 1]
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v2")
    cache.remember_parse_attestation(**args)
    assert not any(k.startswith("parse:") for k in cache._results)


@pytest.mark.parametrize("invalid", ["cancel", "expired", "fence"])
def test_tag_atomic_fence_retains_cancellation_and_ownership(tmp_path, monkeypatch, invalid):
    from proofops.application.ports.jobs import LeaseLost
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.acceptance.test_jobs import MESSAGE, RUN, seeded
    from tests.acceptance.test_jobs import TENANT as JOB_TENANT

    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v3")
    jobs = seeded(tmp_path / "jobs.sqlite3")
    lease = jobs.claim_job(MESSAGE, owner="pa3", now=0, lease_seconds=10)
    jobs.can_call = lambda *a, **k: pytest.fail("duplicate transaction")
    live = object.__new__(LiveTaggingRuntime)
    live.runner = SimpleNamespace(store=SimpleNamespace(jobs=jobs), clock=lambda: 1)
    live.lease = lease
    live._fence()
    if invalid == "cancel":
        jobs.cancel_run(
            JOB_TENANT,
            RUN,
            expected_revision=jobs.get_run(JOB_TENANT, RUN)["revision"],
            idempotency_key="pa3-cancel-000001",
            reason="test",
            actor_sub="test",
            now=2,
        )
    elif invalid == "expired":
        live.runner.clock = lambda: 301
    else:
        live.lease = replace(lease, fencing_token=lease.fencing_token + 1)
    with pytest.raises(LeaseLost, match="LEASE_LOST"):
        live._fence()


def test_pa2_policy_hash_and_frozen_reader_preserved():
    from proofops.application.analysis_profile import V2_PRE_PA3_POLICY, policy_for

    old = "3f1ea21f49dd2b9bf6b58c5b2c84abaadfba203b2dda3415d00ae93b29e8e3d8"
    assert canonical_hash(V2_PRE_PA3_POLICY) == old
    assert policy_for("finals-unattended-v2", pinned_hash=old) == V2_PRE_PA3_POLICY
