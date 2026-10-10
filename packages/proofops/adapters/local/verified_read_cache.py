"""Bounded, process-only reuse after an exact original-source recomputation.

The pickle bytes below are created here and retained only in this process. No
file, user-supplied serialization or persistent cache is ever deserialized.
"""

import os
import pickle
import sys
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import asdict
from hashlib import sha256
from threading import Lock
from zlib import compress, decompress

from proofops.application.analysis_profile import VERIFIED_READ_POLICY as POLICY
from proofops.domain.provenance import canonical_hash

_results: OrderedDict[str, bytes] = OrderedDict()
_inflight: dict[str, Future[bytes]] = {}
_lock = Lock()


def _transient(value):
    if isinstance(value, dict):
        reason = value.get("reason") or ""
        if "error" in value or reason in {
            "rendered_reader_unavailable",
            "render_limit",
            "local_raster_read_unresolved",
            "fallback_reader_unavailable",
            "ocr_reader_unavailable",
        }:
            return True
        return any(_transient(item) for item in value.values())
    return isinstance(value, list | tuple) and any(_transient(item) for item in value)


def replay_cached(
    *, reader_name, policy, receipt, graph, source, tenant_id, recompute, discovery=None
):
    def read():
        args = (receipt, graph, source) + ((discovery,) if discovery is not None else ())
        return recompute(*args, tenant_id=tenant_id)

    if os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") != POLICY["profile"]:
        return read()
    # Native OCR's resolver normally validates live reader bytes inside the cold
    # call. Keep that policy check on every warm hit as well.
    if reader_name.startswith("native:") and (policy or {}).get("mode", "").startswith(
        "upstage-ocr-page-"
    ):
        from proofops.adapters.local.claim_source_policies import page_ocr_profile

        if page_ocr_profile(policy["mode"]).native_policy() != policy:
            raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    key = canonical_hash(
        dict(
            tenant_id=tenant_id,
            reader=reader_name,
            policy=policy,
            receipt=receipt,
            graph=asdict(graph),
            discovery=asdict(discovery) if discovery is not None else None,
            source_sha256=sha256(source).hexdigest(),
            runtime=runtime_policy(),
            platform=sys.platform,
            toolchain=os.environ.get("DEVELOPER_DIR"),
            read_profile=read_profile(),
            execution=POLICY,
        )
    )
    with _lock:
        encoded = _results.get(key)
        if encoded is not None:
            _results.move_to_end(key)
        future = _inflight.get(key)
        owner = encoded is None and future is None
        if owner:
            future = Future()
            _inflight[key] = future
    if encoded is not None:
        return pickle.loads(decompress(encoded))
    if not owner:
        return pickle.loads(decompress(future.result()))
    try:
        result = read()  # every admission/quantity/tenant/receipt guard runs cold
        encoded = compress(pickle.dumps(result, protocol=5), level=1)
        if (
            not _transient(receipt)
            and not _transient(result)
            and len(encoded) <= POLICY["max_bytes"]
        ):
            with _lock:
                _results[key] = encoded
                while (
                    len(_results) > POLICY["max_entries"]
                    or sum(map(len, _results.values())) > POLICY["max_bytes"]
                ):
                    _results.popitem(last=False)
        future.set_result(encoded)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(key, None)
