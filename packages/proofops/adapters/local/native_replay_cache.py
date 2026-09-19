"""Bounded process-local reuse of successfully recomputed native receipts."""

import sys
from collections import OrderedDict
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
from json import dumps, loads
from threading import Lock

from proofops.adapters.local.run_artifacts import native_paragraph_policy
from proofops.adapters.local.source_verification import replay_native_sources
from proofops.domain.provenance import canonical_hash

_replays: OrderedDict[str, frozenset[str]] = OrderedDict()
_raster_replays: OrderedDict[str, tuple[frozenset[str], str, str]] = OrderedDict()
_lock = Lock()
_MAX_REPLAYS = 64


def replay_cached(receipt, graph, source, *, tenant_id):
    key = canonical_hash(
        dict(
            tenant_id=tenant_id,
            source_sha256=sha256(source).hexdigest(),
            graph_sha256=canonical_hash(asdict(graph)),
            receipt_sha256=canonical_hash(receipt),
            policy=native_paragraph_policy(),
            platform=sys.platform,
            readers=[version(name) for name in ("pdfplumber", "pdfminer.six", "pypdfium2")],
        )
    )
    with _lock:
        verified = _replays.get(key)
        if verified is not None:
            _replays.move_to_end(key)
    if verified is None:
        # ponytail: simultaneous cold reads may repeat OCR; coalesce only if measured.
        checked = replay_native_sources(receipt, graph, source, tenant_id=tenant_id)
        verified = frozenset(b.source_id for b in checked.blocks if b.quality == "verified")
        with _lock:
            _replays[key] = verified
            _replays.move_to_end(key)
            while len(_replays) > _MAX_REPLAYS:
                _replays.popitem(last=False)
    return replace(
        graph,
        blocks=tuple(
            replace(block, quality="verified") if block.source_id in verified else block
            for block in graph.blocks
        ),
    )


def replay_raster_cached(snapshot, message, native, graph, source, registrations, receipts):
    """Reuse a completed v5 replay without relaxing its durable read checks."""
    from proofops.adapters.local.raster_checkpoint import replay_raster_records
    from proofops.adapters.local.raster_visibility import raster_ocr_policy

    policy = raster_ocr_policy(
        mode=snapshot["raster_ocr_policy"]["mode"],
        max_pages=snapshot["raster_ocr_policy"]["max_pages"],
        max_calls=snapshot["raster_ocr_policy"]["max_calls"],
    )
    key = canonical_hash(
        {
            "snapshot": snapshot,
            "message": asdict(message),
            "graph_sha256": canonical_hash(asdict(graph)),
            "original_pdf_sha256": sha256(source).hexdigest(),
            "native_receipt_sha256": canonical_hash(native),
            "registrations_sha256": canonical_hash(registrations),
            "receipts_sha256": canonical_hash(receipts),
            "raster_policy": policy,
            "platform": sys.platform,
            "pdfminer_version": version("pdfminer.six"),
        }
    )
    with _lock:
        cached = _raster_replays.get(key)
        if cached is not None:
            _raster_replays.move_to_end(key)
    if cached is None:
        # ponytail: simultaneous cold reads may repeat replay; coalesce only if measured.
        composed, coverage, refs = replay_raster_records(
            snapshot, message, native, graph, source, registrations, receipts
        )
        cached = (
            frozenset(block.source_id for block in composed.blocks if block.quality == "verified"),
            dumps(coverage, sort_keys=True, separators=(",", ":")),
            dumps(refs, sort_keys=True, separators=(",", ":")),
        )
        with _lock:
            _raster_replays[key] = cached
            _raster_replays.move_to_end(key)
            while len(_raster_replays) > _MAX_REPLAYS:
                _raster_replays.popitem(last=False)
    verified, coverage, refs = cached
    return (
        replace(
            graph,
            blocks=tuple(
                replace(block, quality="verified") if block.source_id in verified else block
                for block in graph.blocks
            ),
        ),
        loads(coverage),
        loads(refs),
    )
