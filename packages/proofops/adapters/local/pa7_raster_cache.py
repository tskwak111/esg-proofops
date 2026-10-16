"""Scoped raw CPU OCR reuse; source approval stays in the unchanged v9 verifier."""

import json
import math
import os
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from multiprocessing import get_context
from pathlib import Path
from threading import Lock
from types import FunctionType, MethodType, SimpleNamespace
from zlib import compress, decompress

from proofops.adapters.local.local_raster_reader import LocalRasterReader
from proofops.adapters.local.worker_resources import enabled as resources_enabled
from proofops.adapters.local.worker_resources import ocr_workers, shared_ocr_pool
from proofops.application.analysis_profile import (
    VERIFIED_READ_V4_POLICY,
    VERIFIED_READ_V5_POLICY,
    VERIFIED_READ_V6_POLICY,
    VERIFIED_READ_V7_POLICY,
    VERIFIED_READ_V8_POLICY,
)
from proofops.domain.provenance import canonical_hash

_scope: ContextVar[tuple[str, str, str] | None] = ContextVar("pa7_raw_read_scope", default=None)
_pool: ContextVar[ProcessPoolExecutor | None] = ContextVar("w3_raw_read_pool", default=None)
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
        pool = _pool.get()
        if pool is None:
            result = super().read(page, box, padding_px=padding_px)
        else:
            # The frozen verifier reads padding 0 and 6 for each crop. PDFium is
            # isolated per process; never operate native PDF handles on threads.
            pending = getattr(self, "_parallel_reads", None)
            if pending is None:
                pending = self._parallel_reads = {}
            crop = (page.page_number, page.width, page.height, tuple(box))
            if crop not in pending:
                pending[crop] = {
                    padding: pool.submit(_raw_read, self.source, crop, padding)
                    for padding in (0, 6)
                }
            result = pending[crop][padding_px].result()
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


def _raw_read(source, crop, padding):
    # A two-run CPU8 host has four independent crop workers. Keep Tesseract from
    # spawning another full CPU pool per crop. This grants no source approval.
    os.environ["OMP_THREAD_LIMIT"] = str(VERIFIED_READ_V5_POLICY["raw_ocr_omp_threads"])
    number, width, height, box = crop
    page = SimpleNamespace(page_number=number, width=width, height=height)
    return LocalRasterReader(source).read(page, box, padding_px=padding)


@contextmanager
def bounded_reader(reader, *, tenant_id, run_id):
    """Clone only this instance's constructor binding; no frozen module mutation.

    All source/glyph/quantity/visibility and row/cell verification code, its
    globals and closure are unchanged. Only complete raw OCR reads can be reused.
    """
    instance = reader.for_run(run_id)
    original = instance._claim_receipt.__func__
    heading_wrapper = None
    if reader.PROFILE in ("upstage-ocr-page-v12", "upstage-ocr-page-v13"):
        from proofops.adapters.local.verified_read_cache import _execution_policy

        if (
            (
                not resources_enabled()
                and _execution_policy() not in (VERIFIED_READ_V7_POLICY, VERIFIED_READ_V8_POLICY)
            )
            or sha256(Path(reader.__file__).read_bytes()).hexdigest()
            != (
                VERIFIED_READ_V8_POLICY
                if reader.PROFILE.endswith("v13")
                else VERIFIED_READ_V7_POLICY
            )["v13_replay_sha256" if reader.PROFILE.endswith("v13") else "v12_replay_sha256"]
            or (
                reader.PROFILE.endswith("v13")
                and not resources_enabled()
                and _execution_policy() != VERIFIED_READ_V8_POLICY
            )
        ):
            raise ValueError("PA7_RASTER_READER_BINDING_MISMATCH")
        heading_wrapper = original
        from proofops.adapters.local import upstage_ocr_profile_v12

        original = super(upstage_ocr_profile_v12.Reader, instance)._claim_receipt.__func__
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
    if heading_wrapper is not None:
        # H1's exact heading/cell proof still runs. Its one super() dispatch is
        # bound to the same inherited proof with only raw OCR reads scoped.
        inherited = MethodType(function, instance)
        function = FunctionType(
            heading_wrapper.__code__,
            heading_wrapper.__globals__
            | dict(super=lambda: SimpleNamespace(_claim_receipt=inherited)),
            heading_wrapper.__name__,
            heading_wrapper.__defaults__,
            heading_wrapper.__closure__,
        )
        function.__kwdefaults__ = heading_wrapper.__kwdefaults__
    instance._claim_receipt = MethodType(function, instance)
    with scope(tenant_id, run_id, reader.claim_source_policy()):
        from proofops.adapters.local.verified_read_cache import _execution_policy

        if resources_enabled():
            token = _pool.set(shared_ocr_pool())
            try:
                yield instance
            finally:
                _pool.reset(token)
        elif _execution_policy() in (
            VERIFIED_READ_V5_POLICY,
            VERIFIED_READ_V6_POLICY,
            VERIFIED_READ_V7_POLICY,
            VERIFIED_READ_V8_POLICY,
        ):
            with ProcessPoolExecutor(
                max_workers=ocr_workers(),
                mp_context=get_context("spawn"),
            ) as pool:
                token = _pool.set(pool)
                try:
                    yield instance
                finally:
                    _pool.reset(token)
        else:
            yield instance


def attest(reader, graph, source, refs, *, tenant_id, run_id):
    with bounded_reader(reader, tenant_id=tenant_id, run_id=run_id) as instance:
        return instance.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
