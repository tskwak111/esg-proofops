"""PA6 real authenticated reads, retention and pixel alignment; no paid providers."""

import io
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from proofops_api.hosted import create_hosted_app
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, RectangleObject

from tests.test_hosted_public import actor, login, pdf
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def test_collection_auth_tenant_pagination_and_privacy(settings):
    app = create_hosted_app(settings)
    store = app.state.composition
    owner = actor(store)
    foreign = actor(store)
    docs = [
        store.upload(owner, pdf(), f"pa6-upload-key-{i:04d}", now=time.time() + i) for i in range(3)
    ]
    store.upload(foreign, pdf(), "pa6-foreign-upload", now=time.time())
    client, _, _, _ = login(app, store, tenant=owner.tenant_id, role="viewer")
    assert TestClient(app).get("/v1/documents").status_code == 401
    first = client.get("/v1/documents?limit=2")
    assert first.status_code == 200, first.text
    body = first.json()
    assert [x["document_id"] for x in body["items"]] == [d["document_id"] for d in docs[::-1]][:2]
    assert body["items"][0]["display_name"] == "보고서 3"
    assert body["items"][0]["uploaded_at"]
    assert "user_hash" not in first.text and "consent_version" not in first.text
    second = client.get("/v1/documents", params={"cursor": body["next_cursor"], "limit": 2})
    assert [x["document_id"] for x in second.json()["items"]] == [docs[0]["document_id"]]
    assert second.json()["next_cursor"] is None
    other, _, _, _ = login(app, store, tenant=foreign.tenant_id)
    assert other.get("/v1/documents", params={"cursor": body["next_cursor"]}).status_code == 400
    assert client.get("/v1/runs", params={"cursor": body["next_cursor"]}).status_code == 400
    for limit in (0, 101):
        assert client.get(f"/v1/documents?limit={limit}").status_code == 422
    assert client.get("/v1/documents?cursor=forged").status_code == 400
    store.create_run(owner, docs[0]["document_id"], [1], "pa6-list-run-key001", now=time.time())
    runs = client.get("/v1/runs").json()["items"]
    assert len(runs) == 1 and runs[0]["stage"] == "queued" and runs[0]["result_url"] is None
    assert "user_active_count" not in runs[0] and "prepared_sha256" not in runs[0]
    assert (
        client.get("/v1/runs", params={"document_id": docs[1]["document_id"]}).json()["items"] == []
    )
    assert other.get("/v1/runs", params={"document_id": docs[0]["document_id"]}).status_code == 404


def test_render_fixed_dpi_crop_and_all_rotations(tmp_path):
    from proofops.application.ingest.geometry import canonical_bbox_from_native
    from proofops.domain.documents import PageGeometry
    from proofops_api.hosted_page_render import render

    writer = PdfWriter()
    for rotation in (0, 90, 180, 270):
        page = writer.add_blank_page(600, 800)
        page.cropbox = RectangleObject([50, 100, 550, 750])
        page.rotate(rotation)
        stream = DecodedStreamObject()
        stream.set_data(b"1 0 0 rg 100 200 40 50 re f 0 0 1 rg 0 0 30 30 re f")
        page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "source.pdf"
    writer.write(path)
    for page, rotation in enumerate((0, 90, 180, 270), 1):
        w, h = (650, 500) if rotation in (90, 270) else (500, 650)
        geometry = PageGeometry(w, h, rotation, (50, 100, 550, 750))
        png, metadata = render(path, page, geometry, tmp_path)
        assert (metadata["width_px"], metadata["height_px"]) == (w * 2, h * 2)
        bbox = canonical_bbox_from_native((100, 200, 140, 250), geometry)
        image = Image.open(io.BytesIO(png)).convert("RGB")
        x, y = int(bbox[0] + bbox[2]), int(bbox[1] + bbox[3])
        assert image.getpixel((x, y)) == (255, 0, 0)
        assert (0, 0, 255) not in image.getdata()


def test_expired_resources_omitted(settings):
    app = create_hosted_app(settings)
    store = app.state.composition
    owner = actor(store)
    store.upload(owner, pdf(), "pa6-expired-upload", now=time.time() - 8 * 86400)
    client, _, _, _ = login(app, store, tenant=owner.tenant_id)
    response = client.get("/v1/documents")
    assert response.status_code == 200 and response.json()["items"] == []


