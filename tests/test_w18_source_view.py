"""W18 display-only offsets, real PDFium, immutable publication and private reads."""
# ruff: noqa: F811

import copy
import json
import time
from dataclasses import asdict
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from proofops.domain.documents import PageGeometry
from proofops_api import w18_source_view as w18
from proofops_api.hosted_reads import HostedReads
from proofops_api.hosted_source_view import project_source_view

from tests.test_hosted_analysis import source_pdf
from tests.test_hosted_public import login
from tests.test_pa6_reads import publication, published, settings  # noqa: F401


def fixture():
    geometry = PageGeometry(100, 100, 0, (0, 0, 100, 100))
    block = dict(
        source_id="block", page_num=1, bbox=[0, 0, 100, 100], raw_text="AB CD", kind="paragraph"
    )
    ref = {k: block[k] for k in ("source_id", "page_num", "bbox")}
    ref.update(quote="CD", char_start=3, char_end=5, raw_text_sha256=sha256(b"AB CD").hexdigest())
    inventory = dict(
        page=asdict(geometry),
        chars=[[c, i, [i * 10, 80, i * 10 + 5, 90]] for i, c in enumerate("ABCD")],
    )
    return ref, block, inventory, geometry


def test_exact_offsets_select_only_quote_not_paragraph_and_keep_input():
    args = fixture()
    before = copy.deepcopy(args)
    assert w18.locate(*args) == ([[20, 10, 35, 20]], None)
    assert args == before
    ref, block, inventory, geometry = args
    assert w18.locate(ref, block | dict(kind="table_cell"), inventory, geometry) == (
        None,
        [block["bbox"]],
    )


@pytest.mark.parametrize(
    "bad",
    [
        dict(char_start=2),
        dict(char_end=4),
        dict(quote="AB"),
        dict(raw_text_sha256="0" * 64),
        dict(page_num=2),
        dict(source_id="foreign"),
        dict(bbox=[1, 1, 2, 2]),
    ],
)
def test_changed_source_bindings_never_receive_coordinates(bad):
    ref, *rest = fixture()
    with pytest.raises(ValueError):
        w18.locate(ref | bad, *rest)


def test_ambiguous_missing_and_changed_codepoints_are_not_fuzzy_matches():
    ref, block, inventory, geometry = fixture()
    for chars in [
        inventory["chars"] * 2,
        inventory["chars"][:-1],
        [["a", *inventory["chars"][0][1:]], *inventory["chars"][1:]],
    ]:
        with pytest.raises(ValueError, match="native_alignment"):
            w18.locate(ref, block, inventory | dict(chars=chars), geometry)
    with pytest.raises(ValueError, match="page_geometry"):
        w18.locate(ref, block, inventory, PageGeometry(200, 100, 0, (0, 0, 200, 100)))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_shifted_crop_rotation_uses_native_glyph_transform_once(rotation):
    from proofops.application.ingest.geometry import project_native_bbox

    width, height = (100, 200) if rotation in (90, 270) else (200, 100)
    geo = PageGeometry(width, height, rotation, (50, 100, 250, 200))
    box = list(project_native_bbox((60, 120, 70, 130), geo))
    block = dict(source_id="s", page_num=1, raw_text="A", kind="paragraph", bbox=box)
    ref = block | dict(
        quote="A", char_start=0, char_end=1, raw_text_sha256=sha256(b"A").hexdigest()
    )
    inventory = dict(page=asdict(geo), chars=[["A", 0, [60, 120, 70, 130]]])
    assert w18.locate(ref, block, inventory, geo) == ([box], None)


def test_real_pdfium_page_cache_rechecks_sha_and_is_tenant_scoped(tmp_path):
    original = tmp_path / "original.pdf"
    content = source_pdf()
    original.write_bytes(content)
    store = SimpleNamespace(root=tmp_path, document_dir=lambda *_: tmp_path)
    row = dict(tenant_id="tenant-a", document_id="doc")
    doc = dict(sha256=sha256(content).hexdigest(), expires=time.time() + 60)
    w18._cache.clear()
    pages, _ = w18._inventories(store, row, doc, {1, 2})
    assert len(pages) == 2
    assert "Acme" in "".join(c[0] for c in pages[1]["chars"])
    warm, _ = w18._inventories(store, row, doc, {1, 2})
    assert pages == warm and len(w18._cache) == 2
    w18._inventories(store, row | dict(tenant_id="tenant-b"), doc, {1})
    assert len(w18._cache) == 3
    original.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="original_integrity"):
        w18._inventories(store, row, doc, {1})


