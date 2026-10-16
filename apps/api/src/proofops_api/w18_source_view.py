"""Opt-in, additive display coordinates. Never replay or modify decision policies."""

from __future__ import annotations

import fcntl
import json
import math
import sys
import time
from collections import OrderedDict
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Lock, Thread
from types import SimpleNamespace

from proofops.adapters.parsing.parser_artifacts import read_parser_json
from proofops.application.ingest.geometry import project_native_bbox
from proofops.domain.provenance import canonical_hash

W18_TIMEOUT_SECONDS = 6
W18_TOTAL_SECONDS = 8
W18_CACHE_BYTES = 32 * 1024 * 1024
W19_DISK_BYTES = 32 * 1024 * 1024  # Per document; removed with its retention purge.
W19_WARM_SECONDS = 120
_warm_lock = Lock()
_cache: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
_lock = Lock()


def _read_json(path):
    if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("unsafe artifact")
    content = path.read_bytes()
    return json.loads(content), sha256(content).hexdigest()


def _graph(path, row, doc, anchor, original):
    version, manifest_id, expected, _ = anchor
    if original:
        for name in ("c3-evidence.json", "c4-evidence.json"):
            if (path / name).is_file():
                evidence, _ = _read_json(path / name)
                if canonical_hash(evidence) != expected:
                    raise ValueError("evidence hash")
                graph = evidence["parser_artifact"]
                if graph["tenant_id"] != row["tenant_id"]:
                    raise ValueError("tenant")
                # C3/C4 keep the full graph; use only its selected source candidate.
                blocks = []
                for block in graph["blocks"]:
                    if type(block.get("winner")) is not int:
                        continue
                    candidate = block["candidates"][block["winner"]]
                    source = candidate["source"]
                    blocks.append(
                        dict(
                            source_id=block["source_id"],
                            kind=block["kind"],
                            page_num=source["physical_page"],
                            bbox=candidate["bbox"],
                            raw_text=source["raw_text"],
                        )
                    )
                break
        else:
            raise ValueError("missing graph")
        source_sha = doc["sha256"]
    else:
        directory = path / "parser-prepared" / row["tenant_id"] / version / manifest_id
        if directory.is_symlink():
            raise ValueError("unsafe graph")
        manifest, digest = _read_json(directory / "manifest.json")
        if digest != expected or manifest["tenant_id"] != row["tenant_id"]:
            raise ValueError("manifest hash")
        graph = read_parser_json(directory / "graph.json", manifest=manifest)
        blocks = graph["blocks"]
        source_sha = row["prepared_sha256"]
    if (graph["document_version_id"], graph["parse_manifest_id"], graph["source_sha256"]) != (
        version,
        manifest_id,
        source_sha,
    ):
        raise ValueError("graph scope")
    return {block["source_id"]: block for block in blocks}


def _box_valid(box, page):
    return (
        isinstance(box, list | tuple)
        and len(box) == 4
        and all(type(n) in (int, float) and math.isfinite(n) for n in box)
        and 0 <= box[0] < box[2] <= page["width_pt"]
        and 0 <= box[1] < box[3] <= page["height_pt"]
    )


def _source(ref, block):
    if block is None or any(ref.get(k) != block.get(k) for k in ("source_id", "page_num", "bbox")):
        raise ValueError("source_binding_mismatch")
    text = block["raw_text"]
    start, end = ref.get("char_start"), ref.get("char_end")
    if (
        sha256(text.encode()).hexdigest() != ref.get("raw_text_sha256")
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or text[start:end] != ref.get("quote")
    ):
        raise ValueError("source_offset_mismatch")
    return text


def _lines(boxes):
    # Union only adjacent glyphs on the same row; never bridge a column gap.
    lines = []
    previous = None
    for box in boxes:
        if (
            previous is None
            or box[0] < previous[0]
            or min(box[3], previous[3]) <= max(box[1], previous[1])
            or box[0] - previous[2] > 2 * max(box[3] - box[1], previous[3] - previous[1])
        ):
            lines.append(list(box))
        else:
            prior = lines[-1]
            lines[-1] = [
                min(prior[0], box[0]),
                min(prior[1], box[1]),
                max(prior[2], box[2]),
                max(prior[3], box[3]),
            ]
        previous = box
    return lines


