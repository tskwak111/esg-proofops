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
from proofops.application.analysis_profile import VERIFIED_READ_V2_POLICY
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

_results: OrderedDict[str, bytes] = OrderedDict()
_inflight: dict[str, Future[bytes]] = {}
_lock = Lock()
_OCR_REPLAY_TAIL_SHA256 = "8d4b5caddb377ca1e9dc10998588449b85415aff6e4910372774d355db643102"


def fresh_execution_enabled():
    return os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") == VERIFIED_READ_V2_POLICY["profile"]


def _retain(key, encoded):
    with _lock:
        _results[key] = encoded
        _results.move_to_end(key)
        while (
            len(_results) > POLICY["max_entries"]
            or sum(map(len, _results.values())) > POLICY["max_bytes"]
        ):
            _results.popitem(last=False)


def _fresh_key(reader, policy, receipt, graph, source, refs, tenant_id):
    from pathlib import Path

    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    if (
        not fresh_execution_enabled()
        or policy.get("profile") != "upstage-ocr-page-v6"
        or reader is not page_ocr_profile("upstage-ocr-page-v6")
        or reader.claim_source_policy() != policy
        or sha256(Path(upstage_ocr_profile.__file__).read_bytes()).hexdigest()
        != _OCR_REPLAY_TAIL_SHA256
        or receipt.get("policy") != policy
        or not receipt.get("run_id")
        or _transient(receipt)
        or canonical_hash([r["ref"] for r in receipt.get("records", [])])
        != canonical_hash([asdict(r) for r in refs])
    ):
        return None
    return "fresh:" + canonical_hash(
        dict(
            reader=reader.__name__,
            tenant_id=tenant_id,
            source_sha256=sha256(source).hexdigest(),
            graph=asdict(graph),
            receipt=receipt,
            refs=[asdict(r) for r in refs],
            policy=policy,
            runtime=runtime_policy(),
            read_profile=read_profile(),
            platform=sys.platform,
            toolchain=os.environ.get("DEVELOPER_DIR"),
            execution=VERIFIED_READ_V2_POLICY,
        )
    )


def remember_fresh_attestation(*, reader, policy, receipt, graph, source, refs, tenant_id):
    """Called ONLY after the trusted reader just verified these original bytes.

    Keep the whole receipt, never stitch records or import a persisted cache.
    Fresh receipts and replay results share one four-entry / 32-MiB bound.
    """
    if not fresh_execution_enabled():
        return
    key = _fresh_key(reader, policy, receipt, graph, source, refs, tenant_id)
    if key is not None:
        encoded = compress(canonical_json(receipt).encode(), level=1)
        if len(encoded) <= POLICY["max_bytes"]:
            _retain(key, encoded)


def reuse_fresh_attestation(*, reader, policy, receipt, graph, source, discovery, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.native_replay_cache import _project_whole_attestation
    from proofops.adapters.local.receipt_environment_compat import compare_receipts, read_profile

    if not fresh_execution_enabled():
        return None
    key = _fresh_key(reader, policy, receipt, graph, source, discovery_refs(discovery), tenant_id)
    with _lock:
        encoded = _results.get(key)
        if encoded is not None:
            _results.move_to_end(key)
    if encoded is None or decompress(encoded) != canonical_json(receipt).encode():
        return None
    compare_receipts(receipt, receipt, profile=read_profile())
    return _project_whole_attestation(receipt, graph, discovery, tenant_id, refs_field="records")


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

    execution = VERIFIED_READ_V2_POLICY if fresh_execution_enabled() else POLICY
    if os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") != execution["profile"]:
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

    live_claim_policy = None
    if fresh_execution_enabled() and (policy or {}).get("profile", "").startswith(
        "upstage-ocr-page-"
    ):
        from proofops.adapters.local.claim_source_policies import page_ocr_profile

        live_claim_policy = page_ocr_profile(policy["profile"]).claim_source_policy()
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
            execution=execution,
            **(dict(live_claim_policy=live_claim_policy) if fresh_execution_enabled() else {}),
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
            _retain(key, encoded)
        future.set_result(encoded)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(key, None)
