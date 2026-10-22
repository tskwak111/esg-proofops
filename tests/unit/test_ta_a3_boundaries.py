"""Hosted facade contracts captured before TA A3 separation; offline transports only."""

import json
import sqlite3
import time
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_analysis import MODEL, WIRE_POLICY, HostedLunaProbe
from proofops_api.hosted_store import (
    HostedError,
    HostedSettings,
    HostedStore,
    day,
    digest,
    identifier,
    micros,
    usd,
)

TENANT = "10000000-0000-0000-0000-000000000001"
DOCUMENT = "20000000-0000-0000-0000-000000000002"
RUN = "30000000-0000-0000-0000-000000000003"
NOW = 1800000000.0
SOURCE = b"original source bytes\n"
INPUT_SHA = digest(b'{"input":"claim"}')


def schema_hash(store):
    with store.transaction(readonly=True) as db:
        return canonical_hash(
            {
                schema: [
                    list(row)
                    for row in db.execute(
                        f"SELECT type,name,tbl_name,sql FROM {schema}.sqlite_master "
                        "WHERE sql IS NOT NULL ORDER BY type,name"
                    )
                ]
                for schema in ("main", "deletion")
            }
        )


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    store = HostedStore(
        HostedSettings(
            root=tmp_path / "private",
            origin="https://app.example.com",
            secret="x" * 40,
            event_id="a3",
            backend="r108",
            accept_runs=True,
        )
    )
    auth = SimpleNamespace(tenant_id=TENANT, user_sub="a3-user", has_capability=lambda _: True)
    with store.transaction() as db:
        db.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
            (TENANT, DOCUMENT, digest(SOURCE), 1, len(SOURCE), NOW, NOW + 86400, "v1"),
        )
        db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,'queued',?,?,?,?,0,0,NULL,NULL)",
            (
                TENANT,
                RUN,
                DOCUMENT,
                store.user_hash(auth.user_sub),
                "[1]",
                NOW,
                day(NOW),
                "a3",
                1000000,
            ),
        )
        db.execute(
            "INSERT INTO deletion.spend VALUES (?,?,?,?,?,?,'reserved')",
            (RUN, store.user_hash(auth.user_sub), day(NOW), "a3", 1000000, NOW),
        )
    directory = store.document_dir(TENANT, DOCUMENT)
    directory.mkdir(parents=True)
    (directory / "original.pdf").write_bytes(SOURCE)
    return store, auth


def ledger(store):
    with store.transaction(readonly=True) as db:
        costs = [
            list(row)
            for row in db.execute(
                "SELECT provider,input_sha256,bound,actual,status FROM deletion.costs "
                "ORDER BY call_id"
            )
        ]
        spend = list(db.execute("SELECT amount,status FROM deletion.spend").fetchone())
    return costs, spend


def test_public_contract_and_schema(seeded):
    store, _ = seeded
    assert schema_hash(store) == "49d99297c3c71e5b495cc9ebde0dc83a1dfe6bda0b6cca9b8412c3df13b682f7"
    assert (
        canonical_hash(create_hosted_app(store.settings).openapi())
        == "ea3b5f378da25a80ec170ce17d57e2c41985fea1829f1f7bb868ea20c738b089"
    )
    assert digest("한글") == "bd87f9bb68b67d2fa1cb82b6751820e946d5b1316d25d5fd96512fb4be44a2a8"
    assert micros("0.000001") == 1
    assert usd(11000) == "0.011000"
    assert identifier(TENANT) == TENANT
    with pytest.raises(HostedError) as caught:
        identifier("invalid")
    assert (caught.value.code, caught.value.status, caught.value.retry_after) == (
        "RESOURCE_NOT_FOUND",
        404,
        None,
    )
    with pytest.raises(ValueError, match="invalid micro-USD amount"):
        micros("0.0000001")


def test_attached_transaction_rolls_back_both_databases(seeded):
    store, _ = seeded
    with pytest.raises(RuntimeError, match="rollback"):
        with store.transaction() as db:
            assert db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete"
            assert db.execute("PRAGMA deletion.journal_mode").fetchone()[0] == "delete"
            db.execute("UPDATE runs SET status='failed'")
            db.execute("UPDATE deletion.spend SET amount=1")
            raise RuntimeError("rollback")
    assert store.get_run(TENANT, RUN)["status"] == "queued"
    assert ledger(store) == ([], [1000000, "reserved"])
    with store.transaction(readonly=True) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("UPDATE deletion.spend SET amount=1")


