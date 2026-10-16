"""W16: actual HTTP bytes, private access, immutable result projections."""
# ruff: noqa: F811 -- imported pytest fixtures are injected as test parameters.

import copy
import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_reads import HostedReads
from proofops_api.hosted_source_view import project_source_view

from tests.test_hosted_public import actor, login, pdf
from tests.test_pa6_reads import publication, published, settings  # noqa: F401


def test_original_pdf_private_exact_bytes_range_and_auth(settings):
    app = create_hosted_app(settings)
    store = app.state.composition
    owner = actor(store)
    content = pdf()
    doc = store.upload(owner, content, "w16-original-upload", now=time.time())
    route = f'/v1/documents/{doc["document_id"]}/original'
    client, _, _, _ = login(app, store, tenant=owner.tenant_id, role="viewer")
    assert TestClient(app).get(route).status_code == 401
    other, _, _, _ = login(app, store)
    assert other.get(route).status_code == 404
    response = client.get(route)
    assert response.status_code == 200 and response.content == content
    assert response.headers["x-source-sha256"] == hashlib.sha256(content).hexdigest()
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment")
    part = client.get(route, headers={"Range": "bytes=4-13"})
    assert part.status_code == 206 and part.content == content[4:14]
    assert part.headers["content-range"] == f"bytes 4-13/{len(content)}"
    assert client.get(route, headers={"Range": "bytes=999999-"}).status_code == 416
    assert client.get(route + "?sha256=" + "0" * 64).status_code == 409
    assert not list(store.root.glob(".original-read-*"))


def test_original_tamper_symlink_and_expiry_fail_closed(settings, tmp_path):
    app = create_hosted_app(settings)
    store = app.state.composition
    owner = actor(store)
    doc = store.upload(owner, pdf(), "w16-tamper-upload01", now=time.time())
    client, _, _, _ = login(app, store, tenant=owner.tenant_id)
    route = f'/v1/documents/{doc["document_id"]}/original'
    source = store.document_dir(owner.tenant_id, doc["document_id"]) / "original.pdf"
    source.chmod(0o600)
    source.write_bytes(b"corrupted")
    assert client.get(route).status_code == 409
    source.unlink()
    target = tmp_path / "foreign.pdf"
    target.write_bytes(pdf())
    source.symlink_to(target)
    assert client.get(route).status_code == 409
    with store.transaction() as db:
        db.execute("UPDATE documents SET expires=0 WHERE document_id=?", (doc["document_id"],))
    assert client.get(route).status_code == 410
    assert not list(store.root.glob(".original-read-*"))


def test_original_membership_revocation_during_copy_returns_no_bytes(settings, monkeypatch):
    from proofops_api import hosted_source_view

    app = create_hosted_app(settings)
    store = app.state.composition
    owner = actor(store)
    doc = store.upload(owner, pdf(), "w16-revocation-001", now=time.time())
    client, _, _, user = login(app, store, tenant=owner.tenant_id)
    original_copy = hosted_source_view.copy_verified_file

    def revoked(*args):
        original_copy(*args)
        with store.transaction() as db:
            db.execute(
                "UPDATE memberships SET status='revoked' WHERE tenant_id=? AND user_id=?",
                (owner.tenant_id, user),
            )

    monkeypatch.setattr(hosted_source_view, "copy_verified_file", revoked)
    response = client.get(f'/v1/documents/{doc["document_id"]}/original')
    assert response.status_code == 404
    assert not response.content.startswith(b"%PDF")
    assert not list(store.root.glob(".original-read-*"))


def test_original_disconnect_cleans_private_copy(tmp_path):
    import asyncio
    from tempfile import TemporaryDirectory

    from proofops_api.hosted_source_view import _OriginalPdfResponse

    scratch = TemporaryDirectory(dir=tmp_path)
    source = Path(scratch.name) / "original.pdf"
    source.write_bytes(pdf())
    response = _OriginalPdfResponse(source, scratch=scratch)

    async def disconnected():
        return {"type": "http.disconnect"}

    async def failed_send(message):
        if message["type"] == "http.response.body":
            raise OSError("client disconnected after headers")

    with pytest.raises(OSError, match="disconnected"):
        asyncio.run(
            response({"type": "http", "method": "GET", "headers": []}, disconnected, failed_send)
        )
    assert not source.parent.exists()