def _project_inventory(inventory, geometry, *, deadline=None):
    """Project each glyph once; keep the same affine arithmetic as W18."""
    chars = []
    for offset, (char, index, native) in enumerate(inventory["chars"]):
        if deadline is not None and offset % 1024 == 0 and time.monotonic() >= deadline:
            raise ValueError("coordinate_timeout")
        bounds = project_native_bbox(native, geometry) if native is not None else None
        if bounds is not None:
            chars.append((char, index, bounds))
    return chars


def locate(ref, block, inventory, geometry, *, deadline=None, projected=None):
    """Bind exact parser offsets through a literal, unique full-source character map."""
    text = _source(ref, block)
    page = inventory["page"]
    if any(
        abs(page[k] - getattr(geometry, k)) > 0.01 for k in ("width_pt", "height_pt", "rotation")
    ) or any(abs(a - b) > 0.01 for a, b in zip(page["crop_box"], geometry.crop_box, strict=True)):
        raise ValueError("page_geometry_mismatch")
    if not _box_valid(block["bbox"], page):
        raise ValueError("source_geometry_unavailable")
    if block["kind"] == "table_cell":
        return None, [block["bbox"]]
    box = block["bbox"]
    chars = []
    if projected is None:
        projected = _project_inventory(inventory, geometry, deadline=deadline)
    for offset, (char, index, bounds) in enumerate(projected):
        if deadline is not None and offset % 1024 == 0 and time.monotonic() >= deadline:
            raise ValueError("coordinate_timeout")
        if (
            box[0] <= (bounds[0] + bounds[2]) / 2 <= box[2]
            and box[1] <= (bounds[1] + bounds[3]) / 2 <= box[3]
        ):
            chars.append((char, index, bounds))
    needle = "".join(c for c in text if not c.isspace())
    haystack = "".join(c[0] for c in chars)
    start = haystack.find(needle) if needle else -1
    if start < 0:
        raise ValueError("native_alignment_unavailable")
    if haystack.find(needle, start + 1) >= 0:
        raise ValueError("native_alignment_ambiguous")
    # Offset map is derived from the whole hash-bound source, not a guessed quote hit.
    offsets = [i for i, c in enumerate(text) if not c.isspace()]
    selected = [
        chars[start + i]
        for i, offset in enumerate(offsets)
        if ref["char_start"] <= offset < ref["char_end"]
    ]
    if not selected or any(not _box_valid(c[2], page) for c in selected):
        raise ValueError("glyph_geometry_unavailable")
    return _lines([c[2] for c in selected]), None