def test_queue_drain_lease_expiry_and_zero_dispatch_release(seeded):
    store, _ = seeded
    assert store.drain(now=NOW) == {
        "maintenance": True,
        "message": "서버 점검 중입니다. 진행 중 분석은 계속 처리하며 새 분석은 점검 후 접수합니다.",
        "running": 0,
        "queued": 1,
    }
    assert store.claim(now=NOW) is None
    assert store.resume(now=NOW)["maintenance"] is False
    job = store.claim(now=NOW)
    assert (job["status"], job["fence"], job["lease_until"]) == ("running", 1, NOW + 1900)
    assert store.claim(now=NOW) is None
    store.control_state(now=NOW + 1901)
    result = store.get_run(TENANT, RUN)
    assert (result["status"], result["error_code"]) == ("failed", "LEASE_EXPIRED_NO_DISPATCH")
    assert ledger(store) == ([], [0, "settled"])


@pytest.mark.parametrize("deleted", [False, True])
def test_reservation_before_transport_and_late_settlement(seeded, monkeypatch, deleted):
    store, auth = seeded
    job = store.claim(now=NOW)
    calls = []
    original_purge = store._purge

    def purge(tenant, document, now):
        with store.transaction(readonly=True) as db:
            assert store._deleted(db, tenant, document)
            row = db.execute("SELECT status,fence FROM runs WHERE run_id=?", (RUN,)).fetchone()
            assert tuple(row) == ("cancelled", 2)
        assert (store.document_dir(tenant, document) / "original.pdf").read_bytes() == SOURCE
        return original_purge(tenant, document, now)

    monkeypatch.setattr(store, "_purge", purge)

    def transport(request):
        assert str(UUID(request["request_id"])) == request["request_id"]
        assert ledger(store) == (
            [["openrouter", INPUT_SHA, 11000, None, "reserved"]],
            [1000000, "reserved"],
        )
        calls.append(json.dumps(request | {"request_id": "<uuid>"}, sort_keys=True).encode())
        if deleted:
            assert (
                store.delete_document(auth, DOCUMENT, "delete-key-000001", now=NOW)["status"]
                == "completed"
            )
        else:
            store.cancel(auth, RUN, now=NOW)
        return request | {"actual_usd": "0.003000", "payload": {"unknown": True}}

    response = store.dispatch(
        job, "openrouter", "call-1", INPUT_SHA, Decimal("0.011"), transport, now=NOW
    )
    assert len(calls) == 1
    assert calls[0] == (
        b'{"input_sha256": "23930966c05b0fb14279543e79936e9a8be13a86d8365dd'
        b'13be739aed54892c3", "provider": "openrouter", "request_id": "<uui'
        b'd>"}'
    )
    assert response["payload"] == {"unknown": True}
    assert ledger(store) == ([["openrouter", INPUT_SHA, 11000, 3000, "settled"]], [3000, "settled"])
    assert store.budget_totals() == {"event_reserved_usd": "0.003000"}
    with pytest.raises(HostedError) as caught:
        store.finish(job, "partial_blocked", now=NOW)
    assert caught.value.code == ("RESOURCE_NOT_FOUND" if deleted else "LEASE_LOST")


@pytest.mark.parametrize("failure", ["network", "receipt"])
def test_uncertain_cost_and_duplicate_dispatch_remain_reserved(seeded, failure):
    store, _ = seeded
    job = store.claim(now=NOW)
    calls = []

    def transport(request):
        calls.append(request)
        if failure == "network":
            raise TimeoutError("uncertain")
        return request | {"request_id": "wrong", "actual_usd": "0.001000"}

    with pytest.raises(HostedError) as caught:
        store.dispatch(job, "openrouter", "call-1", INPUT_SHA, Decimal("0.011"), transport, now=NOW)
    assert caught.value.code == (
        "PROCESSING_UNCERTAIN" if failure == "network" else "RECEIPT_MISMATCH"
    )
    assert ledger(store) == (
        [["openrouter", INPUT_SHA, 11000, None, "accounting_pending"]],
        [1000000, "accounting_pending"],
    )
    with pytest.raises(HostedError) as caught:
        store.dispatch(job, "openrouter", "call-1", INPUT_SHA, Decimal("0.011"), transport, now=NOW)
    assert caught.value.code == (
        "DISPATCH_ALREADY_RECORDED" if failure == "network" else "LEASE_LOST"
    )
    assert len(calls) == 1


