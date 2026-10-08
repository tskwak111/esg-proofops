"""P1 regression contracts: real HTTP/security/storage, no model transport."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from proofops_api.hosted import HostedSettings, HostedStore, create_hosted_app
from proofops_api.hosted_store import HostedError
from pypdf import PdfWriter

ORIGIN = "https://app.example.com"


@pytest.fixture
def settings(tmp_path):
    return HostedSettings(
        root=tmp_path / "private",
        origin=ORIGIN,
        secret="x" * 40,
        event_id="p1-test",
        accept_uploads=True,
        consent_version="proposal-test-v1",
        backend="r108",
        accept_runs=True,
    )


@pytest.fixture
def store(settings):
    return HostedStore(settings)


def pdf(pages=3):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def login(app, store, *, tenant=None, user=None, role="admin"):
    tenant, user = tenant or str(uuid4()), user or str(uuid4())
    code = store.invite(tenant, user, role, now=time.time())
    client = TestClient(app, base_url="https://api.example.com")
    response = client.post("/v1/auth/invitation", json={"code": code}, headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    csrf = response.json()["csrf_token"]
    return client, {"Origin": ORIGIN, "X-CSRF-Token": csrf}, tenant, user


def actor(store, *, tenant=None, user=None):
    from proofops.application.authorization import authorize

    code = store.invite(tenant or str(uuid4()), user or str(uuid4()), "admin", now=time.time())
    sid = store.redeem(code, now=time.time())
    return authorize(
        session_id=sid,
        now=time.time(),
        session_port=store.sessions,
        membership_port=store.memberships,
        required_capability="editor",
    )


def uploaded(store, auth):
    return store.upload(auth, pdf(), "upload-key-0000001", now=time.time())


def test_hosted_settings_fail_closed(tmp_path):
    env = {
        "APP_ENV": "hosted",
        "HOSTED_DATA_DIR": str(tmp_path),
        "APP_ORIGIN": ORIGIN,
        "HOSTED_SESSION_SECRET": "x" * 40,
        "HOSTED_EVENT_ID": "test",
    }
    s = HostedSettings.from_env(env)
    assert not s.accept_uploads and not s.accept_runs and s.live_disabled
    for change in (
        {"APP_ORIGIN": "https://*.vercel.app"},
        {"APP_ORIGIN": "http://app.test"},
        {"HOSTED_SESSION_SECRET": "short"},
        {"MODEL_ADAPTER": "synthetic"},
        {"LIVE_DISABLED": "false"},
        {"HOSTED_DATA_DIR": "relative"},
        {"R108_ACCEPT_NEW_RUNS": "maybe"},
    ):
        with pytest.raises(ValueError):
            HostedSettings.from_env(env | change)


def test_invitation_single_use_expiration_and_persistent_session(store, settings):
    app = create_hosted_app(settings)
    client, headers, tenant, _ = login(app, store)
    cookie = client.cookies.get("__Host-proofops_session")
    fresh = create_hosted_app(settings)
    with TestClient(fresh, base_url="https://api.example.com") as restarted:
        restarted.cookies.set("__Host-proofops_session", cookie)
        response = restarted.get("/v1/session")
        assert response.status_code == 200
        assert response.json()["tenant_id"] == tenant
        assert response.json()["csrf_token"] == headers["X-CSRF-Token"]
    code = store.invite(str(uuid4()), "u", "editor", now=1)
    with pytest.raises(HostedError):
        store.redeem(code, now=86402)
    code = store.invite(str(uuid4()), "u", "editor", now=time.time())
    with ThreadPoolExecutor(2) as pool:

        def attempt(_):
            try:
                return store.redeem(code, now=time.time())
            except HostedError:
                return None

        assert sum(result is not None for result in pool.map(attempt, range(2))) == 1


def test_cookie_origin_csrf_logout_and_cors(store, settings):
    app = create_hosted_app(settings)
    code = store.invite(str(uuid4()), "user", "admin", now=time.time())
    client = TestClient(app, base_url="https://api.example.com")
    assert client.post("/v1/auth/invitation", json={"code": code}).status_code == 403
    response = client.post("/v1/auth/invitation", json={"code": code}, headers={"Origin": ORIGIN})
    cookie = response.headers["set-cookie"]
    assert all(text in cookie.lower() for text in ("secure", "httponly", "samesite=lax", "path=/"))
    assert "domain=" not in cookie.lower()
    csrf = response.json()["csrf_token"]
    assert client.post("/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    assert (
        client.post(
            "/v1/auth/logout", headers={"Origin": "https://evil.test", "X-CSRF-Token": csrf}
        ).status_code
        == 403
    )
    for origin in (ORIGIN, "https://random.vercel.app"):
        response = client.options(
            "/v1/documents",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Idempotency-Key",
            },
        )
        assert (response.status_code == 200) == (origin == ORIGIN)
    assert (
        client.post("/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code
        == 204
    )
    assert client.get("/v1/session").status_code == 401


def test_real_upload_tenant_isolation_run_poll_and_purge(store, settings):
    app = create_hosted_app(settings)
    first, h, _, _ = login(app, store)
    second, h2, _, _ = login(app, store)
    response = first.post(
        "/v1/documents",
        content=pdf(),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "upload-http-key01"},
    )
    assert response.status_code == 201, response.text
    document = response.json()
    document_id = document["document_id"]
    assert document["page_count"] == 3
    assert second.get(f"/v1/documents/{document_id}").status_code == 404
    assert (
        second.post(
            "/v1/runs",
            json={"document_id": document_id},
            headers=h2 | {"Idempotency-Key": "run-cross-key001"},
        ).status_code
        == 404
    )
    response = first.post(
        "/v1/runs",
        json={"document_id": document_id},
        headers=h | {"Idempotency-Key": "run-http-key0001"},
    )
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["selected_pages"] == [1, 2]
    assert first.get(run["status_url"]).json()["status"] == "queued"
    job = store.claim(now=time.time())
    assert job["run_id"] == run["run_id"]
    prepared = store.prepare(job, now=time.time())
    from pypdf import PdfReader

    assert len(PdfReader(BytesIO(prepared.read_bytes())).pages) == 2
    assert store.tick(now=time.time()) is None  # active job already belongs to this claim
    response = first.post(
        f"/v1/documents/{document_id}/deletion-requests",
        json={"reason": "remove my upload"},
        headers=h | {"Idempotency-Key": "delete-http-key1"},
    )
    assert response.status_code == 202 and response.json()["status"] == "completed"
    assert first.get(run["status_url"]).status_code == 404
    assert not prepared.exists()
    with pytest.raises(HostedError):
        store.finish(job, "partial_blocked", now=time.time())


def test_flags_limits_and_upload_security(store, settings):
    app = create_hosted_app(settings)
    client, h, _, _ = login(app, store, role="viewer")
    assert (
        client.post(
            "/v1/documents",
            content=pdf(),
            headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "upload-http-key02"},
        ).status_code
        == 403
    )
    client, h, _, _ = login(app, store)
    request_headers = h | {
        "Content-Type": "application/pdf",
        "Idempotency-Key": "upload-http-key03",
    }
    assert (
        client.post("/v1/documents", content=b"not a pdf", headers=request_headers).status_code
        == 422
    )
    tiny = create_hosted_app(replace(settings, max_upload_bytes=50))
    tiny_client, tiny_h, _, _ = login(tiny, store)
    assert (
        tiny_client.post(
            "/v1/documents",
            content=pdf(),
            headers=tiny_h
            | {"Content-Type": "application/pdf", "Idempotency-Key": "upload-http-key04"},
        ).status_code
        == 413
    )
    closed = create_hosted_app(replace(settings, accept_uploads=False))
    closed_client, closed_h, _, _ = login(closed, store)
    assert (
        closed_client.post(
            "/v1/documents",
            content=pdf(),
            headers=closed_h
            | {"Content-Type": "application/pdf", "Idempotency-Key": "upload-http-key05"},
        ).status_code
        == 503
    )
    encrypted = PdfWriter()
    encrypted.add_blank_page(width=72, height=72)
    encrypted.encrypt("secret")
    b = BytesIO()
    encrypted.write(b)
    assert (
        client.post("/v1/documents", content=b.getvalue(), headers=request_headers).status_code
        == 422
    )


def test_selection_idempotency_and_no_get_dispatch(store):
    auth = actor(store)
    document = uploaded(store, auth)
    for pages in ([1, 2, 3], [0], [4], [1, 1], [True], []):
        with pytest.raises(HostedError):
            store.create_run(
                auth, document["document_id"], pages, "run-pages-key010", now=time.time()
            )
    first = store.create_run(
        auth, document["document_id"], [2, 3], "run-repeat-key10", now=time.time()
    )
    assert (
        store.create_run(auth, document["document_id"], [2, 3], "run-repeat-key10", now=time.time())
        == first
    )
    with pytest.raises(HostedError):
        store.create_run(auth, document["document_id"], [1], "run-repeat-key10", now=time.time())
    for _ in range(3):
        assert store.get_run(auth.tenant_id, first["run_id"])["status"] == "queued"


def test_queue_and_global_budget_races(store):
    actors = [actor(store) for _ in range(12)]
    documents = [uploaded(store, auth) for auth in actors]

    def enqueue(index):
        try:
            return store.create_run(
                actors[index],
                documents[index]["document_id"],
                None,
                f"queue-request-{index:04}",
                now=time.time(),
            )
        except HostedError as exc:
            assert exc.status == 429
            return None

    with ThreadPoolExecutor(12) as pool:
        results = list(pool.map(enqueue, range(12)))
    assert sum(result is not None for result in results) == 8
    with ThreadPoolExecutor(3) as pool:
        claims = list(pool.map(lambda _: store.claim(now=time.time()), range(3)))
    assert sum(job is not None for job in claims) == 1
    assert store.budget_totals()["event_reserved_usd"] == "4.000000"


def test_nested_reservation_unknown_cost_and_fence(store):
    auth = actor(store)
    document = uploaded(store, auth)
    store.create_run(auth, document["document_id"], None, "dispatch-run-001", now=time.time())
    job = store.claim(now=time.time())
    called = []

    def timeout(request):
        called.append(request)
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        store.dispatch(job, "fake", "call-001", "a" * 64, Decimal("0.2"), timeout, now=time.time())
    with pytest.raises(HostedError):
        store.dispatch(job, "fake", "call-001", "a" * 64, Decimal("0.2"), timeout, now=time.time())
    assert len(called) == 1
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"
    assert store.get_run(auth.tenant_id, job["run_id"])["status"] == "accounting_pending"
    assert store.claim(now=time.time() + 1000) is None


def test_broker_receipt_matching_and_daily_event_caps(store, settings):
    limited = HostedStore(replace(settings, event_usd=Decimal("0.5")))
    auth = actor(limited)
    doc = uploaded(limited, auth)
    run = limited.create_run(auth, doc["document_id"], None, "cost-run-key0010", now=time.time())
    job = limited.claim(now=time.time())

    def response(request):
        return request | {"actual_usd": "0.100000"}

    limited.dispatch(job, "fake", "call-ok", "b" * 64, Decimal("0.2"), response, now=time.time())
    with pytest.raises(HostedError):
        limited.dispatch(
            job, "fake", "call-over", "b" * 64, Decimal("0.41"), response, now=time.time()
        )
    limited.finish(job, "partial_blocked", now=time.time())
    assert limited.budget_totals()["event_reserved_usd"] == "0.100000"
    other = actor(limited)
    other_doc = uploaded(limited, other)
    with pytest.raises(HostedError, match="BUDGET_EXCEEDED"):
        limited.create_run(
            other, other_doc["document_id"], None, "cost-run-key0020", now=time.time()
        )
    assert limited.get_run(auth.tenant_id, run["run_id"])["status"] == "partial_blocked"


def test_purge_backup_restore_tombstone_and_expiration(store, tmp_path):
    auth = actor(store)
    doc = uploaded(store, auth)
    path = store.document_dir(auth.tenant_id, doc["document_id"])
    (path / "receipt").mkdir()
    (path / "receipt" / "r.json").write_text('{"quote":"secret source quote"}')
    backup = store.backup(tmp_path / "backup", now=time.time())
    assert not list(backup.rglob("*.pdf"))
    assert list(backup.rglob("r.json"))
    store.delete_document(auth, doc["document_id"], "purge-request010", now=time.time())
    assert not path.exists()
    assert not list(backup.rglob("r.json"))
    store.restore(backup, now=time.time())
    with pytest.raises(HostedError):
        store.get_document(auth.tenant_id, doc["document_id"])
    doc2 = store.upload(auth, pdf(), "upload-expire001", now=time.time())
    store.maintain(now=time.time() + 8 * 86400)
    assert not store.document_dir(auth.tenant_id, doc2["document_id"]).exists()
    store.maintain(now=time.time() + 15 * 86400)
    assert not backup.exists()


def test_schema_guard_no_raw_tokens_or_source_in_database(store, settings):
    code = store.invite(str(uuid4()), "user", "admin", now=time.time())
    sid = store.redeem(code, now=time.time())
    data = (settings.root / "control.sqlite3").read_bytes()
    assert code.encode() not in data and sid.encode() not in data
    with sqlite3.connect(settings.root / "control.sqlite3") as db:
        db.execute("UPDATE hosted_schema SET version=99")
    with pytest.raises(ValueError, match="schema"):
        HostedStore(settings)


def test_main_dispatches_hosted_without_local_bypass(monkeypatch, settings):
    monkeypatch.setenv("APP_ENV", "hosted")
    monkeypatch.setenv("APP_ORIGIN", settings.origin)
    monkeypatch.setenv("HOSTED_DATA_DIR", str(settings.root))
    monkeypatch.setenv("HOSTED_SESSION_SECRET", settings.secret)
    monkeypatch.setenv("HOSTED_EVENT_ID", settings.event_id)
    monkeypatch.setenv("MODEL_ADAPTER", "disabled")
    from proofops_api.main import create_app

    app = create_app()
    assert app.state.composition.app_env == "hosted"
    assert not any(route.path.startswith("/local/") for route in app.routes)


def test_chunked_body_limit_and_durable_user_rate(store, settings):
    app = create_hosted_app(replace(settings, max_upload_bytes=100))
    client, h, _, _ = login(app, store)

    def chunks():
        yield b"%PDF-1.3\n" + b"x" * 40
        yield b"x" * 100

    response = client.post(
        "/v1/documents",
        content=chunks(),
        headers=h | {"Content-Type": "application/pdf", "Idempotency-Key": "chunked-upload-001"},
    )
    assert response.status_code == 413
    for index in range(10):
        store.consume("one-subject", 10, 100 + index)
    restarted = HostedStore(settings)
    with pytest.raises(HostedError, match="RATE_LIMITED"):
        restarted.consume("one-subject", 10, 110)


def test_rotation_membership_revocation_and_idle_expiry(store, settings):
    app = create_hosted_app(settings)
    client, h, tenant, user = login(app, store)
    old = client.cookies.get("__Host-proofops_session")
    response = client.post("/v1/session/tenant", json={"tenant_id": tenant}, headers=h)
    assert response.status_code == 200
    assert client.cookies.get("__Host-proofops_session") != old
    assert response.json()["csrf_token"] != h["X-CSRF-Token"]
    with store.transaction() as db:
        db.execute(
            "UPDATE memberships SET status='revoked' WHERE tenant_id=? AND user_id=?",
            (tenant, user),
        )
    assert client.get("/v1/session").status_code == 404
    code = store.invite(str(uuid4()), "idle-user", "admin", now=100)
    sid = store.redeem(code, now=100)
    from proofops.application.authorization import SessionExpiredError, get_live_session

    with pytest.raises(SessionExpiredError):
        get_live_session(session_id=sid, now=1900, session_port=store.sessions)


def test_late_dispatch_settlement_after_delete_keeps_money(store):
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "late-dispatch-key01", now=time.time())
    job = store.claim(now=time.time())

    def response(request):
        store.delete_document(auth, doc["document_id"], "delete-inflight-01", now=time.time())
        return request | {"actual_usd": "0.100000"}

    store.dispatch(job, "fake", "late-call", "c" * 64, Decimal("0.2"), response, now=time.time())
    assert store.budget_totals()["event_reserved_usd"] == "0.100000"
    assert not store.document_dir(auth.tenant_id, doc["document_id"]).exists()


def test_unknown_dispatch_deletion_does_not_unblock_other_work(store):
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "unknown-dispatch01", now=time.time())
    job = store.claim(now=time.time())

    def bad_receipt(request):
        return request | {"request_id": "wrong-id", "actual_usd": "0.100000"}

    with pytest.raises(HostedError, match="RECEIPT_MISMATCH"):
        store.dispatch(
            job, "fake", "wrong-call", "d" * 64, Decimal("0.2"), bad_receipt, now=time.time()
        )
    store.delete_document(auth, doc["document_id"], "delete-unknown-01", now=time.time())
    other = actor(store)
    other_doc = uploaded(store, other)
    with pytest.raises(HostedError, match="ACCOUNTING_PENDING"):
        store.create_run(
            other, other_doc["document_id"], None, "unknown-newrun-01", now=time.time()
        )
    assert store.budget_totals()["event_reserved_usd"] == "0.500000"


def test_backup_lifetime_is_bounded_from_document_creation(store, tmp_path):
    auth = actor(store)
    created = time.time() - 6 * 86400
    store.upload(auth, pdf(), "backup-aged-key01", now=created)
    backup = store.backup(tmp_path / "aged-backup", now=time.time())
    manifest = json.loads((backup / "manifest.json").read_text())
    assert manifest["expires"] <= created + 14 * 86400
    store.maintain(now=created + 14 * 86400 + 1)
    assert not backup.exists()


def test_original_expiry_and_safe_restore_require_reupload(store, tmp_path):
    auth = actor(store)
    doc = uploaded(store, auth)
    backup = store.backup(tmp_path / "source-free", now=time.time())
    store.document_dir(auth.tenant_id, doc["document_id"]).joinpath("original.pdf").unlink()
    store.restore(backup, now=time.time())
    with pytest.raises(HostedError, match="SOURCE_UNAVAILABLE"):
        store.create_run(auth, doc["document_id"], None, "missing-source-01", now=time.time())


def test_purge_failure_remains_blocked_and_retry_recovers(store, monkeypatch):
    auth = actor(store)
    doc = uploaded(store, auth)
    import shutil

    actual = shutil.rmtree

    def unavailable(path, *args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(shutil, "rmtree", unavailable)
    result = store.delete_document(auth, doc["document_id"], "failed-purge-key1", now=time.time())
    assert result["status"] == "failed"
    with pytest.raises(HostedError):
        store.get_document(auth.tenant_id, doc["document_id"])
    monkeypatch.setattr(shutil, "rmtree", actual)
    result = store.delete_document(auth, doc["document_id"], "failed-purge-key1", now=time.time())
    assert result["status"] == "completed"


def test_audit_expiry_preserves_aggregate_event_cost(store):
    auth = actor(store)
    doc = uploaded(store, auth)
    store.create_run(auth, doc["document_id"], None, "audit-expiry-key01", now=time.time())
    job = store.claim(now=time.time())
    store.dispatch(
        job,
        "fake",
        "audit-call",
        "e" * 64,
        Decimal("0.2"),
        lambda r: r | {"actual_usd": "0.100000"},
        now=time.time(),
    )
    store.finish(job, "partial_blocked", now=time.time())
    store.delete_document(auth, doc["document_id"], "audit-delete-key1", now=time.time())
    store.maintain(now=time.time() + 31 * 86400)
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM deletion.spend").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM deletion.tombstones").fetchone()[0] == 0
    assert store.budget_totals()["event_reserved_usd"] == "0.100000"


def test_normal_writer_cannot_remove_or_replace_tombstone(store):
    auth = actor(store)
    doc = uploaded(store, auth)
    store.delete_document(auth, doc["document_id"], "immutable-delete01", now=time.time())
    for sql in ("DELETE FROM deletion.tombstones", "UPDATE deletion.tombstones SET created=0"):
        with pytest.raises(sqlite3.DatabaseError):
            with store.transaction() as db:
                db.execute(sql)


def test_api_twenty_sessions_poll_without_dispatch(store, settings):
    app = create_hosted_app(settings)
    # Two users per invitation throttle window via trusted operator-established sessions.
    clients = []
    for _ in range(20):
        auth = actor(store)
        client = TestClient(app, base_url="https://api.example.com")
        client.cookies.set("__Host-proofops_session", auth.session_id)
        clients.append(client)
    with ThreadPoolExecutor(20) as pool:
        responses = list(pool.map(lambda c: c.get("/v1/session"), clients))
    assert all(r.status_code == 200 for r in responses)
    assert store.budget_totals()["event_reserved_usd"] == "0.000000"


def test_control_restore_cannot_reset_money_and_foreign_ledger_rejected(store, settings, tmp_path):
    auth = actor(store)
    doc = uploaded(store, auth)
    backup = store.backup(tmp_path / "money-backup", now=time.time())
    store.create_run(auth, doc["document_id"], None, "restore-cost-key01", now=time.time())
    job = store.claim(now=time.time())
    store.dispatch(
        job,
        "fake",
        "restore-call",
        "f" * 64,
        Decimal("0.2"),
        lambda r: r | {"actual_usd": "0.100000"},
        now=time.time(),
    )
    store.finish(job, "partial_blocked", now=time.time())
    # Simulate loss of application state, while independent deletion/money ledger survives.
    with store.transaction() as db:
        db.execute("DELETE FROM runs")
    store.restore(backup, now=time.time())
    assert store.budget_totals()["event_reserved_usd"] == "0.100000"
    fresh = HostedStore(replace(settings, root=tmp_path / "foreign"))
    with pytest.raises(HostedError, match="LEDGER_RECOVERY_REQUIRED"):
        fresh.restore(backup, now=time.time())