def _disk_inventory(directory, scope, page, doc, data=None):
    """Private, bounded, disposable pages; never an alternate source authority."""
    cache = directory / "w19-inventory"
    if cache.is_symlink():
        raise ValueError("unsafe inventory cache")
    binding = [*scope[1:], page]
    name = sha256(json.dumps(binding).encode()).hexdigest() + ".json"
    file = cache / name
    if data is None:
        if not file.exists():
            return None
        if file.stat().st_size > W19_DISK_BYTES:
            raise ValueError("inventory cache size")
        envelope, _ = _read_json(file)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), str):
            raise ValueError("inventory cache format")
        payload = envelope["payload"].encode()
        if (
            envelope["schema"] != 1
            or envelope["binding"] != binding
            or envelope["expires"] != doc["expires"]
            or time.time() >= envelope["expires"]
            or sha256(payload).hexdigest() != envelope["sha256"]
        ):
            raise ValueError("inventory cache binding")
        return payload
    if time.time() >= doc["expires"]:
        return None
    cache.mkdir(mode=0o700, exist_ok=True)
    payload = json.dumps(
        dict(
            schema=1,
            binding=binding,
            expires=doc["expires"],
            sha256=sha256(data).hexdigest(),
            payload=data.decode(),
        )
    ).encode()
    if len(payload) > W19_DISK_BYTES:
        return None
    # All writers hold w18-coordinates.lock, including background warmers.
    for abandoned in cache.glob(".page-*"):
        abandoned.unlink()  # Recover a writer interrupted before its atomic rename.
    entries = sorted(cache.glob("*.json"), key=lambda p: p.lstat().st_mtime)
    total = sum(p.lstat().st_size for p in entries)
    for entry in entries:
        if entry == file or total + len(payload) > W19_DISK_BYTES:
            total -= entry.lstat().st_size
            entry.unlink()
    with NamedTemporaryFile(dir=cache, prefix=".page-", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.flush()
            temporary.replace(file)
        finally:
            temporary.unlink(missing_ok=True)
    return data


def _inventories(store, row, doc, pages, *, deadline=None):
    """Bounded child, durable tenant/SHA pages, exact original hash on every read."""
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure

    scope = (str(store.root), row["tenant_id"], row["document_id"], doc["sha256"])
    now = time.time()
    if now >= doc["expires"]:
        raise ValueError("original_integrity_unavailable")
    for key in list(_cache):
        if _cache[key][0] <= now:
            del _cache[key]
    found = {}
    directory = store.document_dir(row["tenant_id"], row["document_id"])
    profile = SimpleNamespace(
        timeout_seconds=min(W18_TIMEOUT_SECONDS, max(0.001, deadline - time.monotonic()))
        if deadline is not None
        else W18_TIMEOUT_SECONDS,
        memory_bytes=512 * 1024 * 1024,
        max_output_bytes=W18_CACHE_BYTES,
    )
    with (
        (directory / "analysis.lock").open("a+b") as lease,
        TemporaryDirectory(prefix=".w18-", dir=store.root) as temporary,
    ):
        fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        for page in pages:
            key = scope + (page,)
            try:
                data = (
                    _cache[key][1]
                    if key in _cache
                    else _disk_inventory(directory, scope, page, doc)
                )
                if data is not None:
                    found[page] = json.loads(data)
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Corrupt/old derived data is recomputed from authenticated PDF bytes.
        missing = sorted(pages - found.keys())
        work = Path(temporary)
        (work / "request.json").write_text(
            json.dumps(
                dict(source=str(directory / "original.pdf"), sha256=doc["sha256"], pages=missing)
            )
        )
        failure = "page_inventory_unavailable"
        try:
            OpenDataLoaderParser._execute(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("w18_glyph_worker.py")),
                    str(work),
                ],
                work,
                {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                profile,
            )
        except ParseFailure as exc:
            failure = (
                "coordinate_timeout"
                if str(exc) == "PARSER_TIMEOUT"
                else "page_inventory_unavailable"
            )
        if not (work / "verified.json").exists():
            # A deadline before SHA verification is retryable, never a cache admission.
            if failure == "coordinate_timeout":
                return {}, failure
            raise ValueError("original_integrity_unavailable")
        if time.time() >= doc["expires"]:
            raise ValueError("original_integrity_unavailable")
        for page in missing:
            file = work / f"page-{page}.json"
            if not file.is_file():
                continue
            try:
                data = file.read_bytes()
                found[page] = json.loads(data)
            except ValueError:
                continue
            _cache[scope + (page,)] = (doc["expires"], data)
            _cache.move_to_end(scope + (page,))
            try:
                _disk_inventory(directory, scope, page, doc, data)
            except (OSError, ValueError):
                pass  # A full/read-only cache must not discard valid in-flight coordinates.
        while len(_cache) > 64 or sum(len(v[1]) for v in _cache.values()) > W18_CACHE_BYTES:
            _cache.popitem(last=False)
    return found, failure


def _warm_pages(store, row, doc, pages):
    """One bounded background warmer; page-sized batches make durable progress."""
    stop = time.monotonic() + W19_WARM_SECONDS
    try:
        for page in sorted(pages):
            if time.monotonic() >= stop or time.time() >= doc["expires"]:
                break
            # Never hold a DB writer or recreate a deleted document directory.
            with _lock, (store.root / "w18-coordinates.lock").open("a+b") as lease:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _inventories(store, row, doc, {page}, deadline=stop)
    except (OSError, ValueError):
        pass  # A later read can retry; deletion/integrity failures remain closed.
    finally:
        _warm_lock.release()


