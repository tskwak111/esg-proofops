"""D-07: DART reconciliation is a default-off feature flag.

Real composition, real FastAPI app, real SQLite file. OFF must leave no
reconciliation tables, artifact directory, or routes and must not change any
other API surface; ON must keep the current reconciliation behavior.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from proofops_api.composition import reconciliation_enabled

from tests.acceptance.test_upload import TENANT
from tests.reconciliation.test_product_http import COOKIE, seed_sessions

ORIGIN = "http://testserver"
RUN, CLAIM = str(uuid4()), str(uuid4())
LIST = f"/v1/runs/{RUN}/claims/{CLAIM}/reconciliation"


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str | None):
    for name, value in {
        "APP_ENV": "local",
        "MODEL_ADAPTER": "synthetic",
        "APP_ORIGIN": ORIGIN,
        "LOCAL_DATABASE_PATH": str(tmp_path / "state.sqlite3"),
        "ENABLE_YEAR_COMPARISON": "false",
    }.items():
        monkeypatch.setenv(name, value)
    if flag is None:
        monkeypatch.delenv("ENABLE_RECONCILIATION", raising=False)
    else:
        monkeypatch.setenv("ENABLE_RECONCILIATION", flag)
    from proofops_api.main import create_app

    return create_app()


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def _reconciliation_paths(app) -> set[str]:
    return {path for path in app.openapi()["paths"] if "reconciliation" in path}


def _without_name_clash(document: dict) -> dict:
    """With reconciliation on, FastAPI qualifies the sources router's SourceRef
    because the reconciliation router declares another model of that name.
    Only the component name differs; contracts/openapi.yaml uses the plain name."""
    return json.loads(re.sub(r"proofops_api__routers__sources__", "", json.dumps(document)))


def _viewer(client: TestClient) -> TestClient:
    seed_sessions(client.app.state.composition.auth_store)
    client.cookies.set(COOKIE, "viewer-session")
    return client


@pytest.mark.parametrize("flag", [None, "false", "", "1", "TRUE", "yes", " true"])
def test_only_the_exact_value_true_enables_reconciliation(flag):
    environ = {} if flag is None else {"ENABLE_RECONCILIATION": flag}
    assert reconciliation_enabled(environ) is False
    assert reconciliation_enabled({"ENABLE_RECONCILIATION": "true"}) is True


@pytest.mark.parametrize("flag", [None, "false", "TRUE"])
def test_off_builds_no_store_tables_artifacts_or_routes(tmp_path, monkeypatch, flag):
    app = _app(tmp_path, monkeypatch, flag)
    try:
        assert app.state.composition.reconciliation is None
        assert _reconciliation_paths(app) == set()
        with TestClient(app, base_url=ORIGIN) as client:
            response = _viewer(client).get(LIST)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not Found"}
            case = client.get(f"/v1/reconciliation/cases/{uuid4()}")
            assert case.status_code == 404
            assert case.json() == {"detail": "Not Found"}
        tables = _tables(tmp_path / "state.sqlite3")
        assert tables, "the rest of the local schema must still initialize"
        assert not any(name.startswith("reconciliation") for name in tables)
        assert not (tmp_path / "reconciliation-artifacts").exists()
    finally:
        app.state.composition.uploads.close()
        app.state.composition.registry.close()


def test_on_preserves_the_reconciliation_store_and_router(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, "true")
    try:
        assert app.state.composition.reconciliation is not None
        assert len(_reconciliation_paths(app)) == 7
        assert {
            "reconciliation_schema",
            "reconciliation_case",
            "reconciliation_head",
            "reconciliation_revision",
        } <= _tables(tmp_path / "state.sqlite3")
        assert (tmp_path / "reconciliation-artifacts").is_dir()
        with TestClient(app, base_url=ORIGIN) as client:
            assert client.get(LIST).status_code == 401
            response = _viewer(client).get(LIST)
            assert response.status_code == 200, response.text
            assert response.json() == {"items": []}
    finally:
        app.state.composition.uploads.close()
        app.state.composition.registry.close()


def test_the_flag_changes_no_other_api_surface(tmp_path, monkeypatch):
    apps = {}
    for flag in ("false", "true"):
        root = tmp_path / flag
        root.mkdir()
        apps[flag] = _app(root, monkeypatch, flag)
    try:
        off = apps["false"].openapi()
        on = _without_name_clash(apps["true"].openapi())
        assert "proofops_api__routers__" not in json.dumps(off)
        on_paths = {p: v for p, v in on["paths"].items() if "reconciliation" not in p}
        assert off["paths"] == on_paths
        off_schemas = off.get("components", {}).get("schemas", {})
        on_schemas = on.get("components", {}).get("schemas", {})
        assert off_schemas == {name: on_schemas[name] for name in off_schemas}
        # The baseline endpoints keep serving either way.
        for flag, app in apps.items():
            with TestClient(app, base_url=ORIGIN) as client:
                assert client.get("/v1/health/live").json()["status"] == "ok", flag
    finally:
        for app in apps.values():
            app.state.composition.uploads.close()
            app.state.composition.registry.close()


def test_off_still_mounts_every_other_declared_contract_route(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, None)
    try:
        declared = yaml.safe_load(
            (Path(__file__).parents[2] / "contracts/openapi.yaml").read_text(encoding="utf-8")
        )["paths"]
        mounted = app.openapi()["paths"]
        checked = 0
        for path, methods in declared.items():
            for method, operation in methods.items():
                if not isinstance(operation, dict) or "operationId" not in operation:
                    continue
                operation_id = mounted.get(path, {}).get(method, {}).get("operationId")
                if "reconciliation" in path:
                    assert operation_id is None, path
                else:
                    assert operation_id == operation["operationId"], path
                    checked += 1
        assert checked > 40
    finally:
        app.state.composition.uploads.close()
        app.state.composition.registry.close()


def test_operator_import_enables_reconciliation_for_its_own_process(tmp_path, monkeypatch):
    from evaluation import reconciliation_import

    database = tmp_path / "state.sqlite3"
    database.touch()
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOCAL_DATABASE_PATH", str(database))
    monkeypatch.setenv("ENABLE_RECONCILIATION", "false")
    seen: list[str | None] = []
    closed: list[str] = []

    def compose():
        import os

        seen.append(os.environ.get("ENABLE_RECONCILIATION"))
        return SimpleNamespace(
            reconciliation=None,
            uploads=SimpleNamespace(close=lambda: closed.append("uploads")),
            registry=SimpleNamespace(close=lambda: closed.append("registry")),
        )

    monkeypatch.setattr("proofops_api.composition.build_composition", compose)
    code = reconciliation_import.main(
        [
            "--database",
            str(database),
            "--bundle",
            str(tmp_path / "missing-bundle"),
            "--artifacts",
            str(tmp_path / "missing-artifacts"),
            "--tenant-id",
            TENANT,
            "--run-id",
            RUN,
            "--claim-id",
            CLAIM,
            "--actor",
            "operator@example.test",
        ]
    )
    assert seen == ["true"]
    # A composition that still has no store fails closed instead of crashing.
    assert code == 2
    assert closed == ["uploads", "registry"]
