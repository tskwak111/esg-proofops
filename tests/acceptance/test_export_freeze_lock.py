"""X1: report validation must not hold SQLite's writer or publish stale input."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from threading import Barrier

import proofops.adapters.local.export_store as export_module
import pytest
from proofops.application.element_evidence_encoding import (
    ELEMENT_EVIDENCE_INLINE,
    ELEMENT_EVIDENCE_V1,
    ElementEvidenceExpansionLimit,
)
from proofops.application.exports import ExportRejected, create_snapshot
from proofops.domain.rulepacks import canonical_json

from tests.acceptance.test_export_shared_element_evidence import evidence
from tests.acceptance.test_exports import archive, create, exports


def reserve(ws, key="x1-freeze-regression", *, allow_partial=True):
    return ws["export_store"].reserve(
        ws["actor"],
        ws["run"],
        dict(formats=["json"], allow_partial=allow_partial),
        key,
        now=ws["now"][0],
    )


@pytest.mark.parametrize("encoding", [ELEMENT_EVIDENCE_V1, ELEMENT_EVIDENCE_INLINE])
@pytest.mark.parametrize("mutate_epoch", [False, True])
def test_independent_writer_during_validation_and_epoch_recheck(
    tmp_path, monkeypatch, encoding, mutate_epoch
):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    store.element_evidence_encoding = encoding
    monkeypatch.setattr(
        ws["runner"].claims, "missing_evidence", lambda *a, **k: deepcopy(evidence())
    )
    export_id = reserve(ws)
    captured = store.capture(tenant, export_id)
    build = export_module.build_report_model
    writes = []

    def validate(manifest, decisions):
        # An independent connection exercises real writer exclusion, not a mock lock.
        with sqlite3.connect(ws["jobs"].path, timeout=0.05, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            if mutate_epoch:
                run = ws["jobs"]._get(db, tenant, ws["run"], "run", "META")
                ws["jobs"]._bump_run(db, run)
            else:
                ws["jobs"]._put(db, tenant, ws["run"], "x1_probe", "writer", {"ok": True})
            db.commit()
            writes.append(True)
        return build(manifest, decisions)

    monkeypatch.setattr(export_module, "build_report_model", validate)
    try:
        assert store.freeze(tenant, export_id, captured) is not mutate_epoch
        assert writes == [True]
        frozen = store.frozen(tenant, export_id)
        assert (frozen is None) is mutate_epoch
        if frozen is not None:
            assert canonical_json(frozen) == canonical_json(captured)
    finally:
        ws["http"].close()


def test_validated_bytes_are_pinned_even_when_capture_object_changes(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    export_id = reserve(ws)
    captured = store.capture(tenant, export_id)
    expected = canonical_json(captured).encode()
    claim_id = next(iter(captured["decisions"]))
    build = export_module.build_report_model

    def validate(manifest, decisions):
        model = build(manifest, decisions)
        captured["decisions"][claim_id]["claim_quote"] = "changed after validation"
        return model

    monkeypatch.setattr(store, "capture", lambda *a: captured)
    monkeypatch.setattr(export_module, "build_report_model", validate)
    try:
        result = create_snapshot(store, tenant, export_id)
        assert canonical_json(result).encode() == expected
        assert canonical_json(store.frozen(tenant, export_id)).encode() == expected
        assert store.state(tenant, export_id)["snapshot_sha256"] == sha256(expected).hexdigest()
        assert captured["decisions"][claim_id]["claim_quote"] == "changed after validation"
    finally:
        ws["http"].close()


def test_competing_freezes_commit_one_hash_pinned_snapshot(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    export_id = reserve(ws)
    first = store.capture(tenant, export_id)
    second = deepcopy(first)
    claim_id = next(iter(second["decisions"]))
    second["decisions"][claim_id]["claim_quote"] = "other candidate snapshot"
    barrier = Barrier(2)
    build = export_module.build_report_model

    def validate(manifest, decisions):
        barrier.wait(timeout=2)
        return build(manifest, decisions)

    monkeypatch.setattr(export_module, "build_report_model", validate)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(store.freeze, tenant, export_id, item) for item in (first, second)
            ]
            outcomes = [future.result(timeout=5) for future in futures]
        assert sorted(outcomes) == [False, True]
        winner = (first, second)[outcomes.index(True)]
        raw = canonical_json(winner).encode()
        assert store.state(tenant, export_id)["snapshot_sha256"] == sha256(raw).hexdigest()
        assert store.frozen(tenant, export_id) == json.loads(raw)
        with ws["jobs"]._transaction() as db:
            assert len(ws["jobs"]._all(db, tenant, ws["run"], "export_snapshot")) == 1
            assert not ws["jobs"]._all(db, tenant, ws["run"], "export_artifact")
    finally:
        ws["http"].close()


def test_epoch_changes_during_validation_requeue_then_http_poll_resumes(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    build = export_module.build_report_model
    attempts = []

    def validate(manifest, decisions):
        with sqlite3.connect(ws["jobs"].path, timeout=0.05, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            run = ws["jobs"]._get(db, tenant, ws["run"], "run", "META")
            ws["jobs"]._bump_run(db, run)
            db.commit()
        attempts.append(manifest["mutation_epoch"])
        return build(manifest, decisions)

    monkeypatch.setattr(export_module, "build_report_model", validate)
    try:
        response = create(ws, formats=["json"])
        assert response.status_code == 202, response.text
        result = response.json()
        export_id = result["export_id"]
        assert result["state"] == "queued" and len(attempts) == 4
        assert store.state(tenant, export_id)["errors"] == ["EXPORT_SNAPSHOT_BUSY"]
        assert store.frozen(tenant, export_id) is None
        assert ws["http"].post(f"/v1/exports/{export_id}/download").status_code == 409
        monkeypatch.setattr(export_module, "build_report_model", build)
        ws["now"][0] += 6
        resumed = ws["http"].get(f"/v1/exports/{export_id}")
        assert resumed.status_code == 200 and resumed.json()["state"] == "ready"
        bundle, _, _ = archive(ws, resumed.json())
        report = json.loads(bundle.read("report.json"))
        assert report["snapshot_epoch"] == ws["jobs"].get_run(tenant, ws["run"])["mutation_epoch"]
    finally:
        ws["http"].close()


@pytest.mark.parametrize("step", ["hash", "decode"])
def test_frozen_hash_and_json_restore_release_writer(tmp_path, monkeypatch, step):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    export_id = reserve(ws)
    captured = store.capture(tenant, export_id)
    assert store.freeze(tenant, export_id, captured)
    raw = canonical_json(captured).encode()
    original = export_module.sha256 if step == "hash" else export_module.json.loads
    writes = []

    def restore(value, *args, **kwargs):
        if value == raw:
            with sqlite3.connect(ws["jobs"].path, timeout=0.05, isolation_level=None) as db:
                db.execute("BEGIN IMMEDIATE")
                store.jobs._put(db, tenant, ws["run"], "x1_probe", step, {"ok": True})
                db.commit()
                writes.append(True)
        return original(value, *args, **kwargs)

    if step == "hash":
        monkeypatch.setattr(export_module, "sha256", restore)
    else:
        monkeypatch.setattr(export_module.json, "loads", restore)
    try:
        assert canonical_json(store.frozen(tenant, export_id)).encode() == raw
        assert writes == [True]
    finally:
        ws["http"].close()


@pytest.mark.parametrize("error", [ElementEvidenceExpansionLimit, ValueError])
def test_stale_validation_rejection_retries_instead_of_failing(tmp_path, monkeypatch, error):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    export_id = reserve(ws)
    captured = store.capture(tenant, export_id)

    def reject(manifest, decisions):
        with ws["jobs"]._transaction() as db:
            run = ws["jobs"]._get(db, tenant, ws["run"], "run", "META")
            ws["jobs"]._bump_run(db, run)
        raise error("rejection for the old epoch")

    monkeypatch.setattr(export_module, "build_report_model", reject)
    try:
        assert not store.freeze(tenant, export_id, captured)
        assert store.frozen(tenant, export_id) is None
        assert store.state(tenant, export_id)["response"]["state"] == "queued"
        assert store.state(tenant, export_id)["errors"] == []
    finally:
        ws["http"].close()


@pytest.mark.parametrize("failure", ["integrity", "snapshot_size", "final_only"])
def test_validation_failure_is_terminal_without_snapshot_or_recapture(
    tmp_path, monkeypatch, failure
):
    ws = exports(tmp_path, monkeypatch)
    store, actor = ws["export_store"], ws["actor"]
    key = "x1-terminal-failure"
    export_id = reserve(ws, key, allow_partial=failure != "final_only")
    captured = store.capture(actor.tenant_id, export_id)
    code = {
        "integrity": "EXPORT_INTEGRITY_FAILED",
        "snapshot_size": "EXPORT_SIZE_LIMIT",
        "final_only": "REPORT_NOT_FINALIZABLE",
    }[failure]
    if failure == "integrity":
        captured["manifest"]["source_sha256"] = "0" * 64
    elif failure == "snapshot_size":
        monkeypatch.setattr(export_module, "MAX_EXPORT_BYTES", 100)
    captures = []

    def capture(*args):
        captures.append(True)
        return captured

    monkeypatch.setattr(store, "capture", capture)
    try:
        first = ws["exports"].get(actor, export_id, now=ws["now"][0])
        assert first["state"] == "failed"
        assert store.state(actor.tenant_id, export_id)["errors"] == [code]
        assert ws["exports"].get(actor, export_id, now=ws["now"][0] + 10) == first
        with pytest.raises(ExportRejected, match=code):
            ws["exports"].create(
                actor,
                ws["run"],
                dict(formats=["json"], allow_partial=failure != "final_only"),
                key,
                now=ws["now"][0] + 10,
            )
        assert captures == [True]
        assert store.frozen(actor.tenant_id, export_id) is None
        with ws["jobs"]._transaction() as db:
            assert not ws["jobs"]._all(db, actor.tenant_id, ws["run"], "export_artifact")
    finally:
        ws["http"].close()


def test_frozen_snapshot_still_rejects_changed_bytes(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    store, tenant = ws["export_store"], ws["actor"].tenant_id
    export_id = reserve(ws)
    assert store.freeze(tenant, export_id, store.capture(tenant, export_id))
    read = store.jobs._raw

    def corrupt(db, tenant, run, kind, key):
        raw = read(db, tenant, run, kind, key)
        return raw + b" " if kind == "export_snapshot" and raw is not None else raw

    monkeypatch.setattr(store.jobs, "_raw", corrupt)
    try:
        with pytest.raises(ExportRejected, match="EXPORT_INTEGRITY_FAILED"):
            store.frozen(tenant, export_id)
    finally:
        ws["http"].close()


def test_claim_limit_still_fails_before_freeze(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    tenant = ws["actor"].tenant_id
    with ws["jobs"]._transaction() as db:
        run = ws["jobs"]._get(db, tenant, ws["run"], "run", "META")
        run["coverage"]["claims_discovered"] = 1001
        ws["jobs"]._put(db, tenant, ws["run"], "run", "META", run)

    def unexpected_freeze(*args):
        pytest.fail("over-limit capture must not reach freeze")

    monkeypatch.setattr(ws["export_store"], "freeze", unexpected_freeze)
    try:
        response = create(ws, formats=["json"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "EXPORT_SIZE_LIMIT"
        with ws["jobs"]._transaction() as db:
            states = ws["jobs"]._all(db, tenant, ws["run"], "export_state")
            assert len(states) == 1 and states[0]["response"]["state"] == "failed"
            assert not ws["jobs"]._all(db, tenant, ws["run"], "export_snapshot")
            assert not ws["jobs"]._all(db, tenant, ws["run"], "export_artifact")
    finally:
        ws["http"].close()


def test_concurrent_terminal_failure_is_not_reopened_by_validation(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    store, actor = ws["export_store"], ws["actor"]
    export_id = reserve(ws)
    build = export_module.build_report_model

    def validate(manifest, decisions):
        store.defer(actor.tenant_id, export_id, "EXPORT_SIZE_LIMIT", now=ws["now"][0])
        return build(manifest, decisions)

    monkeypatch.setattr(export_module, "build_report_model", validate)
    try:
        result = ws["exports"].get(actor, export_id, now=ws["now"][0])
        assert result["state"] == "failed"
        assert store.state(actor.tenant_id, export_id)["errors"] == ["EXPORT_SIZE_LIMIT"]
        assert store.frozen(actor.tenant_id, export_id) is None
        with ws["jobs"]._transaction() as db:
            assert not ws["jobs"]._all(db, actor.tenant_id, ws["run"], "export_artifact")
    finally:
        ws["http"].close()