def test_probe_request_hash_and_reservation_count(seeded):
    store, _ = seeded
    job = store.claim(now=NOW)
    body = {
        "model": MODEL,
        "provider": WIRE_POLICY["provider"],
        "messages": [{"role": "user", "content": "claim"}],
    }
    calls = []

    def post(request):
        assert request == body
        assert ledger(store)[0] == [["openrouter", canonical_hash(body), 11000, None, "reserved"]]
        calls.append(json.dumps(request, sort_keys=True).encode())
        return {"model": MODEL, "usage": {"cost": "0.0020001"}, "choices": []}

    probe = object.__new__(HostedLunaProbe)
    probe.store, probe.job, probe.post = store, job, post
    assert probe._post(body) == {"model": MODEL, "usage": {"cost": "0.0020001"}, "choices": []}
    assert len(calls) == 1
    assert digest(calls[0]) == "7ce497bfbe8528cb06b012b1a5a073bbee891f2294753f8262e5365f4eb6bc7b"
    store.finish(job, "partial_blocked", now=NOW)
    assert ledger(store) == (
        [["openrouter", canonical_hash(body), 11000, 2001, "settled"]],
        [2001, "settled"],
    )


@pytest.mark.parametrize("cancel_during_replay", [False, True])
def test_snapshot_bytes_cold_replay_and_publication_fence(
    seeded, tmp_path, monkeypatch, cancel_during_replay
):
    store, auth = seeded
    job = store.claim(now=NOW)
    source = tmp_path / "analysis"
    original = source / "objects" / "original" / "source.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(SOURCE)
    calls = []
    result = {"claims": [{"state": "unknown"}], "reviews": [], "note": "미확인"}

    def replay(*args):
        # A second connection can obtain a writer: replay must stay outside it.
        with store.transaction() as db:
            assert db.execute("SELECT status FROM runs").fetchone()[0] == "running"
        calls.append(args)
        if cancel_during_replay:
            store.cancel(auth, RUN, now=NOW)
        return result

    monkeypatch.setattr("proofops_api.hosted_results.read_result", replay)
    if cancel_during_replay:
        with pytest.raises(HostedError, match="LEASE_LOST"):
            store.publish_analysis(job, source, "completed", None, publication_handoff=b"invalid")
        assert not (store.document_dir(TENANT, DOCUMENT) / "analysis" / RUN).exists()
    else:
        expected = (
            b'{"page_map":[1],"result":{"claims":[{"state":"unknown"}],"note":"'
            b'\xeb\xaf\xb8\xed\x99\x95\xec\x9d\xb8","reviews":[]},"source_hashes":{"objects/original/sourc'
            b'e.pdf":"75afc22e9a068d97c5142edfc652023f864467bf5cb29e6b08beb6093'
            b'28132a1"},"tenant_id":"10000000-0000-0000-0000-000000000001"}'
        )
        store.publish_analysis(job, source, "completed", None, publication_handoff=b"invalid")
        published = store.document_dir(TENANT, DOCUMENT) / "analysis" / RUN
        assert (published / "result-1.json").read_bytes() == expected
        with store.transaction(readonly=True) as db:
            assert tuple(db.execute("SELECT revision,sha256 FROM result_snapshots").fetchone()) == (
                1,
                digest(expected),
            )
        assert store.get_result(TENANT, RUN) == result
        original_published = published / "objects" / "original" / "source.pdf"
        original_published.write_bytes(b"tampered")
        with pytest.raises(HostedError, match="RESULT_INTEGRITY_UNAVAILABLE"):
            store.get_result(TENANT, RUN)
    assert len(calls) == 1
