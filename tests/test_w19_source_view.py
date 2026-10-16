"""W19 page reuse, durable inventory and retry regressions."""

import copy
import fcntl
import json
import time
from dataclasses import asdict
from hashlib import sha256
from threading import Event
from types import SimpleNamespace

import pytest
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
from proofops.domain.documents import PageGeometry
from proofops_api import w18_source_view as w18

from tests.test_hosted_analysis import TEXT, source_pdf
from tests.test_w18_source_view import fixture


def test_project_once_for_many_references(monkeypatch):
    ref, block, inventory, geometry = fixture()
    original = w18.project_native_bbox
    calls = []

    def project(box, geo):
        calls.append(box)
        return original(box, geo)

    monkeypatch.setattr(w18, "project_native_bbox", project)
    projected = w18._project_inventory(inventory, geometry)
    for _ in range(100):
        assert w18.locate(ref, block, inventory, geometry, projected=projected) == (
            [[20, 10, 35, 20]],
            None,
        )
    assert len(calls) == len(inventory["chars"])


@pytest.fixture
def document(tmp_path):
    content = source_pdf()
    (tmp_path / "original.pdf").write_bytes(content)
    store = SimpleNamespace(root=tmp_path, document_dir=lambda *_: tmp_path)
    row = dict(tenant_id="tenant-a", document_id="doc")
    doc = dict(sha256=sha256(content).hexdigest(), expires=time.time() + 3600)
    w18._cache.clear()
    return store, row, doc


def test_disk_survives_memory_eviction_and_300_seconds(document, monkeypatch):
    store, row, doc = document
    pages, _ = w18._inventories(store, row, doc, {1, 2})
    w18._cache.clear()
    real_time = time.time()
    monkeypatch.setattr(w18.time, "time", lambda: real_time + 301)
    execute = OpenDataLoaderParser._execute
    requested = []

    def record(command, work, env, profile):
        requested.append(json.loads((work / "request.json").read_bytes())["pages"])
        return execute(command, work, env, profile)

    monkeypatch.setattr(OpenDataLoaderParser, "_execute", record)
    assert w18._inventories(store, row, doc, {1, 2})[0] == pages
    assert requested == [[]]  # SHA is still checked by the child on every read.
    (store.root / "original.pdf").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="original_integrity"):
        w18._inventories(store, row, doc, {1, 2})


@pytest.mark.parametrize("mutation", ["tenant", "sha", "payload", "malformed"])
def test_disk_binding_tamper_is_recomputed(document, mutation):
    store, row, doc = document
    pages, _ = w18._inventories(store, row, doc, {1})
    file = next((store.root / "w19-inventory").glob("*.json"))
    envelope = json.loads(file.read_bytes())
    if mutation == "tenant":
        envelope["binding"][0] = "tenant-b"
    elif mutation == "sha":
        envelope["binding"][2] = "0" * 64
    elif mutation == "payload":
        envelope["payload"] = "{}"
    else:
        envelope["payload"] = []
    file.write_text(json.dumps(envelope))
    w18._cache.clear()
    assert w18._inventories(store, row, doc, {1})[0] == pages
    assert json.loads(file.read_bytes())["binding"] == [
        row["tenant_id"],
        row["document_id"],
        doc["sha256"],
        1,
    ]


def test_disk_rejects_cross_tenant_and_changed_sha(document):
    store, row, doc = document
    w18._inventories(store, row, doc, {1})
    scope = (str(store.root), row["tenant_id"], row["document_id"], doc["sha256"])
    assert w18._disk_inventory(store.root, (scope[0], "tenant-b", *scope[2:]), 1, doc) is None
    assert w18._disk_inventory(store.root, (*scope[:3], "0" * 64), 1, doc) is None


