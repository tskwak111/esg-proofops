"""HTTP contract checks for TASK-025 rule-pack activation integration."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from proofops.adapters.local.auth_store import InMemoryMembershipStore, InMemorySessionStore
from proofops.application.authorization import MembershipRecord, SessionRecord
from proofops.application.rulepacks import (
    RulePackRecord,
    RunSnapshot,
    compute_pack_sha256,
)
from proofops_api.auth import AuthStore

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
PACK_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RUN_A = "33333333-3333-4333-8333-333333333333"
SOURCE_SHA = "0f9d7e3495d1bc6330ee4ffd2bb644ce8189c89e91dd5f9ae4c720b9ffaebc6a"
GAP_IDS = tuple(f"GAP-{number:03d}" for number in range(1, 11))


def _files() -> dict[str, dict[str, object]]:
    return {
        "regulatory/safe_harbor.yaml": {
            "version": "proofops-domain-v2.0-impl1",
            "effective_date": "2026-09-08",
            "source_document_sha256": SOURCE_SHA,
            "grade_mapping": None,
            "reasonable_basis_boolean_mapping": None,
        },
        "regulatory/timeline.yaml": {
            "version": "proofops-domain-v2.0-impl1",
            "effective_date": "2026-09-08",
            "source_document_sha256": SOURCE_SHA,
            "automatic_legal_applicability_enabled": False,
        },
    }


def _pack(
    *,
    tenant_id: str = TENANT_A,
    pack_id: str = PACK_A,
    status: str = "validated",
    approved_by: str | None = "domain-owner@example.test",
) -> RulePackRecord:
    files = _files()
    data: dict[str, object] = {
        "rule_pack_id": pack_id,
        "tenant_id": tenant_id,
        "version": "proofops-domain-v2.0-impl1",
        "effective_date": "2026-09-08",
        "mode": "disclosure",
        "status": status,
        "ontology_version": "proofops-elements-1",
        "source_document_sha256": SOURCE_SHA,
        "files": list(files),
        "unresolved_gap_ids": list(GAP_IDS),
        "approved_by": approved_by,
        "approved_at": "2026-09-08T10:00:00Z" if approved_by else None,
    }
    data["sha256"] = compute_pack_sha256(data, files)
    return RulePackRecord.from_dict(data)


def _client(tmp_path: Path, *, role: str = "admin") -> tuple[TestClient, object, str]:
    try:
        from proofops.adapters.local.rulepack_store import RulePackSqliteStore
        from proofops_api.rulepacks import build_rulepack_router
    except ModuleNotFoundError as exc:  # RED: endpoint/store do not exist yet.
        pytest.fail(str(exc))

    sessions = InMemorySessionStore()
    memberships = InMemoryMembershipStore()
    auth_store = AuthStore(sessions=sessions, memberships=memberships)
    csrf_token = _seed_auth(auth_store, role=role)
    rulepacks = RulePackSqliteStore(tmp_path / "state.sqlite3")
    app = FastAPI()
    app.include_router(
        build_rulepack_router(
            rulepacks,
            auth_store,
            gap_ids=GAP_IDS,
            allowed_origin="http://testserver",
        )
    )
    client = TestClient(app)
    client.cookies.set("__Host-proofops_session", "admin-session")
    return client, rulepacks, csrf_token


def _seed_auth(auth_store: AuthStore, *, role: str = "admin") -> str:
    far_future = time.time() + 10_000
    auth_store.sessions.put_with_token(
        SessionRecord(
            "admin-session",
            "admin-user",
            TENANT_A,
            auth_store.hash_csrf("csrf-token"),
            far_future,
            far_future,
            False,
        ),
        "csrf-token",
    )
    auth_store.memberships.put(MembershipRecord(TENANT_A, "admin-user", role, "active"))
    csrf_token = auth_store.sessions.csrf_token_for("admin-session")
    assert csrf_token is not None
    return csrf_token


def _headers(
    csrf_token: str, *, if_match: int = 1, key: str = "activate-rulepack-key"
) -> dict[str, str]:
    return {
        "X-CSRF-Token": csrf_token,
        "Origin": "http://testserver",
        "Idempotency-Key": key,
        "If-Match": f'"{if_match}"',
    }


def test_approved_activation_changes_new_run_pointer_not_inflight_snapshot(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path)
    pack = _pack()
    store.add_pack(pack, _files())
    running = RunSnapshot(RUN_A, TENANT_A, PACK_A, pack.sha256, "running")
    store.add_run_snapshot(running)

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "approve validated pack"},
        headers=_headers(csrf_token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "rule_pack_id": PACK_A,
        "version": "proofops-domain-v2.0-impl1",
        "sha256": pack.sha256,
        "status": "active",
        "mode": "disclosure",
        "effective_date": "2026-09-08",
        "unresolved_gap_ids": list(GAP_IDS),
    }
    assert response.headers["etag"] == '"2"'
    assert store.active_pack_id(TENANT_A, "disclosure") == PACK_A
    assert store.get_run_snapshot(TENANT_A, RUN_A) == running


def test_activation_requires_admin_capability(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path, role="reviewer")
    store.add_pack(_pack(), _files())

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "reviewer cannot activate"},
        headers=_headers(csrf_token),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert store.active_pack_id(TENANT_A, "disclosure") is None


def test_activation_requires_csrf_token_and_same_origin(tmp_path: Path) -> None:
    client, store, _csrf_token = _client(tmp_path)
    store.add_pack(_pack(), _files())
    headers = _headers("wrong-token")

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "attempt without valid csrf"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"
    assert store.active_pack_id(TENANT_A, "disclosure") is None


def test_cross_tenant_rule_pack_is_indistinguishable_from_missing(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path)
    store.add_pack(_pack(tenant_id=TENANT_B), _files())

    hidden = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "try another tenant pack"},
        headers=_headers(csrf_token, key="cross-tenant-key"),
    )
    missing = client.post(
        "/v1/rule-packs/99999999-9999-4999-8999-999999999999/activate",
        json={"reason": "try missing tenant pack"},
        headers=_headers(csrf_token, key="missing-pack-key"),
    )

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["error"]["code"] == missing.json()["error"]["code"]
    assert set(hidden.json()["error"]) == set(missing.json()["error"])


def test_stale_if_match_returns_current_revision_without_mutation(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path)
    store.add_pack(_pack(), _files())

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "stale activation attempt"},
        headers=_headers(csrf_token, if_match=2, key="stale-activate-key"),
    )

    assert response.status_code == 412
    assert response.json()["error"]["code"] == "STALE_RULEPACK_REVISION"
    assert response.json()["error"]["details"] == {"current_revision": 1}
    assert store.active_pack_id(TENANT_A, "disclosure") is None


def test_idempotency_replays_after_restart_and_changed_body_conflicts(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path)
    pack = _pack()
    store.add_pack(pack, _files())
    body = {"reason": "activate once only"}
    headers = _headers(csrf_token, key="durable-replay-key")

    first = client.post(f"/v1/rule-packs/{PACK_A}/activate", json=body, headers=headers)
    replay = client.post(f"/v1/rule-packs/{PACK_A}/activate", json=body, headers=headers)
    changed = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "different activation reason"},
        headers=headers,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.headers["etag"] == replay.headers["etag"] == '"2"'
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    reopened = RulePackSqliteStore(store.path)
    durable_replay = reopened.activate(
        tenant_id=TENANT_A,
        rule_pack_id=PACK_A,
        expected_revision=1,
        idempotency_key="durable-replay-key",
        actor="admin-user",
        reason=body["reason"],
        gap_ids=GAP_IDS,
        now=time.time(),
    )
    assert durable_replay.body == first.json()
    assert durable_replay.revision == 2
    assert reopened.active_pack_id(TENANT_A, "disclosure") == PACK_A
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT count(*) FROM rulepack_revisions").fetchone()[0] == 2
        assert (
            connection.execute("SELECT count(*) FROM rulepack_idempotency_records").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "pack",
    [
        _pack(status="draft"),
        _pack(approved_by=None),
    ],
    ids=["draft", "missing-recorded-approver"],
)
def test_repository_draft_or_unapproved_pack_cannot_activate(
    tmp_path: Path, pack: RulePackRecord
) -> None:
    client, store, csrf_token = _client(tmp_path)
    store.add_pack(pack, _files())

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "must not invent approval"},
        headers=_headers(csrf_token, key=f"blocked-{pack.status}-{pack.approved_by}"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RULEPACK_ACTIVATION_BLOCKED"
    assert store.active_pack_id(TENANT_A, "disclosure") is None


def test_empty_local_store_does_not_seed_or_activate_repository_draft(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path)

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "repository draft is not runtime approval"},
        headers=_headers(csrf_token, key="no-repository-seed-key"),
    )

    assert response.status_code == 404
    assert store.active_pack_id(TENANT_A, "disclosure") is None


def test_missing_if_match_uses_contract_error_shape(tmp_path: Path) -> None:
    client, store, csrf_token = _client(tmp_path)
    store.add_pack(_pack(), _files())
    headers = _headers(csrf_token)
    del headers["If-Match"]

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "missing concurrency token"},
        headers=headers,
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message", "request_id", "retryable"}


@pytest.mark.parametrize("key", [None, "too-short"])
def test_missing_or_short_idempotency_key_uses_contract_error_shape(
    tmp_path: Path, key: str | None
) -> None:
    client, store, csrf_token = _client(tmp_path)
    store.add_pack(_pack(), _files())
    headers = _headers(csrf_token)
    if key is None:
        del headers["Idempotency-Key"]
    else:
        headers["Idempotency-Key"] = key

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json={"reason": "invalid idempotency key"},
        headers=headers,
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "no"},
        {"reason": "valid reason", "approved_by": "invented@example.test"},
    ],
    ids=["reason-too-short", "approval-injection"],
)
def test_invalid_action_reason_uses_contract_error_shape(
    tmp_path: Path, payload: dict[str, str]
) -> None:
    client, store, csrf_token = _client(tmp_path)
    store.add_pack(_pack(), _files())

    response = client.post(
        f"/v1/rule-packs/{PACK_A}/activate",
        json=payload,
        headers=_headers(csrf_token),
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_activation_audit_is_atomic_and_idempotent_replay_adds_no_event(tmp_path: Path) -> None:
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    store = RulePackSqliteStore(tmp_path / "state.sqlite3", id_factory=lambda: "activation-1")
    store.add_pack(_pack(), _files())
    arguments = {
        "tenant_id": TENANT_A,
        "rule_pack_id": PACK_A,
        "expected_revision": 1,
        "idempotency_key": "audit-replay-key",
        "actor": "admin-user",
        "reason": "record approved activation",
        "gap_ids": GAP_IDS,
        "now": 1_000.0,
    }

    store.activate(**arguments)
    store.activate(**arguments)

    with sqlite3.connect(store.path) as connection:
        events = connection.execute(
            """SELECT activation_id, actor_sub, reason, before_pack_id,
                      after_pack_id, activated_at
               FROM rulepack_activation_events"""
        ).fetchall()
    assert events == [
        (
            "activation-1",
            "admin-user",
            "record approved activation",
            None,
            PACK_A,
            "1970-01-01T00:16:40Z",
        )
    ]


def test_idempotency_key_expires_after_24_hours(tmp_path: Path) -> None:
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    activation_ids = iter(("activation-1", "activation-2"))
    store = RulePackSqliteStore(tmp_path / "state.sqlite3", id_factory=lambda: next(activation_ids))
    store.add_pack(_pack(), _files())
    store.activate(
        tenant_id=TENANT_A,
        rule_pack_id=PACK_A,
        expected_revision=1,
        idempotency_key="expiring-idempotency-key",
        actor="admin-user",
        reason="first activation reason",
        gap_ids=GAP_IDS,
        now=1_000.0,
    )

    after_expiry = store.activate(
        tenant_id=TENANT_A,
        rule_pack_id=PACK_A,
        expected_revision=2,
        idempotency_key="expiring-idempotency-key",
        actor="admin-user",
        reason="new intent after expiry",
        gap_ids=GAP_IDS,
        now=87_401.0,
    )

    assert after_expiry.revision == 2
    with sqlite3.connect(store.path) as connection:
        event_count = connection.execute(
            "SELECT count(*) FROM rulepack_activation_events"
        ).fetchone()[0]
        expiry = connection.execute(
            "SELECT expires_at FROM rulepack_idempotency_records"
        ).fetchone()[0]
    assert event_count == 2
    assert expiry == 173_801.0


def test_rulepack_store_coexists_without_claiming_global_schema_version(tmp_path: Path) -> None:
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 7")
    connection.execute("CREATE TABLE registry_marker (id TEXT PRIMARY KEY)")
    connection.commit()
    connection.close()

    RulePackSqliteStore(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            connection.execute(
                "SELECT version FROM rulepack_schema_metadata WHERE component='rulepacks'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='registry_marker'"
            ).fetchone()[0]
            == "registry_marker"
        )


def test_rulepack_store_fails_closed_on_unknown_component_schema(tmp_path: Path) -> None:
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE rulepack_schema_metadata (component TEXT PRIMARY KEY, version INTEGER)"
    )
    connection.execute("INSERT INTO rulepack_schema_metadata VALUES ('rulepacks', 2)")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="unsupported local rulepack schema version: 2"):
        RulePackSqliteStore(path)


def test_rulepack_and_run_identities_are_immutable(tmp_path: Path) -> None:
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    store = RulePackSqliteStore(tmp_path / "state.sqlite3")
    pack = _pack()
    store.add_pack(pack, _files())
    with pytest.raises(ValueError, match="immutable rule-pack identity"):
        store.add_pack(replace(pack, approved_by="another-approver"), _files())

    snapshot = RunSnapshot(RUN_A, TENANT_A, PACK_A, pack.sha256, "running")
    store.add_run_snapshot(snapshot)
    with pytest.raises(ValueError, match="immutable run snapshot"):
        store.add_run_snapshot(replace(snapshot, status="completed"))


def test_active_pack_reader_uses_durable_pointer_after_reopen(tmp_path: Path) -> None:
    from proofops.adapters.local.rulepack_store import RulePackSqliteStore

    path = tmp_path / "state.sqlite3"
    store = RulePackSqliteStore(path)
    store.add_pack(_pack(), _files())
    store.activate(
        tenant_id=TENANT_A,
        rule_pack_id=PACK_A,
        expected_revision=1,
        idempotency_key="active-reader-key",
        actor="admin-user",
        reason="activate durable reader",
        gap_ids=GAP_IDS,
        now=1_000.0,
    )

    active = RulePackSqliteStore(path).list_active_packs(TENANT_A)

    assert len(active) == 1
    assert active[0].rule_pack_id == PACK_A
    assert active[0].status == "active"


def test_generated_openapi_matches_activation_contract(tmp_path: Path) -> None:
    client, _store, _csrf_token = _client(tmp_path)
    operation = client.app.openapi()["paths"]["/v1/rule-packs/{rule_pack_id}/activate"]["post"]

    assert operation["operationId"] == "rulepack_activate"
    assert operation["security"] == [{"sessionCookie": []}]
    assert operation["x-minimum-role"] == "admin"
    assert operation["x-idempotency-required"] is True
    assert {
        (parameter["name"], parameter["in"], parameter["required"])
        for parameter in operation["parameters"]
    } == {
        ("rule_pack_id", "path", True),
        ("X-CSRF-Token", "header", True),
        ("Idempotency-Key", "header", True),
        ("If-Match", "header", True),
    }
    assert set(operation["responses"]) == {
        "200",
        "400",
        "401",
        "403",
        "404",
        "409",
        "412",
        "422",
        "429",
        "503",
    }
    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_ref == {"$ref": "#/components/schemas/RulePack"}


def test_composed_local_app_exposes_rulepack_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("MODEL_ADAPTER", "synthetic")
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("LOCAL_DATABASE_PATH", str(tmp_path / "composed.sqlite3"))

    from proofops_api.main import create_app

    app = create_app()
    composition = app.state.composition
    csrf_token = _seed_auth(composition.auth_store)
    composition.rulepack_store.add_pack(_pack(), _files())

    with TestClient(app) as client:
        client.cookies.set("__Host-proofops_session", "admin-session")
        response = client.post(
            f"/v1/rule-packs/{PACK_A}/activate",
            json={"reason": "activate through composition"},
            headers=_headers(csrf_token, key="composed-activation-key"),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
