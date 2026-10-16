"""Instance-private policy snapshots; all original proof code still executes.

Policies are immutable during one read. Recheck the entire public policy at both
boundaries; a changing reader/runtime fails closed instead of seeding a result.
No shared reader modules or persisted receipts are modified.
"""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import FunctionType, MethodType, SimpleNamespace

from proofops.domain.provenance import canonical_hash

_POLICIES = ("claim_source_policy", "reader_policy", "native_policy", "table_span_policy")


def _snapshot(function):
    value = function()
    return lambda: deepcopy(value)


def _bind(core, name):
    """Clone the two existing private method chains, preserving their closures."""
    parent = None
    for cls in reversed(type(core).__mro__):
        original = cls.__dict__.get(name)
        if not isinstance(original, FunctionType):
            continue
        namespace = original.__globals__.copy()
        if name == "_claim_receipt" and "LocalRasterReader" in namespace:
            from proofops.adapters.local.local_raster_reader import LocalRasterReader
            from proofops.adapters.local.pa7_raster_cache import ScopedRasterReader

            if namespace["LocalRasterReader"] is not LocalRasterReader:
                raise ValueError("S2_RASTER_READER_UNKNOWN")
            namespace["LocalRasterReader"] = ScopedRasterReader
        for key in _POLICIES:
            if callable(namespace.get(key)):
                namespace[key] = _snapshot(namespace[key])
        if parent is not None:
            namespace["super"] = lambda prior=parent: SimpleNamespace(**{name: prior})
        function = FunctionType(
            original.__code__,
            namespace,
            original.__name__,
            original.__defaults__,
            original.__closure__,
        )
        function.__kwdefaults__ = original.__kwdefaults__
        parent = MethodType(function, core)
    if parent is None:
        raise ValueError("S2_READER_METHOD_UNKNOWN")
    return parent


@contextmanager
def reader_scope(reader, *, run_id, tenant_id):
    """V21 execution only; registered source policies and receipts stay identical."""
    from proofops.application.analysis_profile import VERIFIED_READ_V12_POLICY

    if (
        reader.PROFILE
        not in {"upstage-ocr-page-v19", "upstage-ocr-page-v20", "upstage-ocr-page-v21"}
        or sha256(Path(__file__).read_bytes()).hexdigest()
        != VERIFIED_READ_V12_POLICY["policy_snapshot_sha256"]
    ):
        raise ValueError("S2_READER_EXECUTION_MISMATCH")
    before = canonical_hash(dict(claim=reader.claim_source_policy(), native=reader.native_policy()))
    instance = reader.for_run(run_id)
    core = (
        instance.previous.previous
        if reader.PROFILE == "upstage-ocr-page-v21"
        else instance.previous
    )
    modules = _bind(core, "_modules")
    core._claim_receipt = _bind(core, "_claim_receipt")

    def prepared(*a, **k):
        private, seen = modules(*a, **k)
        for module in private.values():
            for key in _POLICIES:
                function = getattr(module, key, None)
                if callable(function):
                    setattr(module, key, _snapshot(function))
        return private, seen

    core._modules = prepared
    from proofops.adapters.local import pa7_raster_cache as raster
    from proofops.adapters.local.worker_resources import shared_ocr_pool

    try:
        with raster.scope(tenant_id, run_id, reader.claim_source_policy()):
            token = raster._pool.set(shared_ocr_pool())
            try:
                yield instance
            finally:
                raster._pool.reset(token)
    finally:
        after = canonical_hash(
            dict(claim=reader.claim_source_policy(), native=reader.native_policy())
        )
        if before != after:
            raise ValueError("S2_READER_POLICY_CHANGED")
