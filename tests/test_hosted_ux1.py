"""UX1 additive metadata: persistence, ownership, replay and purge (no providers)."""

import json
from urllib.parse import quote

import pytest
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import HostedError
from proofops_api.hosted_ux1 import UX1_POLICY_SHA256, parse_metadata

from tests import test_hosted_public as base
from tests import test_pa6_reads as reads_fixtures
from tests.test_hosted_public import login, pdf

settings = base.settings
store = base.store


def test_metadata_upload_cors_allows_only_configured_origin(store, settings):
    from fastapi.testclient import TestClient

    client = TestClient(create_hosted_app(settings))
    headers = {
        "Origin": settings.origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": (
            "Content-Type,X-CSRF-Token,Idempotency-Key,X-UX1-Metadata"
        ),
    }
    response = client.options("/v1/documents", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == settings.origin
    assert "x-ux1-metadata" in response.headers["access-control-allow-headers"].lower()
    rejected = client.options(
        "/v1/documents", headers=headers | {"Origin": "https://untrusted.example"}
    )
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_metadata_is_opt_in_bounded_and_cannot_set_paths():
    assert parse_metadata(None) is None
    value = {"policy_sha256": UX1_POLICY_SHA256, "original_filename": "../회사 2025.pdf"}
    assert parse_metadata(quote(json.dumps(value)))["original_filename"] == "회사 2025.pdf"
    for bad in [
        [],
        {},
        {**value, "policy_sha256": "old"},
        {**value, "title": "x" * 201},
        {**value, "title": "x\ny"},
        {**value, "company_name": "injected"},
    ]:
        with pytest.raises(HostedError):
            parse_metadata(quote(json.dumps(bad)))


def test_http_metadata_survives_reload_replay_and_is_deleted_with_document(store, settings):
    app = create_hosted_app(settings)
    first, headers, tenant, user = login(app, store)
    other, _, _, _ = login(app, store)
    value = {
        "policy_sha256": UX1_POLICY_SHA256,
        "original_filename": "검증회사 2025 ESG보고서.pdf",
        "title": "PDF 내부 제목",
    }
    h = headers | {
        "Content-Type": "application/pdf",
        "Idempotency-Key": "ux1-upload-key-001",
        "X-UX1-Metadata": quote(json.dumps(value)),
    }
    content = pdf()
    response = first.post("/v1/documents", content=content, headers=h)
    assert response.status_code == 201, response.text
    doc = response.json()
    path = f"/v1/documents/{doc['document_id']}"
    assert doc["ux1_metadata"] == value
    assert other.get(path).status_code == 404
    # A fresh session reads server metadata; no browser storage is involved.
    fresh, fresh_headers, _, _ = login(app, store, tenant=tenant, user=user)
    assert fresh.get(path).json()["ux1_metadata"] == value
    assert fresh.get("/v1/documents").json()["items"][0]["ux1_metadata"] == value
    replay = first.post(
        "/v1/documents",
        content=content,
        headers=h | {"X-UX1-Metadata": quote(json.dumps({**value, "title": "replacement"}))},
    )
    assert replay.json() == doc  # first metadata and PDF identity are immutable
    deleted = fresh.post(
        path + "/deletion-requests",
        json={"reason": "UX1 test cleanup"},
        headers=fresh_headers | {"Idempotency-Key": "ux1-delete-key-001"},
    )
    assert deleted.status_code == 202
    assert fresh.get(path).status_code == 404
    assert not (store.document_dir(tenant, doc["document_id"]) / "ux1-metadata.json").exists()


def test_old_upload_shape_and_replay_remain_unchanged(store, settings):
    app = create_hosted_app(settings)
    client, headers, _, _ = login(app, store)
    h = headers | {"Content-Type": "application/pdf", "Idempotency-Key": "ux1-old-upload-001"}
    content = pdf()
    old = client.post("/v1/documents", content=content, headers=h).json()
    assert "ux1_metadata" not in old
    assert client.post("/v1/documents", content=content, headers=h).json() == old


def test_data_projection_uses_pinned_graph_and_keeps_input_unchanged(tmp_path):
    from hashlib import sha256
    from types import SimpleNamespace

    from proofops_api.hosted_ux1 import project_data

    directory = tmp_path / "analysis/run/parser-prepared/tenant/version/manifest"
    directory.mkdir(parents=True)
    graph = {
        "document_version_id": "version",
        "parse_manifest_id": "manifest",
        "source_sha256": "source",
        "blocks": [{"kind": "table"}, {"kind": "paragraph"}, {"kind": "table"}],
    }
    raw = json.dumps(graph).encode()
    (directory / "graph.json").write_bytes(raw)
    manifest = json.dumps(
        {"tenant_id": "tenant", "artifacts": {"graph.json": sha256(raw).hexdigest()}}
    ).encode()
    (directory / "manifest.json").write_bytes(manifest)
    reads = SimpleNamespace(
        store=SimpleNamespace(document_dir=lambda *args: tmp_path),
        _anchor=lambda *args: ("version", "manifest", sha256(manifest).hexdigest(), None),
    )
    row = {
        "tenant_id": "tenant",
        "document_id": "doc",
        "run_id": "run",
        "prepared_sha256": "source",
    }
    result = {"page_map": [16, 24], "pipeline": {"status": "completed"}, "claims": []}
    before = json.dumps(result)
    assert project_data(reads, row, result)["pipeline"]["ux1_data"]["table_count"] == 2
    assert json.dumps(result) == before
    (directory / "graph.json").write_text("tampered")
    assert project_data(reads, row, result)["pipeline"]["ux1_data"]["table_count"] is None
    assert (
        project_data(reads, row, result | {"reuse": {"reused": True}})["pipeline"]["ux1_data"][
            "table_count"
        ]
        is None
    )


publication = reads_fixtures.publication
published = reads_fixtures.published


def test_result_query_is_opt_in_additive_and_preserves_snapshot_bytes(published):
    app, store, client, owner, done, stored = published
    path = store.document_dir(owner.tenant_id, done["document_id"]) / "analysis" / done["run_id"]
    snapshots = {p.name: p.read_bytes() for p in path.glob("result-*.json")}
    route = f'/v1/runs/{done["run_id"]}/result'
    baseline = client.get(route).json()
    assert "ux1_data" not in baseline.get("pipeline", {})
    assert client.get(route, params={"ux1": "old"}).json() == baseline
    response = client.get(route, params={"ux1": UX1_POLICY_SHA256})
    assert response.status_code == 200, response.text
    projected = response.json()
    added = projected["pipeline"].pop("ux1_data")
    assert added["policy_sha256"] == UX1_POLICY_SHA256
    assert isinstance(added["table_count"], int)
    assert added["table_count"] >= 0
    assert projected == baseline
    assert {p.name: p.read_bytes() for p in path.glob("result-*.json")} == snapshots


def test_v29d_result_defaults_to_ux1_without_rewriting_snapshot(published, monkeypatch):
    from proofops.application.analysis_profile import FINALS_I31_POLICY, V2_PROFILE
    from proofops.domain.provenance import canonical_hash

    app, store, client, owner, done, stored = published
    path = store.document_dir(owner.tenant_id, done["document_id"]) / "analysis" / done["run_id"]
    snapshots = {p.name: p.read_bytes() for p in path.glob("result-*.json")}
    options = store.run_options
    monkeypatch.setattr(
        store,
        "run_options",
        lambda row: options(row)
        | dict(
            analysis_profile=V2_PROFILE, analysis_profile_sha256=canonical_hash(FINALS_I31_POLICY)
        ),
    )
    route = f'/v1/runs/{done["run_id"]}/result'
    response = client.get(route)
    assert response.status_code == 200, response.text
    measured = response.json()["pipeline"]["ux1_data"]
    assert measured["policy_sha256"] == UX1_POLICY_SHA256
    assert isinstance(measured["table_count"], int)
    assert measured["table_count"] >= 0
    assert client.get(route, params={"ux1": UX1_POLICY_SHA256}).json() == response.json()
    assert {p.name: p.read_bytes() for p in path.glob("result-*.json")} == snapshots
