"""HF6: private bounded failure evidence without credentials or guard changes."""

import json
import sqlite3
from dataclasses import replace

import pytest
from proofops_api.hosted_diagnostics import analysis_workspace, retain_failure, write_child_failure
from proofops_api.hosted_store import HostedError

from tests.test_hosted_analysis import job_setup
from tests.test_hosted_public import settings as base_settings


@pytest.fixture
def setup(tmp_path):
    return job_setup(base_settings.__wrapped__(tmp_path))


def seed(workspace):
    state = workspace / "state"
    state.mkdir()
    with sqlite3.connect(state / "state.sqlite3") as db:
        db.execute("CREATE TABLE job_records (kind TEXT, value TEXT)")
        db.execute("INSERT INTO job_records VALUES ('usage',?)", ('{"model_calls":4}',))
        db.execute("CREATE TABLE catalog_cursor_key (secret TEXT)")
        db.execute("INSERT INTO catalog_cursor_key VALUES ('never-copy-credential')")
    receipt = state / "tagging-receipts" / "run" / "preliminary" / "call"
    receipt.mkdir(parents=True)
    (receipt / "request.json").write_text('{"request_id":"call"}')
    (state / "environment.json").write_text('{"OPENAI_API_KEY":"never-copy-credential"}')
    (workspace / "stderr.txt").write_text("never-copy-credential")
    return state


def captured(store):
    return list((store.root / "payloads").glob("*/*/analysis-failures/*"))


def test_failure_keeps_original_error_and_private_operational_state(setup):
    store, _, job = setup
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    error = HostedError("LEASE_LOST")
    with pytest.raises(HostedError) as raised:
        with analysis_workspace(store, job, directory) as workspace:
            state = seed(workspace)
            write_child_failure(state, sqlite3.OperationalError("never-copy-credential"))
            raise error
    assert raised.value is error and not workspace.exists()
    (saved,) = captured(store)
    with sqlite3.connect(saved / "state.sqlite3") as db:
        assert db.execute("SELECT * FROM job_records").fetchone() == ("usage", '{"model_calls":4}')
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("job_records",)
        ]
    assert json.loads((saved / "failure.json").read_text())["exception_type"] == "OperationalError"
    assert (saved / "tagging-receipts/run/preliminary/call/request.json").is_file()
    for file in saved.rglob("*"):
        assert file.stat().st_mode & 0o077 == 0
        if file.is_file():
            assert b"never-copy-credential" not in file.read_bytes()


@pytest.mark.parametrize("status,expected", [("completed", 0), ("partial_blocked", 1)])
def test_only_failed_outcome_is_retained(setup, status, expected):
    store, _, job = setup
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    with analysis_workspace(store, job, directory) as workspace:
        state = seed(workspace)
        (state / "outcome.json").write_text(json.dumps(dict(status=status)))
    assert len(captured(store)) == expected


def test_disabled_full_and_symlink_diagnostics_are_bounded(setup, tmp_path):
    store, _, job = setup
    workspace = tmp_path / "work"
    workspace.mkdir()
    state = seed(workspace)
    secret = tmp_path / "secret.json"
    secret.write_text("never-copy-credential")
    (state / "tagging-receipts" / "linked.json").symlink_to(secret)
    store.settings = replace(store.settings, retain_failed_analysis=False)
    retain_failure(store, job, workspace)
    assert not captured(store)
    store.settings = replace(
        store.settings, retain_failed_analysis=True, failure_diagnostics_max_bytes=32768
    )
    (state / "tagging-receipts" / "large.json").write_bytes(b"x" * 65536)
    retain_failure(store, job, workspace)
    (saved,) = captured(store)
    assert not (saved / "tagging-receipts/linked.json").exists()
    assert not (saved / "tagging-receipts/large.json").exists()
    assert sum(p.stat().st_size for p in saved.rglob("*") if p.is_file()) <= 32768
    manifest = (saved / "manifest.json").read_bytes()
    retain_failure(store, job, workspace)
    assert (saved / "manifest.json").read_bytes() == manifest
    for fence in range(2, 6):
        retain_failure(store, job | dict(fence=fence), workspace)
    assert (
        sum(p.stat().st_size for root in captured(store) for p in root.rglob("*") if p.is_file())
        <= 32768
    )


