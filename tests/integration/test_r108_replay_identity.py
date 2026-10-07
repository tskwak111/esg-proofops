"""Offline regression checks for parse-graph reuse and fresh continuation guards."""

from dataclasses import asdict, replace

import pytest
from proofops.adapters.local import claim_store
from proofops.application.ports.jobs import JobMessage
from proofops.domain.provenance import canonical_hash
from proofops_worker import extract_runner

from tests.acceptance.test_upload import TENANT
from tests.integration.test_extract_batch_continuation import setup_run


def test_completed_replay_loads_graph_once_and_preserves_checkpoint(tmp_path, monkeypatch):
    service, run_id, runner, _, probe, graph = setup_run(tmp_path, monkeypatch, paragraphs=2)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    head = service.store.jobs.get_run(TENANT, run_id)
    checkpoint = service.store.jobs.read_checkpoint(JobMessage(**head["extract_job"]))
    calls = []

    def load(*a, **kw):
        calls.append(True)
        return graph

    monkeypatch.setattr(claim_store, "load_run_graph", load)
    monkeypatch.setattr(extract_runner, "load_run_graph", load)
    before = canonical_hash(asdict(runner.claims.load(TENANT, run_id)))
    calls.clear()
    assert runner.run_batch(tenant_id=TENANT, run_id=run_id)["status"] == "complete"
    assert len(calls) == 1
    assert len(probe.calls) == 2
    assert service.store.jobs.read_checkpoint(JobMessage(**head["extract_job"])) == checkpoint
    assert canonical_hash(asdict(runner.claims.load(TENANT, run_id))) == before