@pytest.fixture(scope="module")
def publication(tmp_path_factory):
    from proofops_api import hosted_analysis

    from evaluation.hosted_r108 import drive
    from tests.test_hosted_analysis import fake_llm, fake_parse, source_pdf
    from tests.test_hosted_ocr import fake_page_ocr

    def verified_analysis(store, job, prepared):
        with TemporaryDirectory() as scratch, pytest.MonkeyPatch.context() as patch:
            patch.setattr(os, "environ", os.environ.copy())
            patch.setattr(hosted_analysis.sys, "platform", "linux")
            workspace = Path(scratch)
            (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
            state, outcome = drive(
                store,
                job,
                workspace,
                dict(
                    report_year=2025,
                    period_start="2024-01-01",
                    period_end="2024-12-31",
                    analysis_profile="r108-finals-candidate-v2",
                ),
                llm_post=fake_llm,
                parse_post=fake_parse,
                ocr_post=fake_page_ocr,
            )
            store.publish_analysis(job, state, outcome["status"], outcome["reason"])

    settings = _settings.__wrapped__(tmp_path_factory.mktemp("pa6-publication"))
    app = create_hosted_app(settings)
    store = app.state.composition
    owner = actor(store)
    doc = store.upload(owner, source_pdf(), "pa6-published-upload", now=time.time())
    store.create_run(owner, doc["document_id"], [2], "pa6-published-run001", now=time.time())
    done = store.tick(now=time.time(), analysis=verified_analysis)
    assert done["result_url"], done
    result = store.get_result(owner.tenant_id, done["run_id"])
    assert result["claims"]
    return settings, owner, done, result


@pytest.fixture
def published(publication, tmp_path):
    settings, owner, done, result = publication
    root = tmp_path / "copy"
    shutil.copytree(settings.root, root)
    app = create_hosted_app(replace(settings, root=root))
    store = app.state.composition
    client, _, _, _ = login(app, store, tenant=owner.tenant_id, role="viewer")
    return app, store, client, owner, done, result


def route(done, suffix="manifest", page=2):
    return f"/v1/runs/{done['run_id']}/source-pages/{page}/{suffix}"


def test_source_manifest_png_mapping_and_result_listing(published):
    _, store, client, owner, done, result = published
    before = store.budget_totals()
    response = client.get(route(done))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["physical_page"] == 2 and body["prepared_page"] == 1
    assert (
        body["source_sha256"] == store.get_document(owner.tenant_id, done["document_id"])["sha256"]
    )
    ref = result["claims"][0]["source_refs"][0]
    assert body["document_version_id"] == ref["document_version_id"]
    assert body["parse_manifest_id"] == ref["parse_manifest_id"]
    assert body["highlights"]
    box = ref["bbox"]
    expected = [box[0] / 600, box[1] / 400, box[2] / 600, box[3] / 400]
    assert body["highlights"][0]["bbox_normalized"] == pytest.approx(expected)
    image = client.get(body["image_url"])
    from hashlib import sha256

    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["etag"] == f'"{sha256(image.content).hexdigest()}"'
    assert sha256(image.content).hexdigest() == body["image_sha256"]
    assert "no-store" in image.headers["cache-control"]
    listed = client.get("/v1/runs").json()["items"][0]
    assert listed["result_url"] == done["result_url"]
    assert store.budget_totals() == before
    assert client.get(route(done), params={"source_id": str(uuid4())}).status_code == 404
    assert client.get(route(done), params={"claim_id": str(uuid4())}).status_code == 404
    mismatch = client.get(route(done), params={"document_version_id": str(uuid4())})
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "SOURCE_REFERENCE_MISMATCH"
    assert client.get(route(done, page=1)).status_code == 404
    assert client.get(route(done, page=0)).status_code == 422
    assert client.get(route(done, "image"), params={"image_sha256": "0" * 64}).status_code == 409


def test_source_cross_tenant_and_revoked_membership(published):
    app, store, client, owner, done, _ = published
    other, _, _, _ = login(app, store)
    assert other.get(route(done)).status_code == 404
    assert other.get(route(done, "image")).status_code == 404
    assert TestClient(app).get(route(done)).status_code == 401
    session = store.sessions.get(client.cookies.get("__Host-proofops_session"))
    with store.transaction() as db:
        db.execute(
            "UPDATE memberships SET status='revoked' WHERE tenant_id=? AND user_id=?",
            (owner.tenant_id, session.user_sub),
        )
    assert client.get(route(done)).status_code == 404


def test_expiry_cache_and_purge_returns_410_only_to_tenant(published):
    app, store, client, owner, done, _ = published
    assert client.get(route(done)).status_code == 200
    now = time.time()
    with store.transaction() as db:
        db.execute("UPDATE documents SET expires=?", (now - 1,))
        db.execute("UPDATE deletion.source_retention SET expires=?", (now - 1,))
    assert client.get(route(done, "image")).status_code == 410
    store.maintain(now=now)
    assert not store.document_dir(owner.tenant_id, done["document_id"]).exists()
    assert client.get(route(done)).status_code == 410
    other, _, _, _ = login(app, store)
    assert other.get(route(done)).status_code == 404


def rewrite_result(store, owner, done, edit):
    path = store.document_dir(owner.tenant_id, done["document_id"]) / "analysis" / done["run_id"]
    with store.transaction() as db:
        revision = db.execute(
            "SELECT max(revision) FROM result_snapshots WHERE run_id=?", (done["run_id"],)
        ).fetchone()[0]
        file = path / f"result-{revision}.json"
        body = json.loads(file.read_bytes())
        edit(body["result"])
        content = json.dumps(body).encode()
        # A new immutable revision fixture; never change the old anchor.
        store._publish_snapshot(db, done["run_id"], path, content)


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r.update(verification_state="candidate"),
        lambda r: r.update(location_quality="unreadable"),
        lambda r: r.update(bbox=None),
        lambda r: r.update(bbox=[-1, 0, 20, 20]),
        lambda r: r.update(bbox=[20, 20, 10, 10]),
    ],
)
def test_unverified_or_invalid_ref_never_highlighted(published, edit):
    _, store, client, owner, done, result = published
    rewrite_result(store, owner, done, lambda result: edit(result["claims"][0]["source_refs"][0]))
    response = client.get(route(done))
    assert response.status_code == 200, response.text
    assert response.json()["highlights"] == []
    assert response.json()["message"] == "원문 미검증"