def test_only_exact_hash_bound_receipt_glyphs_are_exposed(tmp_path):
    from proofops.domain.documents import PageGeometry
    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_source_view import _stored_glyphs

    ref = dict(source_id="source", quote="ISO 14001", page_num=36, bbox=[0, 0, 100, 20])
    glyphs = [[1, 2, 3, 4], [5, 2, 7, 4]]
    evidence = {
        "source_receipt": {
            "records": [
                {
                    "ref": ref,
                    "status": "verified",
                    "normalization": {
                        "source_sha256": "a" * 64,
                        "physical_page": 36,
                        "glyphs": [{"bbox": box} for box in glyphs],
                    },
                }
            ]
        }
    }
    (tmp_path / "c3-evidence.json").write_text(json.dumps(evidence))
    geometry = PageGeometry(200, 300, 0, (0, 0, 200, 300))
    args = (tmp_path, canonical_hash(evidence), ref, 36, "a" * 64, geometry)
    assert _stored_glyphs(*args) == glyphs
    assert _stored_glyphs(tmp_path, "b" * 64, *args[2:]) is None
    assert _stored_glyphs(*args[:2], ref | {"quote": "different"}, *args[3:]) is None
    assert _stored_glyphs(*args[:4], "b" * 64, geometry) is None


def test_multiline_highlight_is_a_union_of_stored_glyphs_not_paragraph_extent():
    from proofops_api.hosted_source_view import _glyph_lines

    boxes = [[50, 10, 55, 20], [60, 11, 65, 19], [10, 30, 15, 40], [20, 31, 25, 39]]
    assert _glyph_lines(boxes) == [[50, 10, 65, 20], [10, 30, 25, 40]]


def test_evidence_subspan_uses_only_receipt_character_map(tmp_path):
    from proofops.domain.documents import PageGeometry
    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_source_view import _stored_glyphs

    ref = dict(
        source_id="source",
        quote="AB CD",
        char_start=10,
        char_end=15,
        page_num=36,
        bbox=[0, 0, 100, 20],
    )
    glyphs = [dict(char=char, bbox=[i * 10, 1, i * 10 + 5, 8]) for i, char in enumerate("ABCD")]
    normalization = dict(
        source_sha256="a" * 64,
        physical_page=36,
        canonical_quote="AB CD",
        canonical_nonspace_offsets=[0, 1, 3, 4],
        glyphs=glyphs,
    )
    evidence = dict(
        source_receipt=dict(records=[dict(ref=ref, status="verified", normalization=normalization)])
    )
    file = tmp_path / "c3-evidence.json"
    file.write_text(json.dumps(evidence))
    child = ref | dict(quote="CD", char_start=13, char_end=15)
    geometry = PageGeometry(200, 300, 0, (0, 0, 200, 300))

    def read(candidate=child):
        return _stored_glyphs(tmp_path, canonical_hash(evidence), candidate, 36, "a" * 64, geometry)

    assert read() == [g["bbox"] for g in glyphs[2:]]
    assert read(child | dict(char_start=12)) is None
    assert read(child | dict(quote="AB")) is None
    normalization["canonical_nonspace_offsets"] = [0, 1, 2, 4]
    file.write_text(json.dumps(evidence))
    assert read() is None


def test_result_locations_are_additive_pinned_and_do_not_rewrite_snapshot(published):
    app, store, client, owner, done, stored = published
    path = store.document_dir(owner.tenant_id, done["document_id"]) / "analysis" / done["run_id"]
    before = {p.name: p.read_bytes() for p in path.glob("result-*.json")}
    route = f'/v1/runs/{done["run_id"]}/result'
    assert TestClient(app).get(route).status_code == 401
    other, _, _, _ = login(app, store)
    assert other.get(route).status_code == 404
    response = client.get(route)
    assert response.status_code == 200, response.text
    projected = response.json()
    for original, claim in zip(stored["claims"], projected["claims"], strict=True):
        assert {k: v for k, v in claim.items() if k != "w16_source_view"} == original
        assert claim["w16_source_view"]["quote"] == original["quote"]
    ref = projected["claims"][0]["w16_source_view"]["refs"][0]
    assert ref["physical_page"] == 2
    assert ref["location"]["bbox"] == stored["claims"][0]["source_refs"][0]["bbox"]
    assert ref["location"]["space"] == "rotated_cropbox_display"
    assert ref["location"]["page"]["width_pt"] == 600
    assert ref["location"]["line_rects"] is None
    assert client.get(projected["w16_source_document"]["url"]).status_code == 200
    assert before == {p.name: p.read_bytes() for p in path.glob("result-*.json")}


