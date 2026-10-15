"""Reusable password security regressions; all credentials are disposable fixtures."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from proofops.application.authorization import authorize
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import HostedError, HostedStore

from tests.test_hosted_public import ORIGIN, actor, pdf
from tests.test_hosted_public import settings as hosted_settings

settings = hosted_settings


@pytest.fixture
def configured(settings):
    store = HostedStore(replace(settings, access_config=settings.root / "access.json"))
    tenant = str(uuid4())
    for role in ("admin", "organizer"):
        store.access.set_password(
            role,
            role + "-fixture-only-password",
            tenant=tenant,
            expires=time.time() + 86400,
            now=time.time(),
        )
    return store, tenant


def access_actor(store, role, *, now=None, ip="fixture-ip"):
    now = time.time() if now is None else now
    sid = store.access.login(role, role + "-fixture-only-password", ip=ip, now=now)
    return authorize(
        session_id=sid,
        now=now,
        session_port=store.sessions,
        membership_port=store.memberships,
        required_capability="editor",
    )


def test_reusable_hash_only_permissions_and_session_bounds(configured):
    store, _ = configured
    first = access_actor(store, "organizer")
    second = access_actor(store, "organizer")
    assert first.user_sub == second.user_sub and first.session_id != second.session_id
    record = store.sessions.get(first.session_id)
    assert record.expires_at - time.time() <= 28800
    assert record.idle_deadline - time.time() <= 1800
    assert not first.has_capability("admin") and not first.has_capability("reviewer")
    assert access_actor(store, "admin").has_capability("admin")
    path = store.settings.access_config
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert "fixture-only-password" not in path.read_text()


def test_expiration_disable_and_rotation(configured):
    store, tenant = configured
    original = access_actor(store, "organizer")
    store.access.set_password(
        "organizer",
        "new-fixture-only-password",
        tenant=tenant,
        expires=time.time() + 400,
        now=time.time(),
        revoke_sessions=False,
    )
    assert not store.sessions.get(original.session_id).revoked
    store.access.set_password(
        "organizer",
        "next-fixture-only-password",
        tenant=tenant,
        expires=time.time() + 400,
        now=time.time(),
        revoke_sessions=True,
    )
    assert store.sessions.get(original.session_id).revoked
    sid = store.access.login("organizer", "next-fixture-only-password", ip="other", now=time.time())
    store.access.disable("organizer", now=time.time())
    assert store.sessions.get(sid).revoked
    with pytest.raises(HostedError, match="ACCESS_PASSWORD_INVALID"):
        store.access.login("organizer", "next-fixture-only-password", ip="other", now=time.time())
    store.access.set_password(
        "organizer",
        "last-fixture-only-password",
        tenant=tenant,
        expires=time.time() - 1,
        now=time.time(),
    )
    with pytest.raises(HostedError, match="ACCESS_PASSWORD_INVALID"):
        store.access.login("organizer", "last-fixture-only-password", ip="other", now=time.time())


def test_persistent_ip_and_account_lock_sliding_window(configured):
    store, _ = configured
    now = time.time()
    for i in range(5):
        with pytest.raises(HostedError) as failure:
            store.access.login("organizer", "wrong-fixture-password", ip="attacker", now=now + i)
        assert failure.value.code == (
            "ACCESS_PASSWORD_LOCKED" if i == 4 else "ACCESS_PASSWORD_INVALID"
        )
    restarted = HostedStore(store.settings)
    for role, ip in (("organizer", "new-ip"), ("admin", "attacker")):
        with pytest.raises(HostedError, match="ACCESS_PASSWORD_LOCKED"):
            access_actor(restarted, role, now=now + 60, ip=ip)
    assert access_actor(restarted, "organizer", now=now + 905)
    with store.transaction() as db:
        audit = [dict(r) for r in db.execute("SELECT * FROM access_auth_audit")]
    serialized = json.dumps(audit)
    assert "fixture-password" not in serialized and "attacker" not in serialized


def test_concurrent_failures_cannot_bypass_lock(configured):
    store, _ = configured

    def fail(_):
        try:
            store.access.login("admin", "wrong-fixture-password", ip="parallel", now=time.time())
        except HostedError as exc:
            return exc.code

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(fail, range(8)))
    assert outcomes.count("ACCESS_PASSWORD_INVALID") == 4
    assert outcomes.count("ACCESS_PASSWORD_LOCKED") == 4


def test_http_origin_csrf_cookie_validation_and_idle(configured):
    store, _ = configured
    app = create_hosted_app(store.settings)
    client = TestClient(app, base_url="https://api.example.com")
    body = {"role": "organizer", "password": "organizer-fixture-only-password"}
    for origin in (None, "https://preview.vercel.app"):
        assert (
            client.post(
                "/v1/auth/access-password", json=body, headers={"Origin": origin} if origin else {}
            ).status_code
            == 403
        )
    response = client.post("/v1/auth/access-password", json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 200 and response.json()["role"] == "organizer"
    cookie = response.headers["set-cookie"].lower()
    assert all(x in cookie for x in ("secure", "httponly", "samesite=lax", "path=/"))
    assert client.post("/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
    bad = body | {"password": "private-invalid-fixture" * 20}
    response = client.post("/v1/auth/access-password", json=bad, headers={"Origin": ORIGIN})
    assert response.status_code == 422 and "private-invalid" not in response.text
    with store.transaction() as db:
        db.execute("UPDATE sessions SET idle=?", (time.time() - 1,))
    assert client.get("/v1/session").status_code == 401


def test_organizer_inventory_and_all_individual_resources_are_private(configured):
    store, tenant = configured
    mine = access_actor(store, "organizer")
    other = actor(store, tenant=tenant)
    own_doc = store.upload(mine, pdf(), "own-document-key1", now=time.time())
    other_doc = store.upload(other, pdf(), "other-document-key", now=time.time())
    other_run = store.create_run(
        other, other_doc["document_id"], [1], "other-run-key0001", now=time.time()
    )
    app = create_hosted_app(store.settings)
    client = TestClient(app, base_url="https://api.example.com")
    response = client.post(
        "/v1/auth/access-password",
        json={"role": "organizer", "password": "organizer-fixture-only-password"},
        headers={"Origin": ORIGIN},
    )
    headers = {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}
    assert [d["document_id"] for d in client.get("/v1/documents").json()["items"]] == [
        own_doc["document_id"]
    ]
    assert client.get("/v1/runs").json()["items"] == []
    for path in (
        f'/v1/documents/{other_doc["document_id"]}',
        f'/v1/documents/{other_doc["document_id"]}/scope-plan',
        f'/v1/documents/{other_doc["document_id"]}/original',
        f'/v1/runs?document_id={other_doc["document_id"]}',
        f'/v1/runs/{other_run["run_id"]}',
        f'/v1/runs/{other_run["run_id"]}/result',
        f'/v1/runs/{other_run["run_id"]}/source-pages/1/manifest',
        f'/v1/runs/{other_run["run_id"]}/source-pages/1/image',
    ):
        assert client.get(path).status_code == 404, path
    response = client.post(
        "/v1/runs",
        json={"document_id": other_doc["document_id"], "selected_pages": [1]},
        headers=headers | {"Idempotency-Key": "cross-run-key0001"},
    )
    assert response.status_code == 404
    response = client.post(
        "/v1/runs",
        json={"document_id": own_doc["document_id"], "selected_pages": [1]},
        headers=headers | {"Idempotency-Key": "own-run-key00001"},
    )
    assert response.status_code == 202
    own_run = response.json()
    assert client.get(own_run["status_url"]).status_code == 200
    assert [r["run_id"] for r in client.get("/v1/runs").json()["items"]] == [own_run["run_id"]]
    admin = TestClient(app, base_url="https://api.example.com")
    assert (
        admin.post(
            "/v1/auth/access-password",
            json={"role": "admin", "password": "admin-fixture-only-password"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    assert len(admin.get("/v1/documents").json()["items"]) == 2
    assert admin.get(other_run["status_url"]).status_code == 200


def test_reserved_identity_cannot_be_invited(configured):
    store, tenant = configured
    with pytest.raises(ValueError):
        store.invite(tenant, "access-password:organizer", "admin", now=time.time())


def test_credential_expiry_rechecks_existing_sessions_and_preserves_tenant_switch(configured):
    store, tenant = configured
    auth = access_actor(store, "organizer")
    selected = store.sessions.set_active_tenant(auth.session_id, tenant, now=time.time())
    assert not selected.revoked and selected.session_id != auth.session_id
    store.access.set_password(
        "organizer",
        "expired-fixture-password",
        tenant=tenant,
        expires=time.time() - 1,
        now=time.time(),
        revoke_sessions=False,
    )
    assert store.sessions.get(selected.session_id).revoked


def test_failure_window_slides_and_config_permissions_fail_closed(configured):
    store, _ = configured
    now = time.time()
    for _ in range(4):
        with pytest.raises(HostedError, match="ACCESS_PASSWORD_INVALID"):
            store.access.login("admin", "wrong-fixture-password", ip="sliding", now=now)
    with pytest.raises(HostedError, match="ACCESS_PASSWORD_INVALID"):
        store.access.login("admin", "wrong-fixture-password", ip="sliding", now=now + 601)
    store.settings.access_config.chmod(0o644)
    with pytest.raises(HostedError, match="ACCESS_CONFIG_INVALID"):
        access_actor(store, "organizer")


def test_http_lock_retry_and_untrusted_forwarded_ip_cannot_bypass(configured):
    store, _ = configured
    client = TestClient(create_hosted_app(store.settings), base_url="https://api.example.com")
    for i in range(5):
        response = client.post(
            "/v1/auth/access-password",
            json={"role": "organizer", "password": "wrong-fixture-password"},
            headers={"Origin": ORIGIN, "X-Forwarded-For": f"192.0.2.{i}"},
        )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ACCESS_PASSWORD_LOCKED"
    assert int(response.headers["Retry-After"]) == 900
    response = client.post(
        "/v1/auth/access-password",
        json={"role": "admin", "password": "admin-fixture-only-password"},
        headers={"Origin": ORIGIN, "X-Forwarded-For": "192.0.2.200"},
    )
    assert response.status_code == 429


def test_cli_default_expiry_rotation_disable_and_secret_free_output(configured, tmp_path):
    store, tenant = configured
    source = tmp_path / "password.txt"
    source.write_text("cli-fixture-only-password\n")
    source.chmod(0o600)
    env = os.environ | {
        "APP_ENV": "hosted",
        "MODEL_ADAPTER": "disabled",
        "APP_ORIGIN": ORIGIN,
        "HOSTED_DATA_DIR": str(store.root),
        "HOSTED_SESSION_SECRET": "x" * 40,
        "HOSTED_EVENT_ID": "p1-test",
        "HOSTED_ACCESS_CONFIG": str(store.settings.access_config),
        "LIVE_DISABLED": "true",
    }
    command = [sys.executable, "scripts/hosted_control.py", "access-password"]
    result = subprocess.run(
        command + ["set", "--role", "admin", "--tenant", tenant, "--from-file", str(source)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "cli-fixture" not in result.stdout + result.stderr
    from datetime import datetime

    config = json.loads(store.settings.access_config.read_text())
    assert (
        config["accounts"]["admin"]["expires"]
        == datetime.fromisoformat("2026-10-20T23:59:00+09:00").timestamp()
    )
    auth = store.access.login("admin", "cli-fixture-only-password", ip="cli", now=time.time())
    subprocess.run(
        command + ["disable", "--role", "admin"], env=env, capture_output=True, check=True
    )
    assert store.sessions.get(auth).revoked
    source.chmod(0o644)
    result = subprocess.run(
        command + ["set", "--role", "admin", "--from-file", str(source)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "cli-fixture" not in result.stdout + result.stderr


def test_additive_migration_and_backup_exclude_password_sessions(configured, tmp_path):
    store, _ = configured
    auth = access_actor(store, "admin")
    assert HostedStore(store.settings).sessions.get(auth.session_id)
    backup = store.backup(tmp_path / "backup", now=time.time())
    import sqlite3

    with sqlite3.connect(backup / "control.sqlite3") as db:
        for table in ("sessions", "access_sessions", "access_auth_audit", "access_login_failures"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert not (Path(backup) / "access.json").exists()
