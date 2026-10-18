"""HS2 unattended blockers: offline regressions, never provider calls."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from proofops_api.hosted_store import HostedError

from tests.test_hosted_public import actor, pdf
from tests.test_hosted_scope import settings as _settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


@pytest.fixture
def store(settings):
    from proofops_api.hosted_store import HostedStore

    return HostedStore(settings)


def test_proxy_precedes_spa_and_configure_web_accepts_checkout():
    rewrites = json.loads((ROOT / "vercel.json").read_text())["rewrites"]
    assert rewrites[0]["source"] == "/hosted-api/:path*"
    result = subprocess.run(
        [
            sys.executable,
            "deploy/lightsail/configure-web.py",
            "--checkout",
            str(ROOT),
            "--static-ip",
            "8.8.8.8",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "https://8.8.8.8.sslip.io/:path*" in result.stdout


def test_failed_scope_manual_selection_preserves_unreadable_and_caps(store):
    auth = actor(store)
    doc = store.upload(auth, pdf(32), "hs2-manual-upload", now=time.time())
    original = store.generate_scope(auth, doc["document_id"])
    assert original["plan"]["status"] == "failed"
    changed = store.edit_scope(
        auth,
        doc["document_id"],
        [1, 2],
        [1, 2, 3],
        '"1"',
        reporting_scope=dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
    )
    assert changed["revision"] == 2
    assert changed["plan"] == original["plan"] | dict(
        selected_claim_pages=[1, 2], selected_evidence_pages=[1, 2, 3]
    )
    assert changed["selection"]["manual_override"] is True
    assert store.get_scope(auth.tenant_id, doc["document_id"]) == changed
    for claims, evidence in [
        ([True], [1]),
        (list(range(1, 12)), list(range(1, 12))),
        ([1], list(range(1, 32))),
        ([2], [1]),
        ([33], [33]),
    ]:
        with pytest.raises(HostedError, match="PAGE_SELECTION_INVALID"):
            store.edit_scope(auth, doc["document_id"], claims, evidence, '"2"')
    with pytest.raises(HostedError, match="SCOPE_CONFLICT"):
        store.edit_scope(auth, doc["document_id"], [1], [1], '"1"')
    run = store.create_run(
        auth,
        doc["document_id"],
        None,
        "hs2-manual-run001",
        now=time.time(),
        auto_scope=True,
        scope_selection_sha256=changed["selection"]["selection_sha256"],
    )
    assert run["claim_pages"] == [1, 2]
    assert run["selected_pages"] == [1, 2, 3]


def queued(store, key):
    auth = actor(store)
    doc = store.upload(auth, pdf(), key + "-upload-0001", now=time.time())
    return store.create_run(auth, doc["document_id"], [1], key + "-run-0001", now=time.time())


def test_disabled_live_publishes_real_blocked_snapshot(store):
    run = queued(store, "hs2-offline")
    done = store.tick(now=time.time())
    assert done["run_id"] == run["run_id"]
    assert done["status"] == "partial_blocked"
    assert done["result_url"]
    assert done["result"]["claims"] == []
    assert done["result"]["pipeline"]["status"] == "partial_blocked"
    assert done["result"]["hold_reasons"] == ["LIVE_BINDING_UNAVAILABLE"]


def test_expired_zero_dispatch_run_releases_queue_and_fences_old_worker(store):
    first = queued(store, "hs2-expired")
    next_run = queued(store, "hs2-next")
    job = store.claim(now=time.time())
    with store.transaction() as db:
        db.execute("UPDATE runs SET lease_until=0 WHERE run_id=?", (first["run_id"],))
    next_job = store.claim(now=time.time())
    assert next_job and next_job["run_id"] == next_run["run_id"]
    assert store.get_run(job["tenant_id"], job["run_id"])["status"] == "failed"
    with store.transaction() as db:
        row = db.execute(
            "SELECT amount,status FROM deletion.spend WHERE run_id=?", (job["run_id"],)
        ).fetchone()
        assert tuple(row) == (0, "settled")
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.update_progress(job, "parse", 15)


def test_lease_covers_measured_time_and_heartbeat_extends_it(store):
    queued(store, "hs2-heartbeat")
    before = time.time()
    job = store.claim(now=before)
    assert job["lease_until"] >= before + 1900
    store.renew_lease(job, now=before + 605)
    with store.transaction() as db:
        row = store._fenced(db, job, before + 1901)
        # HF4 adds only the measured writer wait to the renewal; it must never be shorter.
        assert before + 605 + 1900 <= row["lease_until"] < before + 605 + 1900 + 1


def test_scope_openapi_declares_cas():
    spec = json.loads((ROOT / "deploy/public/openapi.json").read_text())
    op = spec["paths"]["/v1/documents/{document_id}/scope-plan/selection"]["post"]
    assert any(
        p["name"] == "If-Match" and p["in"] == "header" and p["required"] for p in op["parameters"]
    )
    assert {"412", "428"} <= op["responses"].keys()


@pytest.mark.parametrize("successful_batches", [0, 1])
def test_parse_budget_denial_publishes_partial_instead_of_worker_failure(
    store, monkeypatch, successful_batches
):
    import os
    import socket
    from io import BytesIO

    from proofops.application.budget import BudgetExceeded
    from proofops_api.hosted_analysis import HostedParseProbe
    from pypdf import PdfReader, PdfWriter

    from tests.test_hosted_analysis import fake_analysis, source_pdf

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))

    post = HostedParseProbe._post_parse
    calls = []

    def denied(*args, **kwargs):
        if len(calls) >= successful_batches:
            raise BudgetExceeded("BUDGET_EXHAUSTED")
        calls.append(True)
        return post(*args, **kwargs)

    monkeypatch.setattr(HostedParseProbe, "_post_parse", denied)
    auth = actor(store)
    writer, buffer = PdfWriter(), BytesIO()
    source = PdfReader(BytesIO(source_pdf()))
    for page in [source.pages[0]] * 5:
        writer.add_page(page)
    writer.write(buffer)
    doc = store.upload(auth, buffer.getvalue(), "hs2-budget-upload001", now=time.time())
    store.create_run(
        auth,
        doc["document_id"],
        [1, 2, 3, 4, 5],
        "hs2-budget-run001",
        now=time.time(),
        auto_scope=True,
    )
    done = store.tick(now=time.time(), analysis=fake_analysis)
    assert done["status"] == "partial_blocked", done
    assert done["result"]["hold_reasons"] == ["BUDGET_EXHAUSTED"]
    assert done["result"]["pipeline"]["stages"] == [
        dict(stage="parse", outcome="budget_unanalyzed")
    ]
    assert done["result"]["claims"] == []
    with store.transaction() as db:
        settled = db.execute(
            "SELECT count(*) FROM deletion.costs WHERE status='settled'"
        ).fetchone()[0]
        assert settled == successful_batches


def test_analysis_lock_short_contention_retries_then_times_out(tmp_path, monkeypatch):
    import fcntl
    import threading

    from proofops_api import hosted_analysis

    path = tmp_path / "analysis.lock"
    with path.open("a+b") as owner, path.open("a+b") as contender:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        timer = threading.Timer(0.1, lambda: fcntl.flock(owner, fcntl.LOCK_UN))
        timer.start()
        try:
            hosted_analysis.acquire_analysis_lock(contender, timeout=1)
        finally:
            timer.join()
    with path.open("a+b") as owner, path.open("a+b") as contender:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(HostedError, match="ANALYSIS_LOCK_BUSY"):
            hosted_analysis.acquire_analysis_lock(contender, timeout=0.01)


def test_process_wait_renews_lease_and_preserves_total_timeout(store, tmp_path, monkeypatch):
    from proofops_api import hosted_analysis

    queued(store, "hs2-process-heartbeat")
    job = store.claim(now=time.time())
    monkeypatch.setattr(hosted_analysis, "HEARTBEAT_SECONDS", 0.05)
    renewals = []
    original = store.renew_lease

    def renew(job, *, now):
        renewals.append(now)
        original(job, now=now)

    monkeypatch.setattr(store, "renew_lease", renew)
    with (tmp_path / "lock").open("a+b") as lock:
        hosted_analysis.run_analysis_process(
            [sys.executable, "-c", "import time;time.sleep(.15)"], store, job, lock
        )
        assert len(renewals) >= 2
        monkeypatch.setattr(hosted_analysis, "ANALYSIS_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(subprocess.TimeoutExpired):
            hosted_analysis.run_analysis_process(
                [sys.executable, "-c", "import time;time.sleep(10)"], store, job, lock
            )


def test_heartbeat_keeps_1900_second_lease_valid_through_2700_seconds(store):
    from proofops_api.hosted_analysis import HEARTBEAT_SECONDS
    from proofops_api.hosted_store import RUN_LEASE_SECONDS

    queued(store, "hf2-2700-second-run")
    start = time.time()
    job = store.claim(now=start)
    assert RUN_LEASE_SECONDS == 1900
    assert HEARTBEAT_SECONDS == 30
    for elapsed in range(HEARTBEAT_SECONDS, 2701, HEARTBEAT_SECONDS):
        store.renew_lease(job, now=start + elapsed)
        expected = start + elapsed + RUN_LEASE_SECONDS
        assert expected <= job["lease_until"] < expected + 1  # plus measured writer wait
    with store.transaction() as db:
        assert store._fenced(db, job, start + 2700)["status"] == "running"
    with pytest.raises(HostedError, match="LEASE_LOST"):
        store.renew_lease(job, now=job["lease_until"])


@pytest.mark.parametrize("already_settled", [False, True])
def test_operator_reconciliation_requires_exact_export_and_preserves_unknown(
    store, tmp_path, already_settled
):
    from decimal import Decimal

    from scripts.hosted_control import reconcile

    queued(store, "hs2-reconcile")
    job = store.claim(now=time.time())

    def unknown(request):
        raise TimeoutError("fake unknown")

    if already_settled:
        store.dispatch(
            job,
            "fake",
            "call-hs2",
            "a" * 64,
            Decimal("0.1"),
            lambda request: request | dict(actual_usd="0.02"),
            now=time.time(),
        )
        with store.transaction() as db:
            db.execute("UPDATE runs SET lease_until=0 WHERE run_id=?", (job["run_id"],))
        assert store.claim(now=time.time()) is None
    else:
        with pytest.raises(TimeoutError):
            store.dispatch(
                job, "fake", "call-hs2", "a" * 64, Decimal("0.1"), unknown, now=time.time()
            )
    with store.transaction() as db:
        call = dict(
            db.execute("SELECT * FROM deletion.costs WHERE run_id=?", (job["run_id"],)).fetchone()
        )
    evidence = tmp_path / "provider-export.json"
    evidence.write_text('{"offline_fixture":true,"actual_usd":"0.02"}')
    from proofops_api.hosted_store import digest

    receipt = dict(
        run_id=job["run_id"],
        operator="offline-test",
        reason="Provider export matched",
        provider_evidence_sha256=digest(evidence.read_bytes()),
        calls=[
            {k: call[k] for k in ("call_id", "request_id", "provider", "input_sha256")}
            | dict(actual_usd="0.02")
        ],
    )
    assert reconcile(store, receipt, evidence, apply=False)["calls"] == 1
    assert store.claim(now=time.time()) is None
    with pytest.raises(ValueError):
        reconcile(store, receipt | dict(provider_evidence_sha256="0" * 64), evidence, apply=True)
    for field, value in (("request_id", "wrong-request"), ("actual_usd", "0.11")):
        bad = receipt | dict(calls=[receipt["calls"][0] | {field: value}])
        with pytest.raises(ValueError):
            reconcile(store, bad, evidence, apply=True)
    if already_settled:
        with pytest.raises(ValueError, match="SETTLED_COST_MISMATCH"):
            reconcile(
                store,
                receipt | dict(calls=[receipt["calls"][0] | dict(actual_usd="0.03")]),
                evidence,
                apply=True,
            )
    assert store.claim(now=time.time()) is None
    reconcile(store, receipt, evidence, apply=True)
    assert store.budget_totals()["event_reserved_usd"] == "0.020000"
    assert store.get_run(job["tenant_id"], job["run_id"])["status"] == "failed"
    assert list(store.settings.root.glob("payloads/*/*/receipt/settlement-*.json"))


def test_deploy_accepts_dec22_and_explicit_live_opt_in(tmp_path):
    runtime = tmp_path / "runtime.env"
    init = subprocess.run(
        [
            sys.executable,
            "deploy/lightsail/init-runtime.py",
            "--origin",
            "https://app.example.com",
            "--output",
            str(runtime),
        ],
        cwd=ROOT,
        capture_output=True,
    )
    assert init.returncode == 0
    env = runtime.read_text()
    assert "HOSTED_RUN_USD=1.0" in env and "HOSTED_DAY_USD=7" in env
    assert "HOSTED_EVENT_USD=7" in env and "LIVE_DISABLED=true" in env
    config = tmp_path / "live.json"
    for key in ("openai", "openrouter", "upstage"):
        (tmp_path / f"{key}.key").write_text("offline-test-only")
    config.write_text(
        json.dumps(
            dict(
                enabled=True,
                openai_key_file=str(tmp_path / "openai.key"),
                openrouter_key_file=str(tmp_path / "openrouter.key"),
                upstage_key_file=str(tmp_path / "upstage.key"),
                report_year=2025,
                period_start="2024-01-01",
                period_end="2024-12-31",
            )
        )
    )
    runtime.write_text(
        env.replace("LIVE_DISABLED=true", "LIVE_DISABLED=false")
        .replace("ANALYSIS_BACKEND=static", "ANALYSIS_BACKEND=r108")
        .replace("HOSTED_LIVE_CONFIG=/run/private/live.json", f"HOSTED_LIVE_CONFIG={config}")
    )
    result = subprocess.run(
        [sys.executable, "deploy/lightsail/check-config.py", str(runtime)],
        cwd=ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