def test_disk_symlink_expiry_and_exclusive_lease_fail_closed(document, tmp_path):
    store, row, doc = document
    w18._inventories(store, row, doc, {1})
    with pytest.raises(ValueError, match="original_integrity"):
        w18._inventories(store, row, doc | dict(expires=time.time() - 1), {1})
    with (tmp_path / "analysis.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            w18._inventories(store, row, doc, {1})
    file = next((store.root / "w19-inventory").glob("*.json"))
    outside = tmp_path / "outside"
    outside.write_bytes(b"must not read or modify")
    file.unlink()
    file.symlink_to(outside)
    w18._cache.clear()
    assert w18._inventories(store, row, doc, {1})[0]
    assert outside.read_bytes() == b"must not read or modify"
    assert not file.is_symlink()


def test_disk_capacity_is_bounded(document, monkeypatch):
    store, row, doc = document
    w18._inventories(store, row, doc, {1})
    directory = store.root / "w19-inventory"
    first_size = next(directory.glob("*.json")).stat().st_size
    monkeypatch.setattr(w18, "W19_DISK_BYTES", first_size + 10)
    (directory / ".page-interrupted").write_bytes(b"x" * first_size)
    w18._inventories(store, row, doc, {2})
    assert sum(p.stat().st_size for p in directory.iterdir()) <= first_size + 10
    assert len(list(directory.iterdir())) == 1


def _requests():
    geometry = PageGeometry(600, 400, 0, (0, 0, 600, 400))
    blocks = {}
    requests = []
    for page in (1, 2):
        block = dict(
            source_id=str(page),
            page_num=page,
            raw_text=TEXT,
            bbox=[0, 0, 600, 400],
            kind="paragraph",
        )
        blocks[str(page)] = block
        ref = block | dict(
            quote=TEXT,
            char_start=0,
            char_end=len(TEXT),
            raw_text_sha256=sha256(TEXT.encode()).hexdigest(),
            verification_state="verified",
        )
        view = dict(physical_page=page, location=dict(page=asdict(geometry)))
        requests.append((view, ref, "graph-path", ("v", "m", "sha", geometry), False))
    return blocks, requests


def test_partial_timeout_background_finishes_and_retry_is_exact(document, monkeypatch):
    store, row, doc = document
    blocks, requests = _requests()
    monkeypatch.setattr(w18, "_graph", lambda *args: blocks)
    execute = OpenDataLoaderParser._execute
    calls = []
    warmed = Event()
    warm = w18._warm_pages

    def partial(command, work, env, profile):
        request = json.loads((work / "request.json").read_bytes())
        calls.append(request["pages"])
        if len(calls) == 1:
            assert request["pages"] == [1, 2]
            request["pages"] = [1]
            (work / "request.json").write_text(json.dumps(request))
            execute(command, work, env, profile)
            raise ParseFailure("PARSER_TIMEOUT")
        return execute(command, work, env, profile)

    def signal(*args):
        try:
            warm(*args)
        finally:
            warmed.set()

    monkeypatch.setattr(OpenDataLoaderParser, "_execute", partial)
    monkeypatch.setattr(w18, "_warm_pages", signal)
    reads = SimpleNamespace(store=store)
    w18.enrich(reads, row, doc, requests)
    assert requests[0][0]["w18_line_rects"]
    assert requests[1][0]["w18_reason"] == "coordinate_timeout"
    assert warmed.wait(15)
    before = copy.deepcopy(requests[0][0])
    w18._cache.clear()
    w18.enrich(reads, row, doc, requests)
    assert before == requests[0][0]
    assert all(v[0]["w18_line_rects"] and v[0]["w18_reason"] is None for v in requests)
    assert calls == [[1, 2], [2], []]


def test_zero_budget_still_schedules_and_lock_contention_is_retryable(document, monkeypatch):
    store, row, doc = document
    blocks, requests = _requests()
    monkeypatch.setattr(w18, "_graph", lambda *args: blocks)
    scheduled = []
    monkeypatch.setattr(w18, "_schedule_warm", lambda *args: scheduled.append(args[-1]))
    with monkeypatch.context() as patch:
        patch.setattr(w18, "W18_TOTAL_SECONDS", 0)
        w18.enrich(SimpleNamespace(store=store), row, doc, requests)
    assert scheduled == [{1, 2}]
    assert all(v[0]["w18_reason"] == "coordinate_timeout" for v in requests)
    with (store.root / "w18-coordinates.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        w18.enrich(SimpleNamespace(store=store), row, doc, requests)
    assert all(v[0]["w18_reason"] == "coordinate_busy" for v in requests)


def test_expiry_during_worker_never_publishes_cache(document, monkeypatch):
    store, row, doc = document
    execute = OpenDataLoaderParser._execute

    def expire(command, work, env, profile):
        execute(command, work, env, profile)
        doc["expires"] = time.time() - 1

    monkeypatch.setattr(OpenDataLoaderParser, "_execute", expire)
    with pytest.raises(ValueError, match="original_integrity"):
        w18._inventories(store, row, doc, {1})
    assert not w18._cache
    assert not (store.root / "w19-inventory").exists()


def test_background_admission_is_bounded_and_deleted_document_not_recreated(document, monkeypatch):
    store, row, doc = document
    started = []
    monkeypatch.setattr(
        w18, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: started.append(kwargs))
    )
    try:
        w18._schedule_warm(store, row, doc, {1})
        w18._schedule_warm(store, row, doc, {2})
        assert len(started) == 1
    finally:
        w18._warm_lock.release()
    missing = store.root / "deleted"
    store.document_dir = lambda *_: missing
    assert w18._warm_lock.acquire(blocking=False)
    w18._warm_pages(store, row, doc, {1})
    assert not missing.exists()
    assert not w18._warm_lock.locked()


def test_page_projection_reuse_does_not_bypass_per_reference_checks(monkeypatch):
    ref, block, inventory, geometry = fixture()
    projected = w18._project_inventory(inventory, geometry)
    for changed in [ref | dict(quote="AB"), ref | dict(raw_text_sha256="0" * 64)]:
        with pytest.raises(ValueError, match="source_offset_mismatch"):
            w18.locate(changed, block, inventory, geometry, projected=projected)
    with pytest.raises(ValueError, match="page_geometry_mismatch"):
        w18.locate(
            ref, block, inventory, PageGeometry(200, 100, 0, (0, 0, 200, 100)), projected=projected
        )