def test_diagnostic_projection_is_removed_with_document(setup):
    store, auth, job = setup
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    with pytest.raises(RuntimeError), analysis_workspace(store, job, directory) as workspace:
        seed(workspace)
        raise RuntimeError("never-copy-credential")
    assert captured(store)
    import time

    store.delete_document(auth, job["document_id"], "hf6-delete-fixture", now=time.time())
    assert not directory.exists()


def test_malformed_outcome_diagnostic_does_not_add_a_failure(setup):
    store, _, job = setup
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    with analysis_workspace(store, job, directory) as workspace:
        state = seed(workspace)
        (state / "outcome.json").write_text("{")
    assert len(captured(store)) == 1


def test_execute_analysis_retains_failed_child_workspace(setup, tmp_path, monkeypatch):
    from pathlib import Path

    from proofops_api import hosted_analysis

    store, _, job = setup
    prepared = tmp_path / "prepared.pdf"
    prepared.write_bytes(b"private-source")
    monkeypatch.setattr(hosted_analysis, "read_operator_config", lambda _: {})
    monkeypatch.setattr(
        hosted_analysis, "operator_profiles", lambda _: dict(source_reader="upstage")
    )

    def child(command, *_args, **_kwargs):
        state = seed(Path(command[-1]))
        write_child_failure(state, sqlite3.OperationalError("never-copy-credential"))
        raise HostedError("ANALYSIS_FAILED")

    monkeypatch.setattr(hosted_analysis, "run_analysis_process", child)
    with pytest.raises(HostedError, match="ANALYSIS_FAILED"):
        hosted_analysis.execute_analysis(store, job, prepared)
    (saved,) = captured(store)
    assert (saved / "state.sqlite3").exists() and (saved / "failure.json").exists()
    assert not list(saved.parent.parent.glob("analysis-work-*"))
    assert not (saved / "selected.pdf").exists()


def test_dispatch_diagnostic_retains_cause_without_exception_text(setup, tmp_path):
    import time
    from decimal import Decimal

    store, _, job = setup
    error = sqlite3.OperationalError("never-copy-credential")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY

    def fail(_):
        raise error

    with pytest.raises(sqlite3.OperationalError):
        store.dispatch(
            job,
            "openai",
            "call",
            "a" * 64,
            Decimal(".011"),
            fail,
            now=time.time(),
            diagnostic_context=dict(state=tmp_path, role="preliminary", request_bytes=12345),
        )
    raw = (tmp_path / "dispatch-failures/call.json").read_text()
    record = json.loads(raw)
    assert record["exception_type"] == "OperationalError"
    assert record["sqlite_errorcode"] == 5
    assert record["phase"] == "transport" and record["role"] == "preliminary"
    assert "never-copy-credential" not in raw
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT status FROM runs").fetchone()[0] == "accounting_pending"
        assert tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone()) == (
            None,
            "accounting_pending",
        )


@pytest.mark.parametrize("retain", [False, True])
def test_legacy_probe_without_response_role_preserves_uncertain_accounting(setup, tmp_path, retain):
    import ssl

    from proofops_api.hosted_analysis import HostedOpenAILunaProbe

    store, _, job = setup
    store.settings = replace(store.settings, retain_failed_analysis=retain)
    probe = HostedOpenAILunaProbe("offline-only", tmp_path / "legacy.db", store=store, job=job)
    assert not hasattr(probe, "response_role")
    calls = []

    def fail(body):
        calls.append(body)
        raise ssl.SSLEOFError("never-copy-credential")

    probe.post = fail
    with pytest.raises(HostedError, match="^PROCESSING_UNCERTAIN$"):
        probe._post(probe.request_body("Return JSON", "{}", request_id="legacy"))
    assert len(calls) == 1
    with store.transaction(readonly=True) as db:
        assert tuple(db.execute("SELECT actual,status FROM deletion.costs").fetchone()) == (
            None,
            "accounting_pending",
        )
        assert tuple(db.execute("SELECT status,fence FROM runs").fetchone()) == (
            "running",
            job["fence"],
        )
    records = list((tmp_path / "dispatch-failures").glob("*.json"))
    assert len(records) == int(retain)
    if retain:
        raw = records[0].read_text()
        record = json.loads(raw)
        assert record["role"] is None and record["phase"] == "transport"
        assert record["exception_type"] == "SSLEOFError"
        assert "never-copy-credential" not in raw
