"""Scoped raw CPU OCR reuse; source approval stays in the unchanged v9 verifier."""

import json
import math
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
from threading import Lock
from types import FunctionType, MethodType
from zlib import compress, decompress

from proofops.adapters.local.local_raster_reader import LocalRasterReader
from proofops.application.analysis_profile import VERIFIED_READ_V4_POLICY
from proofops.domain.provenance import canonical_hash

_scope: ContextVar[tuple[str, str, str] | None] = ContextVar("pa7_raw_read_scope", default=None)
_reads: OrderedDict[str, bytes] = OrderedDict()
_lock = Lock()
_MAX_BYTES = VERIFIED_READ_V4_POLICY["raster_raw_reads"]["max_bytes"]
_MAX_ENTRIES = VERIFIED_READ_V4_POLICY["raster_raw_reads"]["max_entries"]


def clear():
    with _lock:
        _reads.clear()


@contextmanager
def scope(tenant, run, policy):
    token = _scope.set((tenant, run, canonical_hash(policy)))
    try:
        yield
    finally:
        _scope.reset(token)


class ScopedRasterReader(LocalRasterReader):
    def read(self, page, box, *, padding_px=0):
        bound = _scope.get()
        if bound is None or self.policy.get("status") != "ready":
            return super().read(page, box, padding_px=padding_px)
        try:
            if (
                not isinstance(self.source, bytes)
                or not 0 < len(self.source) <= 100 * 1024 * 1024
                or type(page.page_number) is not int
                or type(padding_px) is not int
                or padding_px not in (0, 6)
                or len(box) != 4
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in box)
            ):
                return super().read(page, box, padding_px=padding_px)
            key = canonical_hash(
                dict(
                    scope=bound,
                    source_sha256=sha256(self.source).hexdigest(),
                    page=page.page_number,
                    width=page.width,
                    height=page.height,
                    box=list(box),
                    padding_px=padding_px,
                    runtime=self.policy,
                    wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                )
            )
        except (AttributeError, TypeError, ValueError):
            return super().read(page, box, padding_px=padding_px)
        with _lock:
            encoded = _reads.get(key)
            if encoded is not None:
                _reads.move_to_end(key)
        if encoded is not None:
            return json.loads(decompress(encoded))
        result = super().read(page, box, padding_px=padding_px)
        if result.get("status") == "read":
            encoded = compress(
                json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), level=1
            )
            with _lock:
                if len(encoded) + 1024 <= _MAX_BYTES:
                    _reads[key] = encoded
                    _reads.move_to_end(key)
                    while (
                        len(_reads) > _MAX_ENTRIES
                        or sum(len(v) + 1024 for v in _reads.values()) > _MAX_BYTES
                    ):
                        _reads.popitem(last=False)
        return result


def attest(reader, graph, source, refs, *, tenant_id, run_id):
    """Clone only this instance's constructor binding; no frozen module mutation.

    All source/glyph/quantity/visibility and row/cell verification code, its
    globals and closure are unchanged. Only complete raw OCR reads can be reused.
    """
    instance = reader.for_run(run_id)
    original = instance._claim_receipt.__func__
    if original.__globals__.get("LocalRasterReader") is not LocalRasterReader:
        raise ValueError("PA7_RASTER_READER_BINDING_MISMATCH")
    function = FunctionType(
        original.__code__,
        original.__globals__ | dict(LocalRasterReader=ScopedRasterReader),
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    function.__kwdefaults__ = original.__kwdefaults__
    instance._claim_receipt = MethodType(function, instance)
    with scope(tenant_id, run_id, reader.claim_source_policy()):
        return instance.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
