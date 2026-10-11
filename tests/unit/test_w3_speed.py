"""W3 preserves historical policies and complete source receipts."""

from copy import deepcopy
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v10 as v10
from proofops.adapters.local import verified_read_cache as cache
from proofops.adapters.local.claim_source_policies import attest_claims
from proofops.adapters.local.native_replay_cache import replay_claims_cached
from proofops.domain.provenance import canonical_hash

from tests.integration.test_batch_attestation_cache import discovery_for
from tests.unit.test_pb1_source import fixture


@pytest.fixture
def fresh(monkeypatch):
    cache._results.clear()
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v5")
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
    receipt = v10._extend(base, graph, source.content, (ref,), tenant_id=source.tenant_id)
    monkeypatch.setattr(v10.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v10.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(receipt))
    monkeypatch.setattr(v10.PageOCRStore, "from_env", classmethod(lambda cls: object()))
    expected = v10.replay_claim_spans(
        receipt, graph, source.content, discovery, tenant_id=source.tenant_id
    )
    calls = []
    monkeypatch.setattr(v10, "replay_claim_spans", lambda *a, **k: calls.append(1) or expected)
    published = attest_claims(
        reader=v10,
        graph=graph,
        source=source.content,
        refs=(ref,),
        tenant_id=source.tenant_id,
        run_id=run,
        cache=True,
    )
    yield (
        dict(
            reader=v10,
            policy=v10.claim_source_policy(),
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


def test_whole_fresh_v10_receipt_avoids_duplicate_read(fresh):
    args, calls, expected = fresh
    assert replay_claims_cached(**args) == expected
    assert calls == []


@pytest.mark.parametrize("field", ["source", "tenant_id", "run", "receipt", "refs"])
def test_changed_identity_does_not_reuse(fresh, field):
    args, calls, _ = fresh
    args = args | dict(receipt=deepcopy(args["receipt"]))
    if field == "source":
        args["source"] += b"changed"
    elif field == "tenant_id":
        args["tenant_id"] = str(uuid4())
    elif field == "run":
        args["receipt"]["run_id"] = str(uuid4())
    elif field == "receipt":
        args["receipt"]["records"][0]["reason"] = "changed"
    else:
        args["discovery"] = replace(args["discovery"], claims=())
    replay_claims_cached(**args)
    assert calls == [1]


def test_v10_failed_row_projection_preserves_candidate_state(fresh):
    args, _, _ = fresh
    receipt = deepcopy(args["receipt"])
    receipt["records"][0].update(status="unresolved", reason="cell_native_order_unresolved")
    discovery = replace(
        args["discovery"],
        claims=tuple(
            replace(
                c,
                source_quality="verified",
                source_refs=tuple(replace(r, verification_state="verified") for r in c.source_refs),
            )
            for c in args["discovery"].claims
        ),
    )
    result, _ = cache._project_owned_cells(
        receipt, args["graph"], discovery, args["tenant_id"], failed_state="candidate"
    )
    assert result.claims[0].source_quality == "unverified"
    assert result.claims[0].source_refs[0].verification_state == "candidate"


def test_old_v4_does_not_admit_v10(fresh, monkeypatch):
    args, calls, _ = fresh
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", "exact-verified-read-v4")
    replay_claims_cached(**args)
    assert calls == [1]


def test_new_pin_is_opt_in_and_old_policy_is_unchanged():
    from proofops.application.analysis_profile import (
        V2_PA4_POLICY,
        V2_POLICY,
        W3_POLICY,
        policy_for,
        publication_policy_for,
    )

    assert policy_for("finals-unattended-v2") == V2_POLICY
    assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(W3_POLICY)) == W3_POLICY
    assert W3_POLICY["stage_overlap"] is False
    assert (
        publication_policy_for("finals-unattended-v2", pinned_hash=canonical_hash(W3_POLICY))
        == W3_POLICY
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PA4_POLICY))
        == V2_PA4_POLICY
    )
    with pytest.raises(ValueError, match="PUBLICATION_PIN_MISMATCH"):
        publication_policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PA4_POLICY))
    with pytest.raises(ValueError, match="PIN_MISMATCH"):
        policy_for("finals-unattended-v2", pinned_hash="a" * 64)


def test_downloads_parallel_and_provider_order_preserved():
    import threading

    from proofops.adapters.local.upstage_parse import UpstageParseProbe

    probe = object.__new__(UpstageParseProbe)
    probe.download_workers = 4
    barrier = threading.Barrier(3)

    def download(url):
        barrier.wait(timeout=3)
        return {"url": url}

    probe._async_download = download
    urls = ["a", "b", "c"]
    assert probe._download_batches([dict(download_url=u) for u in urls]) == [
        dict(url=u) for u in urls
    ]


def test_rate_limit_reduces_admission_without_retry_or_quota_retry():
    from proofops.adapters.local.provider_concurrency import ProviderConcurrency

    gate = ProviderConcurrency(16, cooldown_seconds=0)
    attempts = []

    def limited():
        attempts.append(1)
        raise ValueError("OPENAI_HTTP_429")

    with pytest.raises(ValueError, match="429"):
        gate.call(limited)
    assert attempts == [1]
    assert gate.snapshot() == dict(limit=8, active=0, peak=1, rate_limits=1, deferred=False)
    with pytest.raises(ValueError, match="QUOTA"):
        gate.call(lambda: (_ for _ in ()).throw(ValueError("OPENAI_INSUFFICIENT_QUOTA")))
    assert gate.snapshot()["rate_limits"] == 1


