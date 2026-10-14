"""P1: real SQLite contention and the hosted worker's exception boundary, offline."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from proofops_api.hosted_store import HostedStore

from scripts.hosted_control import worker_loop
from tests.test_hosted_public import actor, uploaded
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def test_poll_reads_do_not_reserve_the_writer(settings):
    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    writer = sqlite3.connect(store.path, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(store.get_document, auth.tenant_id, doc["document_id"])
            try:
                assert future.result(timeout=1)["document_id"] == doc["document_id"]
            finally:
                writer.rollback()
    finally:
        writer.close()


def test_backup_removal_does_not_hold_control_writer(settings, tmp_path, monkeypatch):
    store = HostedStore(settings)
    target = tmp_path / "expired-backup"
    target.mkdir()
    with store.transaction() as db:
        db.execute("INSERT INTO backups VALUES (?,?,?)", (str(target), 0, 1))
    entered, release = threading.Event(), threading.Event()
    import shutil

    original = shutil.rmtree

    def slow_remove(path, *args, **kwargs):
        if path == target:
            entered.set()
            assert release.wait(5)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", slow_remove)
    with ThreadPoolExecutor(2) as pool:
        maintenance = pool.submit(store.maintain, now=time.time())
        try:
            assert entered.wait(2)
            assert pool.submit(store.claim, now=time.time()).result(timeout=1) is None
        finally:
            release.set()
        maintenance.result(timeout=3)


def test_worker_survives_maintenance_and_future_failures(tmp_path):
    from types import SimpleNamespace

    stop = threading.Event()

    class Store:
        settings = SimpleNamespace(root=tmp_path, max_active_runs=1)
        calls = 0

        def maintain(self, **_):
            raise sqlite3.OperationalError("database is locked")

        def tick(self, **_):
            self.calls += 1
            if self.calls == 1:
                raise sqlite3.OperationalError("database is locked")
            if self.calls == 2:
                raise RuntimeError("private input must not be logged")
            stop.set()
            return None

    store = Store()
    worker_loop(store, stop=stop, interval=0.01)
    assert store.calls == 3


def test_read_transaction_rejects_writes(settings):
    store = HostedStore(settings)
    with store.transaction(readonly=True) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM runs")


def test_busy_commit_retries_without_reexecuting_body(settings, monkeypatch):
    from proofops_api import hosted_sqlite

    store = HostedStore(settings)
    reader = sqlite3.connect(store.ledger, isolation_level=None, check_same_thread=False)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM spend").fetchall()
    monkeypatch.setattr(hosted_sqlite, "LOCK_WAIT_SECONDS", 2)
    bodies = []
    entered = threading.Event()

    def writer():
        with store.transaction() as db:
            bodies.append(1)
            db.execute("INSERT INTO deletion.event_totals VALUES ('retry-proof',7)")
            entered.set()

    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(writer)
            try:
                assert entered.wait(1)
                # The reader owns a SHARED lock on the attached ledger. The
                # writer has executed its body and is now blocked at COMMIT.
                time.sleep(0.35)
                assert not future.done()
            finally:
                reader.rollback()
            future.result(timeout=2)
    finally:
        reader.close()
    assert bodies == [1]
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT amount FROM deletion.event_totals").fetchone()[0] == 7


def test_busy_retry_is_bounded_and_does_not_retry_other_errors(monkeypatch):
    from proofops_api import hosted_sqlite

    monkeypatch.setattr(hosted_sqlite, "LOCK_WAIT_SECONDS", 0.05)
    calls = []

    def busy():
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        hosted_sqlite.retry_busy(busy, phase="begin")
    assert 2 <= len(calls) <= 4
    calls.clear()

    def corrupt():
        calls.append(1)
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="I/O"):
        hosted_sqlite.retry_busy(corrupt, phase="commit")
    assert calls == [1]


def test_settlement_contention_keeps_one_dispatch_and_one_charge(settings):
    from decimal import Decimal

    from proofops_api.hosted_store import HostedError

    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], [1], "p1-settlement-key", now=time.time())
    job = store.claim(now=time.time())
    reader = sqlite3.connect(store.ledger, isolation_level=None, check_same_thread=False)
    dispatched = threading.Event()
    calls = []

    def transport(request):
        calls.append(request["request_id"])
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM costs").fetchall()
        dispatched.set()
        return request | dict(actual_usd="0.01")

    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(
                store.dispatch,
                job,
                "fake",
                "one-call",
                "a" * 64,
                Decimal("0.1"),
                transport,
                now=time.time(),
            )
            try:
                assert dispatched.wait(1)
                time.sleep(0.35)
                assert not future.done()
            finally:
                reader.rollback()
            future.result(timeout=2)
    finally:
        reader.close()
    with pytest.raises(HostedError, match="DISPATCH_ALREADY_RECORDED"):
        store.dispatch(
            job, "fake", "one-call", "a" * 64, Decimal("0.1"), transport, now=time.time()
        )
    assert len(calls) == 1
    with store.transaction(readonly=True) as db:
        rows = db.execute("SELECT actual,status FROM deletion.costs").fetchall()
        assert [tuple(row) for row in rows] == [(10000, "settled")]


def test_read_snapshot_waits_for_pending_commit(settings):
    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    reader = sqlite3.connect(store.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM hosted_schema").fetchall()
    written = threading.Event()

    def write():
        with store.transaction() as db:
            db.execute("UPDATE admission_control SET updated=1")
            written.set()

    try:
        with ThreadPoolExecutor(2) as pool:
            writer = pool.submit(write)
            assert written.wait(1)
            time.sleep(0.35)
            polling = pool.submit(store.get_document, auth.tenant_id, doc["document_id"])
            try:
                time.sleep(0.35)
            finally:
                reader.rollback()
            writer.result(timeout=2)
            assert polling.result(timeout=2)["document_id"] == doc["document_id"]
    finally:
        reader.close()


def test_publication_copy_releases_writer_and_rechecks_cancellation(
    settings, tmp_path, monkeypatch
):
    import json
    import shutil

    from proofops_api.hosted_store import HostedError

    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], [1], "p1-publication-key", now=time.time())
    job = store.claim(now=time.time())
    source = tmp_path / "publication"
    source.mkdir()
    (source / "outcome.json").write_text(
        json.dumps(
            dict(
                status="partial_blocked",
                reason="LIVE_BINDING_UNAVAILABLE",
                stages=[],
                provider_calls=0,
                scope={},
            )
        )
    )
    entered, release = threading.Event(), threading.Event()
    original = shutil.copytree

    def slow_copy(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", slow_copy)
    with ThreadPoolExecutor(2) as pool:
        publishing = pool.submit(store.publish_analysis, job, source, "partial_blocked", None)
        try:
            assert entered.wait(2)
            cancelled = pool.submit(store.cancel, auth, job["run_id"], now=time.time())
            assert cancelled.result(timeout=1)["status"] == "cancelled"
        finally:
            release.set()
        with pytest.raises(HostedError, match="LEASE_LOST"):
            publishing.result(timeout=2)
    with store.transaction(readonly=True) as db:
        assert db.execute("SELECT count(*) FROM result_snapshots").fetchone()[0] == 0
    assert not (store.document_dir(auth.tenant_id, doc["document_id"]) / "analysis").exists()


def test_health_distinguishes_stall_restart_and_observation_gap(settings):
    from proofops_api.hosted_worker_health import WorkerHeartbeat, worker_health

    store = HostedStore(settings)
    heartbeat = WorkerHeartbeat(settings.root)
    heartbeat.write(state="running")
    before = worker_health(settings.root)
    assert before["status"] == "running"
    assert worker_health(settings.root, now=time.time() + 31)["status"] == "stale"
    WorkerHeartbeat(settings.root).write(state="running")
    assert worker_health(settings.root, previous=before)["restart_detected"]
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], [1], "p1-health-run-key", now=time.time())
    store.claim(now=time.time() - 91)
    result = worker_health(settings.root)
    assert result["status"] == "degraded" and result["stalled_lease_heartbeats"] == 1
    (settings.root / "worker-heartbeat.json").write_text("broken")
    assert worker_health(settings.root)["observation"] == "unavailable"


def test_analysis_child_survives_transient_heartbeat_busy(settings, tmp_path, monkeypatch):
    import sys

    from proofops_api import hosted_analysis

    store = HostedStore(settings)
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], [1], "p1-child-busy-key", now=time.time())
    job = store.claim(now=time.time())
    monkeypatch.setattr(hosted_analysis, "HEARTBEAT_SECONDS", 0.05)
    original = store.renew_lease
    renewals = []

    def renew(job, *, now):
        renewals.append(now)
        if len(renewals) == 1:
            raise sqlite3.OperationalError("database is locked")
        original(job, now=now)

    monkeypatch.setattr(store, "renew_lease", renew)
    proof = tmp_path / "child-finished"
    command = [
        sys.executable,
        "-c",
        "import sys,time,pathlib; time.sleep(1.3); " "pathlib.Path(sys.argv[1]).write_text('once')",
        str(proof),
    ]
    with (tmp_path / "child.lock").open("a+b") as lock:
        hosted_analysis.run_analysis_process(command, store, job, lock)
    assert proof.read_text() == "once" and len(renewals) >= 2
    job["lease_until"] = time.time() - 1

    def always_busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "renew_lease", always_busy)
    with (tmp_path / "child.lock").open("a+b") as lock:
        with pytest.raises(ValueError, match="LEASE_LOST"):
            hosted_analysis.run_analysis_process(
                [sys.executable, "-c", "import time;time.sleep(10)"], store, job, lock
            )


def process_environment(settings):
    import os
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    return {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": ":".join(
            str(root / p)
            for p in ("packages", "apps/api/src", "apps/worker/src", "apps/agent/src", ".")
        ),
        "APP_ENV": "hosted",
        "MODEL_ADAPTER": "disabled",
        "LIVE_DISABLED": "true",
        "HOSTED_DATA_DIR": str(settings.root),
        "APP_ORIGIN": settings.origin,
        "HOSTED_SESSION_SECRET": settings.secret,
        "HOSTED_EVENT_ID": settings.event_id,
        "HOSTED_ACCEPT_UPLOADS": "true",
        "R108_ACCEPT_NEW_RUNS": "true",
        "ANALYSIS_BACKEND": "r108",
        "HOSTED_CONSENT_VERSION": settings.consent_version,
        "HOSTED_ACCESS_CONFIG": str(settings.root / "unused-access.json"),
    }


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("subprocess condition timed out")


def test_worker_startup_survives_reader_longer_than_busy_budget(settings, tmp_path):
    import subprocess
    import sys

    from proofops_api.hosted_worker_health import worker_health

    store = HostedStore(settings)
    env = process_environment(settings)
    reader_code = (
        "import sqlite3,sys,time; db=sqlite3.connect(sys.argv[1],isolation_level=None);"
        "db.execute('BEGIN'); db.execute('SELECT * FROM hosted_schema').fetchall();"
        "print('reader-ready',flush=True); sys.stdin.readline(); db.close()"
    )
    with (tmp_path / "worker.log").open("w+") as log:
        reader = subprocess.Popen(
            [sys.executable, "-c", reader_code, str(store.path)],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            env=env,
        )
        worker = None
        try:
            assert reader.stdout.readline().strip() == "reader-ready"
            worker = subprocess.Popen(
                [sys.executable, "scripts/hosted_control.py", "worker"],
                env=env,
                stdout=log,
                stderr=log,
            )
            initial = wait_until(lambda: worker_health(settings.root).get("worker_instance"))
            # Begin the hold window only after worker initialization has begun;
            # import speed must not shorten the contention below the 10s budget.
            time.sleep(11.3)
            reader.communicate("release\n", timeout=3)
            assert reader.returncode == 0
            result = wait_until(
                lambda: (
                    current
                    if (current := worker_health(settings.root))["status"] == "running"
                    else None
                )
            )
            assert worker.poll() is None
            assert result["worker_instance"] == initial
            assert result["database_busy"] >= 1
        finally:
            for process in (worker, reader):
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)
            reader.stdout.close()


def test_real_api_worker_and_observer_subprocess_contention(settings, tmp_path):
    import json
    import socket
    import subprocess
    import sys
    from pathlib import Path

    import httpx
    from proofops_api.hosted_worker_health import worker_health

    store = HostedStore(settings)
    auth = actor(store)
    sid = store.redeem(
        store.invite(auth.tenant_id, auth.user_sub, "admin", now=time.time()), now=time.time()
    )
    doc = uploaded(store, auth)
    accepted = store.create_run(auth, doc["document_id"], [1], "p1-subprocess-key", now=time.time())
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    env = process_environment(settings)
    api_code = (
        "import uvicorn; from proofops_api.hosted import create_hosted_app;"
        f"uvicorn.run(create_hosted_app(),host='127.0.0.1',port={port},access_log=False)"
    )
    # No model/API key enters any child. The worker executes hosted_prepare as
    # a real subprocess and publishes the honest LIVE_BINDING_UNAVAILABLE result.
    reader_code = (
        "import sqlite3,sys,time;db=sqlite3.connect(sys.argv[1],isolation_level=None);"
        "[(db.execute('BEGIN'),db.execute('SELECT * FROM runs').fetchall(),"
        "time.sleep(.35),db.rollback(),time.sleep(.05)) for _ in range(8)];db.close()"
    )
    maintain_code = (
        "import os,time;from proofops_api.hosted_store import HostedSettings,HostedStore;"
        "s=HostedStore(HostedSettings.from_env(os.environ));"
        "[(s.maintain(now=time.time()),time.sleep(.05)) for _ in range(8)]"
    )
    processes = []
    with (tmp_path / "processes.log").open("w+") as log:
        try:
            api = subprocess.Popen(
                [sys.executable, "-c", api_code], env=env, stdout=log, stderr=log
            )
            processes.append(api)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:

                def api_ready():
                    try:
                        return client.get("/v1/health/live").status_code == 200
                    except httpx.TransportError:
                        return False

                wait_until(api_ready)
                reader = subprocess.Popen(
                    [sys.executable, "-c", reader_code, str(store.path)],
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                processes.append(reader)
                worker = subprocess.Popen(
                    [sys.executable, "scripts/hosted_control.py", "worker"],
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                processes.append(worker)
                maintainer = subprocess.Popen(
                    [sys.executable, "-c", maintain_code],
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                processes.append(maintainer)
                initial = wait_until(lambda: worker_health(settings.root).get("worker_instance"))
                cookie = {"Cookie": f"__Host-proofops_session={sid}"}

                def poll(_):
                    return [
                        client.get(accepted["status_url"], headers=cookie).status_code
                        for _ in range(6)
                    ]

                with ThreadPoolExecutor(4) as pool:
                    statuses = [code for values in pool.map(poll, range(4)) for code in values]
                assert statuses == [200] * 24
                assert reader.wait(timeout=10) == 0
                assert maintainer.wait(timeout=10) == 0
                final = wait_until(
                    lambda: (
                        run
                        if (run := store.get_run(auth.tenant_id, accepted["run_id"]))["status"]
                        == "partial_blocked"
                        else None
                    )
                )
                result = client.get(final["result_url"], headers=cookie)
                assert result.status_code == 200
                assert result.json()["hold_reasons"] == ["LIVE_BINDING_UNAVAILABLE"]
                health = worker_health(settings.root)
                assert health["status"] == "running" and health["failures"] == 0
                assert health["worker_instance"] == initial
                assert api.poll() is None and worker.poll() is None
                with store.transaction(readonly=True) as db:
                    assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0
                    assert db.execute("SELECT fence FROM runs").fetchone()[0] == 1
                    assert db.execute("SELECT amount,status FROM deletion.spend").fetchone()[:] == (
                        0,
                        "settled",
                    )
                    assert db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete"
                    assert db.execute("PRAGMA deletion.journal_mode").fetchone()[0] == "delete"
                # Save optional benchmark evidence without changing the assertions.
                import os

                if destination := os.environ.get("P1_CONTENTION_RESULT"):
                    Path(destination).write_text(
                        json.dumps(
                            dict(
                                http_polls=len(statuses),
                                http_errors=0,
                                lock_errors=0,
                                worker_restarts=0,
                                provider_dispatches=0,
                                run_fence=1,
                                observer_read_transactions=8,
                                maintenance_sweeps=8,
                                real_processes=[
                                    "api",
                                    "worker",
                                    "observer",
                                    "maintainer",
                                    "prepare",
                                ],
                                worker_health=health,
                                result_status=final["status"],
                                result_hold_reasons=result.json()["hold_reasons"],
                            ),
                            indent=2,
                        )
                        + "\n"
                    )
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
        log.seek(0)
        assert "OperationalError" not in log.read()