def test_opt_in_http_exact_highlight_does_not_change_snapshot_or_auth(published):
    app, store, client, owner, done, stored = published
    path = store.document_dir(owner.tenant_id, done["document_id"]) / "analysis" / done["run_id"]
    before = {p.name: p.read_bytes() for p in path.glob("result-*.json")}
    route = f'/v1/runs/{done["run_id"]}/result'
    old = client.get(route).json()
    assert "w18_line_rects" not in old["claims"][0]["w16_source_view"]["refs"][0]
    response = client.get(route + "?w18=true")
    assert response.status_code == 200
    new = response.json()
    ref = new["claims"][0]["w16_source_view"]["refs"][0]
    assert ref["w18_line_rects"] and ref["w18_reason"] is None
    assert ref["w18_coordinates"]["physical_page"] == 2
    assert ref["w18_coordinates"]["source_sha256"] == new["w16_source_document"]["sha256"]
    assert ref["location"]["line_rects"] is None  # Actual W16 regression baseline.
    for claim in new["claims"]:
        for view in claim["w16_source_view"]["refs"]:
            for key in list(view):
                if key.startswith("w18_"):
                    del view[key]
    assert new == old
    assert before == {p.name: p.read_bytes() for p in path.glob("result-*.json")}
    assert TestClient(app).get(route + "?w18=true").status_code == 401
    other, *_ = login(app, store)
    assert other.get(route + "?w18=true").status_code == 404


def test_graph_tamper_and_unverified_ref_fail_closed(published):
    _, store, _, owner, done, stored = published
    with store.transaction(readonly=True) as db:
        row = store._run(db, owner.tenant_id, done["run_id"])
        doc = store._document(db, owner.tenant_id, done["document_id"])
    changed = copy.deepcopy(stored)
    changed["claims"][0]["source_refs"][0]["verification_state"] = "candidate"
    projected = project_source_view(HostedReads(store), row, doc, changed, w18=True)
    ref = projected["claims"][0]["w16_source_view"]["refs"][0]
    assert ref["w18_line_rects"] is None and ref["w18_reason"] == "source_unverified"
    path = store.document_dir(owner.tenant_id, done["document_id"]) / "analysis" / done["run_id"]
    graph = next(path.rglob("graph.json"))
    graph.chmod(0o600)
    raw = graph.read_bytes()
    try:
        graph.write_text(json.dumps({"blocks": []}))
        projected = project_source_view(HostedReads(store), row, doc, stored, w18=True)
        ref = projected["claims"][0]["w16_source_view"]["refs"][0]
        assert ref["w18_line_rects"] is None
        assert ref["w18_reason"] == "source_offset_or_graph_mismatch"
    finally:
        graph.write_bytes(raw)


def test_enrichment_budget_and_busy_admission_return_null_reasons(published, monkeypatch):
    _, store, _, owner, done, stored = published
    with store.transaction(readonly=True) as db:
        row = store._run(db, owner.tenant_id, done["run_id"])
        doc = store._document(db, owner.tenant_id, row["document_id"])
    reads = HostedReads(store)
    with monkeypatch.context() as patch:
        patch.setattr(w18, "W18_TOTAL_SECONDS", 0)
        result = project_source_view(reads, row, doc, stored, w18=True)
        ref = result["claims"][0]["w16_source_view"]["refs"][0]
        assert ref["w18_line_rects"] is None and ref["w18_reason"] == "coordinate_timeout"
    with w18._lock:
        result = project_source_view(reads, row, doc, stored, w18=True)
        ref = result["claims"][0]["w16_source_view"]["refs"][0]
        assert ref["w18_line_rects"] is None and ref["w18_reason"] == "coordinate_busy"
    changed = copy.deepcopy(stored)
    changed["claims"][0]["source_quality"] = "unverified"
    changed["claims"][0].pop("source_status", None)
    result = project_source_view(reads, row, doc, changed, w18=True)
    ref = result["claims"][0]["w16_source_view"]["refs"][0]
    assert ref["w18_line_rects"] is None and ref["w18_reason"] == "source_unverified"
