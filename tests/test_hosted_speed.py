"""Hosted result snapshots must avoid replay and retain integrity/deletion gates."""

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from proofops_api.hosted_store import HostedError, HostedStore

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def publish_fixture(settings, tmp_path, monkeypatch):
    store, auth, job = job_setup(settings)
    source = tmp_path / "analysis"
    source.mkdir()
    original = source / "objects/original/source.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"source bytes")
    calls = []

    def replay(*args):
        calls.append(args)
        return {"claims": [{"claim_id": "verified"}], "reviews": []}

    monkeypatch.setattr("proofops_api.hosted_results.read_result", replay)
    store.publish_analysis(job, source, "partial_blocked", "R108_NEEDS_REVIEW")
    path = store.document_dir(auth.tenant_id, job["document_id"]) / "analysis" / job["run_id"]
    return store, auth, job, path, calls


def test_completed_reads_use_one_verified_snapshot(settings, tmp_path, monkeypatch):
    store, auth, job, path, calls = publish_fixture(settings, tmp_path, monkeypatch)
    assert len(calls) == 1
    monkeypatch.setattr(
        "proofops_api.hosted_results.read_result",
        lambda *a: pytest.fail("request replayed source"),
    )
    for instance in (store, HostedStore(settings)):
        assert instance.get_result(auth.tenant_id, job["run_id"])["claims"]
        assert instance.get_run(auth.tenant_id, job["run_id"])["result"]["claims"]
    with pytest.raises(HostedError, match="RESOURCE_NOT_FOUND"):
        store.get_result(str(uuid4()), job["run_id"])
    with store.transaction() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable result snapshot"):
            db.execute("UPDATE result_snapshots SET sha256=?", ("a" * 64,))
    deleted = store.delete_document(auth, job["document_id"], "p6-delete-snapshot", now=time.time())
    assert deleted["status"] == "completed"
    assert not path.exists()
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM result_snapshots").fetchone()[0] == 0


@pytest.mark.parametrize("target", ["snapshot", "source", "missing_snapshot", "missing_anchor"])
def test_snapshot_and_source_hashes_fail_closed(settings, tmp_path, monkeypatch, target):
    store, auth, job, path, _ = publish_fixture(settings, tmp_path, monkeypatch)
    if target == "missing_anchor":
        with store.transaction() as db:
            db.execute("DELETE FROM result_snapshots")
    elif target == "source":
        (path / "objects/original/source.pdf").write_bytes(b"changed")
    else:
        snapshot = next(path.glob("result-*.json"))
        if target == "missing_snapshot":
            snapshot.unlink()
        else:
            snapshot.chmod(0o600)
            data = json.loads(snapshot.read_text())
            data["result"]["claims"] = []
            snapshot.write_text(json.dumps(data))
    with pytest.raises(HostedError, match="RESULT_INTEGRITY_UNAVAILABLE"):
        store.get_result(auth.tenant_id, job["run_id"])


def test_publication_replay_releases_writer_and_rechecks_cancellation(
    settings, tmp_path, monkeypatch
):
    store, auth, job = job_setup(settings)
    source = tmp_path / "private-workspace"
    source.mkdir()
    entered, release = threading.Event(), threading.Event()

    def replay(*args):
        entered.set()
        assert release.wait(5)
        return {"claims": []}

    monkeypatch.setattr("proofops_api.hosted_results.read_result", replay)
    with ThreadPoolExecutor(2) as pool:
        publishing = pool.submit(
            store.publish_analysis, job, source, "partial_blocked", "R108_NEEDS_REVIEW"
        )
        assert entered.wait(2)
        try:
            cancelling = pool.submit(store.cancel, auth, job["run_id"], now=time.time())
            assert cancelling.result(timeout=1)["status"] == "cancelled"
        finally:
            release.set()
        with pytest.raises(HostedError, match="LEASE_LOST"):
            publishing.result(timeout=2)
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM result_snapshots").fetchone()[0] == 0


@pytest.mark.parametrize("configured,expected", [(None, 8), (1, 1), (8, 8), (16, 16)])
def test_operator_concurrency(configured, expected):
    from proofops_api.hosted_analysis import operator_profiles

    config = {} if configured is None else {"llm_max_workers": configured}
    assert operator_profiles(config)["llm_max_workers"] == expected


@pytest.mark.parametrize("configured", [True, False, 0, 17, "8", 1.5, None])
def test_invalid_operator_concurrency(configured):
    from proofops_api.hosted_analysis import operator_profiles

    with pytest.raises(ValueError, match="HOSTED_LLM_CONCURRENCY_INVALID"):
        operator_profiles({"llm_max_workers": configured})
