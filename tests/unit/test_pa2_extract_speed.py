"""Reuse only whole fresh attestations; retain source ordering and fenced calls."""

import threading
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local import upstage_ocr_profile_v6 as reader
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import attest_claims
from proofops.adapters.local.native_replay_cache import replay_claims_cached
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_batch_attestation_cache import discovery_for
from tests.integration.test_claim_source_verification import inputs


@pytest.fixture
def fresh(monkeypatch):
    cache._results.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v2")
    source, graph, ref = inputs()
    discovery = discovery_for(graph, (ref,))
    policy = reader.claim_source_policy()
    receipt = dict(
        policy=policy,
        run_id="pa2",
        records=[dict(ref=asdict(ref), status="verified")],
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    monkeypatch.setattr(reader, "attest_claim_spans", lambda *a, **k: deepcopy(receipt))
    calls = []
    monkeypatch.setattr(
        reader, "replay_claim_spans", lambda *a, **k: calls.append(1) or (discovery, graph)
    )
    published = attest_claims(
        reader=reader,
        graph=graph,
        source=source,
        refs=(ref,),
        tenant_id=TENANT,
        run_id="pa2",
        cache=True,
    )
    yield (
        dict(
            reader=reader,
            policy=policy,
            receipt=published,
            graph=graph,
            source=source,
            discovery=discovery,
            tenant_id=TENANT,
        ),
        calls,
        ref,
    )
    cache._results.clear()


def test_fresh_whole_attestation_skips_only_duplicate_read(fresh):
    args, calls, _ = fresh
    first, scoped = replay_claims_cached(**args)
    assert calls == []
    assert first.claims[0].source_quality == "verified"
    assert len(scoped.verified_spans) == 1
    assert getattr(args["graph"], "verified_spans", ()) == ()
    assert replay_claims_cached(**args) == (first, scoped)
    forged = deepcopy(args["receipt"])
    forged["records"][0]["status"] = "unresolved"
    replay_claims_cached(**(args | dict(receipt=forged)))
    assert calls == [1]


def test_unavailable_fresh_attestation_retries_and_shared_storage_is_bounded(fresh):
    args, calls, ref = fresh
    cache._results.clear()
    receipt = dict(args["receipt"], error="reader unavailable")
    cache.remember_fresh_attestation(
        **{k: args[k] for k in ("reader", "policy", "graph", "source", "tenant_id")},
        receipt=receipt,
        refs=(ref,),
    )
    replay_claims_cached(**(args | dict(receipt=receipt)))
    replay_claims_cached(**(args | dict(receipt=receipt)))
    assert calls == [1, 1]
    for i in range(6):
        cache.remember_fresh_attestation(
            **{k: args[k] for k in ("reader", "policy", "graph", "source", "tenant_id")},
            receipt=dict(args["receipt"], run_id=str(i)),
            refs=(ref,),
        )
    assert len(cache._results) == 4
    assert sum(map(len, cache._results.values())) <= 32 * 1024 * 1024


def test_changed_live_reader_policy_cannot_reuse_warm_result(fresh, monkeypatch):
    args, calls, _ = fresh
    cache._results.clear()
    replay_claims_cached(**args)
    replay_claims_cached(**args)
    assert calls == [1]
    monkeypatch.setattr(reader, "claim_source_policy", lambda: dict(args["policy"], changed=True))
    replay_claims_cached(**args)
    assert calls == [1, 1]


def test_operator_batch_and_concurrency_settings_pin_only_new_runs(tmp_path, monkeypatch):
    import json
    import sqlite3
    import sys

    from proofops_api.hosted_analysis import operator_profiles
    from pypdf import PdfWriter

    from evaluation import local_upstage_pilot as pilot
    from evaluation.hosted_r108 import prepare_argv

    config = dict(
        analysis_profile="finals-unattended-v2",
        llm_max_workers=16,
        extract_batch_calls=32,
        report_year=2025,
        period_start="2024-01-01",
        period_end="2024-12-31",
    )
    assert operator_profiles(config)["llm_max_workers"] == 16
    pdf = tmp_path / "selected.pdf"
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.write(pdf)
    monkeypatch.setattr(sys, "argv", prepare_argv(pdf, tmp_path / "state", TENANT, config))
    assert pilot.main() == 0
    with sqlite3.connect(tmp_path / "state/state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["extraction_limits"]["max_calls"] == 32
    assert snapshot["analysis_profile_policy"]["stage_overlap"] is False
    assert (
        snapshot["analysis_profile_policy"]["verified_read_cache"]["profile"]
        == "exact-verified-read-v4"
    )
    assert operator_profiles({})["extract_batch_calls"] == 20
    for invalid in (0, 257, True, "32"):
        with pytest.raises(ValueError, match="HOSTED_EXTRACT_BATCH_INVALID"):
            operator_profiles(config | dict(extract_batch_calls=invalid))


@pytest.mark.parametrize(
    "changed", ["tenant", "source", "graph", "refs", "run", "runtime", "policy", "legacy"]
)
def test_every_changed_input_uses_original_replay(fresh, monkeypatch, changed):
    args, calls, ref = fresh
    args = dict(args)
    if changed == "tenant":
        args["tenant_id"] = "other"
    elif changed == "source":
        args["source"] += b"changed"
    elif changed == "graph":
        args["graph"] = replace(args["graph"], blocks=())
    elif changed == "refs":
        args["discovery"] = discovery_for(args["graph"], (replace(ref, quote="changed"),))
    elif changed == "run":
        args["receipt"] = dict(args["receipt"], run_id="other")
    elif changed == "runtime":
        monkeypatch.setenv("DEVELOPER_DIR", "/changed")
    elif changed == "policy":
        args["policy"] = dict(args["policy"], changed=True)
    else:
        monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v1")
    replay_claims_cached(**args)
    assert calls == [1]


def test_page_preparation_overlaps_provider_and_preserves_order():
    from proofops_worker.extract_runner import prefetch_packets

    entered = threading.Event()
    packets = [
        dict(untrusted_document_data=dict(source_id=str(i), page_num=page))
        for i, page in enumerate((1, 2, 1))
    ]

    def prepare(page):
        if page[0]["untrusted_document_data"]["page_num"] == 2:
            assert entered.wait(2), "next page was prepared before first call started"

    def invoke(packet):
        entered.set()
        return packet["untrusted_document_data"]["source_id"]

    assert list(prefetch_packets(packets, invoke, max_workers=2, prepare_pages=prepare)) == [
        "0",
        "1",
        "2",
    ]


def test_larger_frozen_window_groups_checkpoints_with_same_paid_bound(tmp_path, monkeypatch):
    from proofops_worker.extract_batch import run_batches

    from tests.acceptance.test_upload import TENANT as UPLOAD_TENANT
    from tests.integration.test_extract_batch_continuation import setup_run

    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v2")
    _, run, runner, _, probe, _ = setup_run(
        tmp_path, monkeypatch, paragraphs=31, limit=32, extractor_budget=40
    )
    assert runner.run_once(tenant_id=UPLOAD_TENANT, run_id=run) == "committed"
    assert len(probe.calls) == 31
    assert (
        run_batches(runner, tenant_id=UPLOAD_TENANT, run_id=run, batches=10)[0]["status"]
        == "complete"
    )
    assert len(probe.calls) == 31


def test_pa1_snapshot_keeps_its_original_execution_policy():
    from proofops.application.analysis_profile import V2_POLICY, V2_PRE_PA2_POLICY, policy_for

    old_hash = "626d4f0075d7c66dd938aa9a04242943cfb7db0a5cc2ee073a53e90f7ead9ec1"
    assert canonical_hash(V2_PRE_PA2_POLICY) == old_hash
    assert policy_for("finals-unattended-v2", pinned_hash=old_hash) == V2_PRE_PA2_POLICY
    assert canonical_hash(V2_POLICY) != old_hash


@pytest.mark.parametrize("invalid", ["cancel", "expired", "fence"])
def test_one_transaction_fence_rejects_before_provider(tmp_path, monkeypatch, invalid):
    from proofops_worker.consumer import StageFailure
    from proofops_worker.extract_runner import fence_provider_call

    from tests.acceptance.test_jobs import MESSAGE, RUN, seeded
    from tests.acceptance.test_jobs import TENANT as JOB_TENANT

    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v2")
    jobs = seeded(tmp_path / "jobs.sqlite3")
    lease = jobs.claim_job(MESSAGE, owner="pa2", now=0, lease_seconds=10)
    jobs.can_call = lambda *a, **k: pytest.fail("duplicate guard transaction")
    runner = SimpleNamespace(store=SimpleNamespace(jobs=jobs), clock=lambda: 1)
    fence_provider_call(runner, lease, {})
    if invalid == "cancel":
        jobs.cancel_run(
            JOB_TENANT,
            RUN,
            expected_revision=jobs.get_run(JOB_TENANT, RUN)["revision"],
            idempotency_key="pa2-cancel-000001",
            reason="test",
            actor_sub="test",
            now=2,
        )
    elif invalid == "expired":
        runner.clock = lambda: 301
    else:
        lease = replace(lease, fencing_token=lease.fencing_token + 1)
    with pytest.raises(StageFailure, match="LEASE_LOST"):
        fence_provider_call(runner, lease, {})