def _schedule_warm(store, row, doc, pages):
    if not pages or not _warm_lock.acquire(blocking=False):
        return
    try:
        Thread(target=_warm_pages, args=(store, dict(row), dict(doc), pages), daemon=True).start()
    except RuntimeError:
        _warm_lock.release()


def enrich(reads, row, doc, requests):
    """Only add w18_* keys to newly created view refs; input snapshots are untouched."""
    deadline = time.monotonic() + W18_TOTAL_SECONDS
    pending = []
    graphs = {}
    retry_pages = set()
    for view, ref, path, anchor, original in requests:
        view.update(
            w18_line_rects=None,
            w18_cell_rects=None,
            w18_coordinates=None,
            w18_reason="source_unverified",
            w18_verification_state=ref.get("verification_state"),
        )
        if ref.get("verification_state") != "verified":
            continue
        view["w18_reason"] = "source_binding_unavailable"
        if anchor is None or view["location"] is None:
            continue
        if time.monotonic() >= deadline:
            view["w18_reason"] = "coordinate_timeout"
            retry_pages.add(view["physical_page"])
            continue
        try:
            key = (path, anchor[:3], original)
            if key not in graphs:
                graphs[key] = _graph(path, row, doc, anchor, original)
            block = graphs[key].get(ref["source_id"])
            _source(ref, block)
            pending.append((view, ref, block, anchor[3]))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            view["w18_reason"] = "source_offset_or_graph_mismatch"
    if not pending:
        _schedule_warm(reads.store, row, doc, retry_pages)
        return
    if not _lock.acquire(blocking=False):
        for view, *_ in pending:
            view["w18_reason"] = "coordinate_busy"
        return
    pages = {}
    try:
        with (reads.store.root / "w18-coordinates.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pages, reason = _inventories(
                reads.store, row, doc, {v[0]["physical_page"] for v in pending}, deadline=deadline
            )
        projected_pages = {}
        for view, ref, block, geometry in pending:
            try:
                if time.monotonic() >= deadline:
                    raise ValueError("coordinate_timeout")
                inventory = pages.get(view["physical_page"])
                if inventory is None:
                    raise ValueError(reason)
                # Geometry is part of the key: one anchor must never lend its transform
                # to a different parser page, even if both name the same physical page.
                key = (
                    view["physical_page"],
                    geometry.width_pt,
                    geometry.height_pt,
                    geometry.rotation,
                    tuple(geometry.crop_box),
                )
                if block["kind"] != "table_cell" and key not in projected_pages:
                    projected_pages[key] = _project_inventory(
                        inventory, geometry, deadline=deadline
                    )
                lines, cells = locate(
                    ref,
                    block,
                    inventory,
                    geometry,
                    deadline=deadline,
                    projected=projected_pages.get(key),
                )
                view.update(
                    w18_line_rects=lines,
                    w18_cell_rects=cells,
                    w18_reason=None,
                    w18_coordinates=dict(
                        page=asdict(geometry),
                        units="pdf_points",
                        origin="top_left",
                        space="rotated_cropbox_display",
                        bbox_format="x0,y0,x1,y1",
                        source_sha256=doc["sha256"],
                        physical_page=view["physical_page"],
                        char_start=ref["char_start"],
                        char_end=ref["char_end"],
                    ),
                )
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                view["w18_reason"] = (
                    str(exc) if isinstance(exc, ValueError) else "coordinate_unavailable"
                )
    except BlockingIOError:
        for view, *_ in pending:
            view["w18_reason"] = "coordinate_busy"
    except (OSError, ValueError):
        for view, *_ in pending:
            view["w18_reason"] = "original_integrity_or_reader_unavailable"
    finally:
        _lock.release()
    retry_pages = {
        view["physical_page"]
        for view, *_ in requests
        if view.get("w18_reason") == "coordinate_timeout" and view.get("location") is not None
    }
    _schedule_warm(reads.store, row, doc, retry_pages - pages.keys())
