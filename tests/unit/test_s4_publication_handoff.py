"""Only the private child's unchanged validated state can skip cold publication."""

import json
import sqlite3
from copy import deepcopy
from uuid import uuid4

import pytest
from proofops.application.analysis_profile import FINALS_I7_POLICY, S4_POLICY
from proofops_api import hosted_publication as handoff


@pytest.fixture
def state(tmp_path, monkeypatch):
    tmp_path = tmp_path / "state"
    tmp_path.mkdir()
    tenant, local_run = str(uuid4()), str(uuid4())
    job = dict(tenant_id=tenant, run_id=str(uuid4()), fence=7)
    (tmp_path / "pilot.json").write_text(json.dumps(dict(tenant_id=tenant, run_id=local_run)))
    (tmp_path / "outcome.json").write_text('{"status":"completed"}')
    (tmp_path / "receipt.json").write_text('{"status":"unresolved"}')
    original = tmp_path / "objects" / "original" / tenant / "source.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original")
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        db.execute("CREATE TABLE run_snapshots (run_id TEXT, payload TEXT)")
        db.execute(
            "INSERT INTO run_snapshots VALUES (?,?)",
            (local_run, json.dumps(dict(analysis_profile_policy=S4_POLICY))),
        )
    calls = []
    content = json.dumps(
        dict(tenant_id=tenant, page_map=[13], source_hashes={}, result={"hold": "unknown"})
    ).encode()
    monkeypatch.setattr(
        "proofops_api.hosted_results.result_snapshot", lambda *a: calls.append(1) or content
    )
    return tmp_path, job, calls, content


def test_private_child_result_is_byte_identical_without_second_reader(state):
    path, job, calls, content = state
    packet = handoff.make_handoff(path, job, [13])
    assert handoff.reuse_handoff(packet, path, job, [13]) == content
    assert calls == [1]


@pytest.mark.parametrize(
    "field",
    [
        "original",
        "db",
        "receipt",
        "outcome",
        "add",
        "tenant",
        "run",
        "fence",
        "pages",
        "runtime",
        "content",
        "truncated",
        "reader",
    ],
)
def test_any_pin_or_scope_change_falls_back(state, monkeypatch, field):
    path, job, _, _ = state
    packet = handoff.make_handoff(path, job, [13])
    job, pages = deepcopy(job), [13]
    if field in {"original", "db", "receipt", "outcome"}:
        file = {
            "original": next((path / "objects").rglob("*.pdf")),
            "db": path / "state.sqlite3",
            "receipt": path / "receipt.json",
            "outcome": path / "outcome.json",
        }[field]
        with file.open("ab") as stream:
            stream.write(b"changed")
    elif field == "add":
        (path / "new.json").write_text("new artifact")
    elif field in {"tenant", "run", "fence"}:
        key = {"tenant": "tenant_id", "run": "run_id", "fence": "fence"}[field]
        job[key] = 8 if field == "fence" else str(uuid4())
    elif field == "pages":
        pages = [14]
    elif field in {"runtime", "reader"}:
        original = handoff.runtime_identity
        monkeypatch.setattr(handoff, "runtime_identity", lambda: original() | {field: "changed"})
    elif field == "content":
        record = json.loads(packet)
        record["content"] = "tampered"
        packet = json.dumps(record).encode()
    else:
        packet = packet[:-5]
    assert handoff.reuse_handoff(packet, path, job, pages) is None


def test_old_policy_and_disk_only_packets_cannot_enable_handoff(state):
    path, job, calls, _ = state
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute(
            "UPDATE run_snapshots SET payload=?",
            (json.dumps(dict(analysis_profile_policy=FINALS_I7_POLICY)),),
        )
    assert handoff.make_handoff(path, job, [13]) is None
    assert calls == []
    assert handoff.reuse_handoff(None, path, job, [13]) is None


def test_symlinked_workspace_is_ineligible(state):
    path, job, _, _ = state
    (path / "alias").symlink_to(path / "receipt.json")
    assert handoff.make_handoff(path, job, [13]) is None