def test_retry_after_is_a_minimum_and_long_hint_defers_without_dispatch():
    from proofops.adapters.local.openai import _retry_after
    from proofops.adapters.local.provider_concurrency import ProviderConcurrency

    assert _retry_after("6") == 6
    assert _retry_after("nan") is None and _retry_after("-1") is None
    gate = ProviderConcurrency(16, clock=lambda: 10)
    problem = ValueError("OPENAI_HTTP_429")
    problem.retry_after_seconds = 6
    with pytest.raises(ValueError, match="429"):
        gate.call(lambda: (_ for _ in ()).throw(problem))
    assert gate.not_before == 16
    other = ProviderConcurrency(16, clock=lambda: 10)
    problem.retry_after_seconds = 60
    with pytest.raises(ValueError, match="429"):
        other.call(lambda: (_ for _ in ()).throw(problem))
    with pytest.raises(ValueError, match="429"):
        other.call(lambda: pytest.fail("server delay was shortened"))
    assert other.snapshot()["deferred"] is True


@pytest.mark.parametrize(
    "code",
    [
        "rate_limit_exceeded",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
    ],
)
def test_http_hint_is_kept_and_spend_failures_stay_distinct(tmp_path, monkeypatch, code):
    import json

    from proofops.adapters.local import openai

    class Response:
        status = 429

        def getheader(self, name):
            return "60" if name == "Retry-After" else None

        def read(self, limit):
            return json.dumps(dict(error=dict(code=code, message="private details"))).encode()

    class Connection:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(openai.http.client, "HTTPSConnection", Connection)
    probe = openai.OpenAIProbe("offline", tmp_path / "http.sqlite3")
    expected = "OPENAI_HTTP_429" if code == "rate_limit_exceeded" else "OPENAI_INSUFFICIENT_QUOTA"
    with pytest.raises(ValueError, match=expected) as caught:
        probe._post({})
    assert "private" not in str(caught.value)
    if code == "rate_limit_exceeded":
        assert caught.value.retry_after_seconds == 60


def test_admission_is_shared_between_role_probes():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from proofops.adapters.local.provider_concurrency import ProviderConcurrency

    gate = ProviderConcurrency(2)
    entered, release = threading.Event(), threading.Event()
    count = 0
    lock = threading.Lock()

    def post():
        nonlocal count
        with lock:
            count += 1
            if count == 2:
                entered.set()
        assert release.wait(3)
        return count

    with ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(gate.call, post) for _ in range(4)]
        assert entered.wait(3)
        assert gate.snapshot()["active"] == 2
        release.set()
        assert all(f.result() > 0 for f in futures)
    assert gate.snapshot()["peak"] == 2


def test_usage_reads_are_batched_but_unsettled_and_foreign_calls_stay_separate(
    tmp_path, monkeypatch
):
    import json
    import sqlite3

    from proofops.adapters.local.upstage import request_usage

    ledger = tmp_path / "usage.sqlite3"
    receipt = json.dumps(dict(model="gpt-6-luna", input_tokens=2, output_tokens=3))
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE probe_calls (request_id TEXT, committed TEXT, receipt TEXT)")
        db.executemany(
            "INSERT INTO probe_calls VALUES (?,?,?)",
            [(f"r{i}", "0.010000", receipt if i != 1000 else None) for i in range(1001)]
            + [("foreign", "99", receipt)],
        )
    original = sqlite3.connect
    selects = []

    def connect(*a, **k):
        db = original(*a, **k)
        db.set_trace_callback(lambda sql: selects.append(sql) if sql.startswith("SELECT") else None)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    result = request_usage(ledger, [f"r{i}" for i in range(1001)] + ["r0", "missing"])
    assert result == dict(
        model_calls=1001,
        reserved_calls=1001,
        settled_calls=1000,
        unsettled_calls=1,
        input_tokens=2000,
        output_tokens=3000,
        token_usage_complete=False,
        cost_with_vat_reserve_usd="unknown",
        committed_or_reserved_usd="10.010000",
        unknown_reservation_cost_usd="unknown",
    )
    assert len(selects) <= 3


def test_operator_w3_pin_reaches_preparation_and_frozen_run(tmp_path, monkeypatch):
    import json
    import sys

    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.application.analysis_profile import W3_POLICY

    from evaluation import local_upstage_pilot as pilot
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    __import__("pypdfium2")
    monkeypatch.setattr(sys, "platform", "linux")
    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    state = tmp_path / "state"
    pin = canonical_hash(W3_POLICY)
    argv = prepare_argv(
        pdf,
        state,
        "11111111-1111-4111-8111-111111111111",
        dict(
            analysis_profile="finals-unattended-v2",
            report_year=2024,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
        dict(pages=[10, 20], claim_pages=[10], analysis_profile_sha256=pin),
    )
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    manifest = json.loads((state / "pilot.json").read_text())
    snapshot = LocalSQLiteRunStore(state / "state.sqlite3").snapshot(
        manifest["tenant_id"], manifest["run_id"]
    )
    assert snapshot["analysis_profile_policy_sha256"] == pin
    assert snapshot["analysis_profile_policy"] == W3_POLICY
    assert manifest["analysis_policy_sha256"] == pin
