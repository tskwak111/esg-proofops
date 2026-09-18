"""Bounded process-local reuse of successfully recomputed native receipts."""

import sys
from collections import OrderedDict
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
from threading import Lock

from proofops.adapters.local.run_artifacts import native_paragraph_policy
from proofops.adapters.local.source_verification import replay_native_sources
from proofops.domain.provenance import canonical_hash

_replays: OrderedDict[str, frozenset[str]] = OrderedDict()
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