@pytest.mark.parametrize(
    "change",
    [
        {"bbox": None},
        {"bbox": [0, 0, float("nan"), 5]},
        {"bbox": [0, 0, 999999, 5]},
        {"verification_state": "candidate"},
        {"document_version_id": "foreign"},
        {"page_num": 99},
    ],
)
def test_unlocated_refs_remain_null_without_invented_coordinates(published, change):
    _, store, _, owner, done, stored = published
    changed = copy.deepcopy(stored)
    changed["claims"][0]["source_refs"][0].update(change)
    with store.transaction(readonly=True) as db:
        row = store._run(db, owner.tenant_id, done["run_id"])
        doc = store._document(db, owner.tenant_id, done["document_id"])
    result = project_source_view(HostedReads(store), row, doc, changed)
    assert result["claims"][0]["w16_source_view"]["refs"][0]["location"] is None


def test_frozen_publication_geometry_checks_hashes_without_policy_replay(tmp_path):
    import sqlite3

    from proofops.domain.provenance import canonical_hash
    from proofops_api.hosted_source_view import _publication_anchor

    graph = dict(
        tenant_id="tenant",
        document_version_id="version",
        parse_manifest_id="manifest",
        source_sha256="a" * 64,
        blocks=[
            dict(
                winner=0,
                candidates=[
                    dict(
                        source=dict(physical_page=36),
                        geometry=dict(
                            width_pt=800, height_pt=600, rotation=90, crop_box=[50, 100, 650, 900]
                        ),
                    )
                ],
            )
        ],
    )
    evidence = dict(parser_artifact=graph)
    frozen = dict(
        tenant_id="tenant",
        run_id="run",
        document=dict(version_id="version", sha256="a" * 64),
        c3_evidence_sha256=canonical_hash(evidence),
        analysis_profile_policy={"historical": True},
    )
    frozen["input_hash"] = canonical_hash(frozen)
    (tmp_path / "pilot.json").write_text(json.dumps(dict(tenant_id="tenant", run_id="run")))
    (tmp_path / "c3-evidence.json").write_text(json.dumps(evidence))
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        db.execute("CREATE TABLE run_snapshots (tenant_id TEXT,run_id TEXT,payload TEXT)")
        db.execute(
            "INSERT INTO run_snapshots VALUES (?,?,?)", ("tenant", "run", json.dumps(frozen))
        )
    args = (tmp_path, {"tenant_id": "tenant"}, {"sha256": "a" * 64}, 36)
    anchor = _publication_anchor(*args)
    assert anchor[:2] == ("version", "manifest")
    assert (anchor[3].width_pt, anchor[3].rotation) == (800, 90)
    with pytest.raises(ValueError):
        _publication_anchor(tmp_path, {"tenant_id": "foreign"}, args[2], 36)
    graph["blocks"][0]["candidates"][0]["geometry"]["width_pt"] = 999
    (tmp_path / "c3-evidence.json").write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="evidence hash"):
        _publication_anchor(*args)


def test_original_evidence_page_outside_claim_selection_is_preserved(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from proofops.domain.documents import PageGeometry
    from proofops_api import hosted_source_view

    reads = SimpleNamespace(store=SimpleNamespace(document_dir=lambda *args: tmp_path))
    row = dict(tenant_id="tenant", document_id="doc", run_id="run")
    doc = dict(page_count=119, sha256="a" * 64)
    ref = dict(
        source_id="source",
        quote="120",
        page_num=41,
        document_version_id="version",
        parse_manifest_id="manifest",
        bbox=[10, 20, 30, 40],
        verification_state="verified",
        location_quality="located",
    )
    result = dict(
        page_map=[36],
        claims=[
            dict(
                quote="claim p36",
                source_ref_page_space="original",
                source_refs=[],
                elements=[dict(element_id="P1", evidence_refs=[ref])],
            )
        ],
    )
    monkeypatch.setattr(
        hosted_source_view,
        "_publication_anchor",
        lambda *args: ("version", "manifest", "hash", PageGeometry(600, 800, 0, (0, 0, 600, 800))),
    )
    projected = project_source_view(reads, row, doc, result)
    evidence = projected["claims"][0]["w16_source_view"]["refs"][0]
    assert evidence["physical_page"] == 41 and evidence["location"]["bbox"] == ref["bbox"]
    ref["page_num"] = 120
    invalid = project_source_view(reads, row, doc, result)["claims"][0]["w16_source_view"]["refs"][
        0
    ]
    assert invalid["physical_page"] is None and invalid["location"] is None
