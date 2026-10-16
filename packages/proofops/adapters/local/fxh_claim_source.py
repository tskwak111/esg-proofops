"""I24 proofs with instance-private policy snapshots and scoped raw OCR execution.

The three composed readers still execute every guard. D2 uses I21's execution
bindings; FXE reuses exact raw ROI reads. No historical module is changed.
"""

import json
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import FunctionType, MethodType, SimpleNamespace
from zlib import compress, decompress

from proofops.adapters.local import claim_source_fxe, source_fxe
from proofops.adapters.local import i21_reader_execution as execution
from proofops.adapters.local import i24_claim_source as previous
from proofops.adapters.local import pa7_raster_cache as raster
from proofops.adapters.local.worker_resources import shared_ocr_pool
from proofops.domain.provenance import canonical_hash

PROFILE = "fxh_claim_source_v1"
PageOCRStore = previous.PageOCRStore
native_policy = previous.native_policy
table_policy_sha256 = previous.table_policy_sha256
table_span_policy = previous.table_span_policy
attest_tables = previous.attest_tables
replay_tables = previous.replay_tables


def _fxe_raw_read(source, crop, padding):
    number, width, height, box = crop
    reader = source_fxe.RasterReader(source)
    try:
        return reader.read(
            SimpleNamespace(page_number=number, width=width, height=height),
            box,
            padding_px=padding,
        )
    finally:
        reader.close()


class _ScopedFXERaster(source_fxe.RasterReader):
    """Reuse only exact successful raw ROI reads; every source guard still runs."""

    def read(self, page, box, *, padding_px=0):
        bound = raster._scope.get()
        if (
            bound is None
            or self.visibility_hold
            or type(padding_px) is not int
            or padding_px not in (0, 6)
        ):
            return super().read(page, box, padding_px=padding_px)
        crop = (page.page_number, page.width, page.height, tuple(box))
        key = canonical_hash(
            dict(
                namespace="fxh-original-fxe-roi",
                scope=bound,
                source_sha256=sha256(self.source).hexdigest(),
                crop=crop,
                padding=padding_px,
                policy=source_fxe.policy(),
            )
        )
        with raster._lock:
            encoded = raster._reads.get(key)
            if encoded is not None:
                raster._reads.move_to_end(key)
        if encoded is not None:
            return json.loads(decompress(encoded))
        pool = raster._pool.get()
        if pool is None:
            result = super().read(page, box, padding_px=padding_px)
        else:
            pending = getattr(self, "_parallel_reads", None)
            if pending is None:
                pending = self._parallel_reads = {}
            if crop not in pending:
                pending[crop] = {
                    padding: pool.submit(_fxe_raw_read, self.source, crop, padding)
                    for padding in (0, 6)
                }
            result = pending[crop][padding_px].result()
        if result.get("status") == "read":
            encoded = compress(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
            with raster._lock:
                if len(encoded) + 1024 <= raster._MAX_BYTES:
                    raster._reads[key] = encoded
                    raster._reads.move_to_end(key)
                    while (
                        len(raster._reads) > raster._MAX_ENTRIES
                        or sum(len(v) + 1024 for v in raster._reads.values()) > raster._MAX_BYTES
                    ):
                        raster._reads.popitem(last=False)
        return result


def _clone(function, **bindings):
    cloned = FunctionType(
        function.__code__,
        function.__globals__ | bindings,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )
    cloned.__kwdefaults__ = function.__kwdefaults__
    return cloned


def claim_source_policy():
    return previous.claim_source_policy() | dict(
        profile=PROFILE,
        fxh_verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        fxh_execution_sha256=sha256(Path(execution.__file__).read_bytes()).hexdigest(),
        fxh_raster_sha256=sha256(Path(raster.__file__).read_bytes()).hexdigest(),
        fxh_admission="unchanged-i24-guards; instance-private-execution-only",
    )


class Reader:
    def __init__(self, *, run_id):
        self.run_id = run_id
        self.reader = previous.for_run(run_id)
        prose = SimpleNamespace(
            attest_claim_spans=_clone(
                claim_source_fxe.attest_claim_spans,
                source_fxe=SimpleNamespace(RasterReader=_ScopedFXERaster),
            )
        )
        fxe = self.reader.previous
        fxe.attest_claim_spans = MethodType(_clone(type(fxe).attest_claim_spans, prose=prose), fxe)
        # Rebind only the outer receipt's policy. The nested historical proofs
        # retain their original policies and exact full-receipt comparisons.
        for name in ("attest_claim_spans", "recompute_claim_receipt"):
            original = getattr(type(self.reader), name)
            namespace = original.__globals__ | dict(claim_source_policy=claim_source_policy)
            function = FunctionType(
                original.__code__,
                namespace,
                original.__name__,
                original.__defaults__,
                original.__closure__,
            )
            function.__kwdefaults__ = original.__kwdefaults__
            setattr(self.reader, name, MethodType(function, self.reader))
        core = self.reader
        # I24: FXF -> FXE -> FXG/native prose -> D2 -> private byte-pinned v21.
        for _ in range(8):
            if any("_modules" in cls.__dict__ for cls in type(core).__mro__):
                break
            core = core.previous
        else:
            raise ValueError("FXH_READER_CHAIN_MISMATCH")
        modules = execution._bind(core, "_modules")
        core._claim_receipt = execution._bind(core, "_claim_receipt")

        def prepared(*args, **kwargs):
            private, seen = modules(*args, **kwargs)
            for module in private.values():
                for key in execution._POLICIES:
                    function = getattr(module, key, None)
                    if callable(function):
                        setattr(module, key, execution._snapshot(function))
            return private, seen

        core._modules = prepared

    def __getattr__(self, name):
        return getattr(self.reader, name)

    @contextmanager
    def _scope(self, tenant_id):
        before = canonical_hash(claim_source_policy())
        with raster.scope(tenant_id, self.run_id, claim_source_policy()):
            token = raster._pool.set(shared_ocr_pool())
            try:
                yield
            finally:
                raster._pool.reset(token)
                if before != canonical_hash(claim_source_policy()):
                    raise ValueError("FXH_READER_POLICY_CHANGED")

    def attest_claim_spans(self, graph, source, refs, *, tenant_id, **kwargs):
        with self._scope(tenant_id):
            return self.reader.attest_claim_spans(
                graph, source, refs, tenant_id=tenant_id, **kwargs
            )

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        with self._scope(tenant_id):
            return self.reader.recompute_claim_receipt(
                receipt, graph, source, refs, tenant_id=tenant_id
            )


def for_run(run_id):
    return Reader(run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.verified_read_cache import _project_owned_cells

    checked = for_run(receipt["run_id"]).recompute_claim_receipt(
        receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
    )
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="candidate")