def test_private_fd_is_inherited_and_failed_child_cannot_publish(tmp_path):
    import subprocess
    import sys
    from tempfile import TemporaryFile
    from types import SimpleNamespace

    from proofops_api.hosted_analysis import run_analysis_process

    store = SimpleNamespace(settings=SimpleNamespace(max_active_runs=1))
    script = "import os,sys;os.write(int(sys.argv[1]),b'private-result')"
    with (tmp_path / "lock").open("a+b") as lock, TemporaryFile() as publication:
        run_analysis_process(
            [sys.executable, "-c", script],
            store,
            {},
            lock,
            publication_fd=publication.fileno(),
        )
        publication.seek(0)
        assert publication.read() == b"private-result"
        with pytest.raises(subprocess.CalledProcessError):
            run_analysis_process(
                [sys.executable, "-c", script + ";sys.exit(1)"],
                store,
                {},
                lock,
                publication_fd=publication.fileno(),
            )


def test_publisher_uses_handoff_and_preserves_immutable_revision(state, monkeypatch, tmp_path):
    from tests.test_hosted_analysis import job_setup
    from tests.test_hosted_public import settings

    path, _, calls, _ = state
    store, auth, job = job_setup(settings.__wrapped__(tmp_path / "hosted"))
    local_run = json.loads((path / "pilot.json").read_text())["run_id"]
    (path / "pilot.json").write_text(json.dumps(dict(tenant_id=auth.tenant_id, run_id=local_run)))
    pages = json.loads(job["pages"])
    content = json.dumps(
        dict(
            tenant_id=auth.tenant_id,
            page_map=pages,
            source_hashes={},
            result=dict(claims=[], hold_reasons=["unknown"], confirmed_grade=None),
        )
    ).encode()
    monkeypatch.setattr(
        "proofops_api.hosted_results.result_snapshot", lambda *a: calls.append(1) or content
    )
    packet = handoff.make_handoff(path, job, pages)
    assert packet is not None
    store.publish_analysis(job, path, "partial_blocked", "UNKNOWN", publication_handoff=packet)
    assert calls == [1]
    assert store.get_result(auth.tenant_id, job["run_id"])["confirmed_grade"] is None
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM result_snapshots").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE result_snapshots SET sha256='tampered'")
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "partial_blocked"


@pytest.mark.parametrize("changed", ["receipt", "source", "snapshot"])
def test_mutation_during_child_verification_cannot_be_byte_pinned(state, monkeypatch, changed):
    path, job, _, content = state

    def raced(*args):
        if changed == "snapshot":
            with sqlite3.connect(path / "state.sqlite3") as db:
                db.execute("UPDATE run_snapshots SET payload='{}'")
        else:
            file = (
                path / "receipt.json"
                if changed == "receipt"
                else next((path / "objects").rglob("*.pdf"))
            )
            file.write_bytes(b"changed during verification")
        return content

    monkeypatch.setattr("proofops_api.hosted_results.result_snapshot", raced)
    assert handoff.make_handoff(path, job, [13]) is None


@pytest.mark.parametrize("content", [None, 42, []])
def test_malformed_child_packet_uses_original_replay(state, content):
    path, job, _, _ = state
    packet = json.loads(handoff.make_handoff(path, job, [13]))
    packet["content"] = content
    assert handoff.reuse_handoff(json.dumps(packet).encode(), path, job, [13]) is None


def test_real_blob_checkpoints_are_pinned_without_deserialization(state):
    path, job, _, _ = state
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute("CREATE TABLE job_records (kind TEXT, record_id TEXT, value BLOB)")
        db.execute(
            "INSERT INTO job_records VALUES ('artifact','checkpoint',?)",
            (b"original checkpoint bytes",),
        )
    packet = handoff.make_handoff(path, job, [13])
    assert packet is not None
    assert handoff.reuse_handoff(packet, path, job, [13]) is not None
    with sqlite3.connect(path / "state.sqlite3") as db:
        db.execute("UPDATE job_records SET value=?", (b"changed checkpoint bytes",))
    assert handoff.reuse_handoff(packet, path, job, [13]) is None