def test_tampered_source_and_version_ref_fail_closed_even_after_cache(published):
    _, store, client, owner, done, result = published
    assert client.get(route(done)).status_code == 200
    rewrite_result(
        store,
        owner,
        done,
        lambda result: result["claims"][0]["source_refs"][0].update(
            document_version_id=str(uuid4())
        ),
    )
    assert client.get(route(done)).json()["error"]["code"] == "SOURCE_REFERENCE_MISMATCH"
    rewrite_result(
        store,
        owner,
        done,
        lambda current: current["claims"][0]["source_refs"][0].update(
            document_version_id=result["claims"][0]["source_refs"][0]["document_version_id"]
        ),
    )
    original = store.document_dir(owner.tenant_id, done["document_id"]) / "original.pdf"
    original.chmod(0o600)
    original.write_bytes(b"corrupt")
    response = client.get(route(done, "image"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_INTEGRITY_UNAVAILABLE"


def test_concurrency_limit_and_delete_during_render(published, monkeypatch):
    from proofops_api import hosted_reads

    _, store, client, owner, done, _ = published
    hosted_reads.clear_source_cache()
    started, finish = Event(), Event()
    actual = hosted_reads.render

    def slow(*args):
        started.set()
        assert finish.wait(10)
        return actual(*args)

    monkeypatch.setattr(hosted_reads, "render", slow)
    with ThreadPoolExecutor(2) as pool:
        request = pool.submit(client.get, route(done))
        assert started.wait(10)
        busy = client.get(route(done))
        assert busy.status_code == 429 and busy.headers["retry-after"]
        store.delete_document(owner, done["document_id"], "pa6-delete-race-key", now=time.time())
        finish.set()
        assert request.result(timeout=20).status_code == 404


def test_cross_process_slot_rejects_before_render(published):
    import subprocess
    import sys

    _, store, client, _, done, _ = published
    command = [
        sys.executable,
        "-c",
        "import fcntl,sys; f=open(sys.argv[1],'a+b'); "
        "fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); sys.stdin.read()",
        str(store.root / "source-render.lock"),
    ]
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    ) as child:
        assert child.stdout.readline().strip() == "ready"
        try:
            assert client.get(route(done)).status_code == 429
        finally:
            child.communicate("", timeout=5)


def test_render_limits_and_sanitized_errors(tmp_path, monkeypatch):
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
    from proofops.domain.documents import PageGeometry
    from proofops_api.hosted_page_render import render
    from proofops_api.hosted_store import HostedError

    source = tmp_path / "large.pdf"
    writer = PdfWriter()
    writer.add_blank_page(1001, 600)
    writer.write(source)
    with pytest.raises(HostedError, match="SOURCE_RENDER_UNAVAILABLE"):
        render(source, 1, PageGeometry(1001, 600, 0, (0, 0, 1001, 600)), tmp_path)
    seen = []

    def timeout(command, work, env, profile):
        seen.append(profile)
        raise ParseFailure("PARSER_TIMEOUT")

    monkeypatch.setattr(OpenDataLoaderParser, "_execute", timeout)
    with pytest.raises(HostedError, match="SOURCE_RENDER_UNAVAILABLE"):
        render(source, 1, PageGeometry(1001, 600, 0, (0, 0, 1001, 600)), tmp_path)
    assert seen[0].timeout_seconds == 15
    assert seen[0].memory_bytes == 512 * 1024 * 1024
    assert seen[0].max_output_bytes == 16 * 1024 * 1024


def test_cache_capacity_expiry_and_tenant_keys(monkeypatch):
    from proofops_api import hosted_reads

    hosted_reads.clear_source_cache()
    monkeypatch.setattr(hosted_reads, "_CACHE_LIMIT", 8192)
    hosted_reads._cached(("tenant-a",), 100, 0, (b"png", {}))
    hosted_reads._cached(("tenant-b",), 100, 0, (b"png", {}))
    assert hosted_reads._cached(("tenant-a",), 100, 0) is None
    assert hosted_reads._cached(("tenant-b",), 100, 0)
    assert hosted_reads._cached(("tenant-b",), 100, 100) is None
    assert not hosted_reads._cache


def test_run_cursor_ties_filter_and_user_binding(published):
    app, store, client, owner, done, _ = published
    now = time.time()
    for i in range(2):
        store.create_run(owner, done["document_id"], [1], f"pa6-page-runs-{i:04d}", now=now)
    response = client.get("/v1/runs", params={"limit": 1, "document_id": done["document_id"]})
    first = response.json()
    cursor = first["next_cursor"]
    assert cursor
    other, _, _, _ = login(app, store, tenant=owner.tenant_id, role="reviewer")
    assert (
        other.get(
            "/v1/runs", params={"cursor": cursor, "document_id": done["document_id"]}
        ).status_code
        == 400
    )
    assert client.get("/v1/runs", params={"cursor": cursor}).status_code == 400
    seen = [first["items"][0]["run_id"]]
    while cursor:
        page = client.get(
            "/v1/runs", params={"cursor": cursor, "limit": 1, "document_id": done["document_id"]}
        ).json()
        seen.extend(r["run_id"] for r in page["items"])
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 3
    assert client.get("/v1/runs?limit=101").status_code == 422


def test_retention_migration_backfills_existing_runs(published):
    from proofops_api.hosted_store import HostedStore

    _, store, _, owner, done, _ = published
    with store.transaction() as db:
        db.execute("DROP TABLE deletion.source_retention")
    reopened = HostedStore(store.settings)
    with reopened.transaction() as db:
        row = db.execute(
            "SELECT * FROM deletion.source_retention WHERE tenant_id=? AND run_id=?",
            (owner.tenant_id, done["run_id"]),
        ).fetchone()
        assert row["document_id"] == done["document_id"]
        assert (
            row["expires"]
            == reopened._document(db, owner.tenant_id, done["document_id"])["expires"]
        )


def test_revocation_while_rendering_never_returns_page(published, monkeypatch):
    from proofops_api import hosted_reads

    _, store, client, owner, done, _ = published
    hosted_reads.clear_source_cache()
    session = store.sessions.get(client.cookies.get("__Host-proofops_session"))
    actual = hosted_reads.render

    def revoked(*args):
        with store.transaction() as db:
            db.execute(
                "UPDATE memberships SET status='revoked' WHERE tenant_id=? AND user_id=?",
                (owner.tenant_id, session.user_sub),
            )
        return actual(*args)

    monkeypatch.setattr(hosted_reads, "render", revoked)
    assert client.get(route(done)).status_code == 404