def test_extraction_graph_does_not_inherit_claim_span_annotations(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from proofops.adapters.local import claim_source_policies, native_replay_cache, run_artifacts
    from proofops.application.evidence.span_citations import span_verified_graph

    service, run_id, runner, _, _, graph = setup_run(tmp_path, monkeypatch, paragraphs=2)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    snapshot = service.store.snapshot(TENANT, run_id)
    monkeypatch.setattr(
        service.store, "snapshot", lambda *a: snapshot | {"claim_source_policy": {}}
    )
    original = service.store.jobs.read_checkpoint

    def checkpoint(message):
        import json

        payload = original(message)
        if message.stage == "extract":
            envelope = json.loads(payload)
            envelope["claim_source_attestation"] = {}
            envelope["schema"] = "local_extract_checkpoint_v2"
            return json.dumps(envelope).encode()
        return payload

    monkeypatch.setattr(service.store.jobs, "read_checkpoint", checkpoint)
    head = service.store.jobs.get_run(TENANT, run_id)
    from hashlib import sha256

    head["claim_snapshot_sha256"] = sha256(
        checkpoint(JobMessage(**head["extract_job"]))
    ).hexdigest()
    monkeypatch.setattr(service.store.jobs, "get_run", lambda *a: head)
    monkeypatch.setattr(claim_source_policies, "claim_source_reader", lambda p: None)
    monkeypatch.setattr(
        run_artifacts,
        "load_run_inputs",
        lambda *a, **kw: (None, SimpleNamespace(content=b"pdf"), None),
    )
    monkeypatch.setattr(
        native_replay_cache,
        "replay_claims_cached",
        lambda **kw: (kw["discovery"], span_verified_graph(kw["graph"], (), "a" * 64)),
    )
    assert runner.claims.load_evidence(TENANT, run_id)[2] != graph
    assert runner.claims.load_evidence(TENANT, run_id, for_extraction=True)[2] is graph


@pytest.mark.parametrize(
    "field,value",
    [("claim_snapshot_sha256", "0" * 64), ("extract_job", None), ("cancellation_requested", True)],
)
def test_head_change_during_replay_is_rejected(tmp_path, monkeypatch, field, value):
    service, run_id, runner, _, _, graph = setup_run(tmp_path, monkeypatch, paragraphs=2)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    original = service.store.jobs.get_run
    changed = False

    def load(*a, **kw):
        nonlocal changed
        changed = True
        return graph

    def head(*a):
        result = original(*a)
        return result | {field: value} if changed else result

    monkeypatch.setattr(claim_store, "load_run_graph", load)
    monkeypatch.setattr(service.store.jobs, "get_run", head)
    with pytest.raises(ValueError, match="CLAIM_SNAPSHOT_HEAD_CHANGED"):
        runner.claims.load_evidence(TENANT, run_id)


@pytest.mark.parametrize("mutation", ["tenant", "version", "hash", "receipt", "revoked"])
def test_replay_rejects_invalid_inputs(tmp_path, monkeypatch, mutation):
    service, run_id, runner, _, _, graph = setup_run(tmp_path, monkeypatch, paragraphs=2)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    if mutation == "tenant":
        tenant = "foreign"
    else:
        tenant = TENANT
    if mutation == "version":
        monkeypatch.setattr(
            claim_store,
            "load_run_graph",
            lambda *a, **k: replace(graph, document_version_id="foreign"),
        )
    if mutation == "hash":
        original = service.store.jobs.read_checkpoint

        def read(message):
            raw = original(message)
            return raw + b" " if message.stage == "extract" else raw

        monkeypatch.setattr(service.store.jobs, "read_checkpoint", read)
    if mutation == "receipt":
        import json
        from hashlib import sha256

        original = service.store.jobs.read_checkpoint
        head = service.store.jobs.get_run(TENANT, run_id)
        envelope = json.loads(original(JobMessage(**head["extract_job"])))
        envelope["discovery"]["receipts"][0]["raw_response_json"] = '{"spans":[{"bad":true}]}'
        forged = json.dumps(envelope).encode()
        head["claim_snapshot_sha256"] = sha256(forged).hexdigest()
        monkeypatch.setattr(service.store.jobs, "get_run", lambda *a: head)
        monkeypatch.setattr(
            service.store.jobs,
            "read_checkpoint",
            lambda m: forged if m.stage == "extract" else original(m),
        )
    if mutation == "revoked":
        snapshot = service.store.snapshot(TENANT, run_id)
        import json

        with service.store.jobs._transaction() as db:
            # Legacy lifecycle fixtures keep uploads in a separate database;
            # mirror the version row so the production tombstone join is exercised.
            db.execute("CREATE TABLE upload_records (tenant TEXT, kind TEXT, id TEXT, data TEXT)")
            db.execute(
                "INSERT INTO upload_records VALUES (?, 'version', ?, ?)",
                (
                    TENANT,
                    snapshot["document"]["version_id"],
                    json.dumps({"document_id": snapshot["document"]["document_id"]}),
                ),
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS retention_tombstones "
                "(tenant_id TEXT, document_id TEXT)"
            )
            db.execute(
                "INSERT INTO retention_tombstones (tenant_id, document_id) VALUES (?, ?)",
                (TENANT, snapshot["document"]["document_id"]),
            )
    with pytest.raises((ValueError, KeyError)):
        runner.claims.load_evidence(tenant, run_id)


def test_continuation_rejects_head_change_after_evidence_returns(tmp_path, monkeypatch):
    service, run_id, runner, _, probe, _ = setup_run(tmp_path, monkeypatch, paragraphs=2)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    original_load = runner.claims.load_evidence
    original_get = service.store.jobs._get
    changed = False

    def load(*args, **kwargs):
        nonlocal changed
        result = original_load(*args, **kwargs)
        changed = True
        return result

    def get(db, tenant, run, kind, record):
        result = original_get(db, tenant, run, kind, record)
        if changed and kind == "run":
            return result | {"claim_snapshot_sha256": "f" * 64}
        return result

    monkeypatch.setattr(runner.claims, "load_evidence", load)
    monkeypatch.setattr(service.store.jobs, "_get", get)
    with pytest.raises(ValueError, match="CLAIM_SNAPSHOT_HEAD_CHANGED"):
        runner.run_batch(tenant_id=TENANT, run_id=run_id)
    assert len(probe.calls) == 2
