"""Bounded, process-only reuse after an exact original-source recomputation.

The pickle bytes below are created here and retained only in this process. No
file, user-supplied serialization or persistent cache is ever deserialized.
"""

import os
import pickle
import sys
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import asdict, replace
from hashlib import sha256
from threading import Lock
from zlib import compress, decompress

from proofops.application.analysis_profile import VERIFIED_READ_POLICY as POLICY
from proofops.application.analysis_profile import VERIFIED_READ_V2_POLICY, VERIFIED_READ_V3_POLICY
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

_results: OrderedDict[str, bytes] = OrderedDict()
_inflight: dict[str, Future[bytes]] = {}
_lock = Lock()
_OCR_REPLAY_TAIL_SHA256 = "8d4b5caddb377ca1e9dc10998588449b85415aff6e4910372774d355db643102"


def fresh_execution_enabled():
    return os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") in (
        VERIFIED_READ_V2_POLICY["profile"],
        VERIFIED_READ_V3_POLICY["profile"],
    )


def _execution_policy():
    for policy in (POLICY, VERIFIED_READ_V2_POLICY, VERIFIED_READ_V3_POLICY):
        if os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") == policy["profile"]:
            return policy
    return None


def _parse_enabled():
    return _execution_policy() == VERIFIED_READ_V3_POLICY


def _parse_projection_pinned(reader_name, policy):
    from pathlib import Path

    from proofops.adapters.local import evidence_source_ocr_v1 as ev1
    from proofops.adapters.local import evidence_source_verification_v1 as base
    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

    if not _parse_enabled():
        return False
    if reader_name == "native:upstage-ocr-page-v6":
        return (
            policy == page_ocr_profile("upstage-ocr-page-v6").native_policy()
            and sha256(Path(upstage_ocr_profile.__file__).read_bytes()).hexdigest()
            == _OCR_REPLAY_TAIL_SHA256
        )
    return (
        reader_name == ev1.__name__
        and policy == ev1.policy()
        and sha256(Path(base.__file__).read_bytes()).hexdigest()
        == "d006dd1f3534080ad947b28fbfbedd57e97580b67ea3bb397dbb403ce01b01f6"
        and sha256(Path(ev1.__file__).read_bytes()).hexdigest()
        == "542c02413931bea2cb20e697664b5dcd504bc411b4dbcfcc1b9b4210695ade56"
    )


def _parse_key(*, reader_name, policy, receipt, graph, source, tenant_id):
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    if not _parse_projection_pinned(reader_name, policy) or _transient(receipt):
        return None
    if receipt.get("reader_policy" if reader_name.startswith("native:") else "policy") != policy:
        return None
    return "parse:" + canonical_hash(
        dict(
            reader=reader_name,
            policy=policy,
            receipt=receipt,
            graph=asdict(graph),
            source_sha256=sha256(source).hexdigest(),
            tenant_id=tenant_id,
            runtime=runtime_policy(),
            read_profile=read_profile(),
            platform=sys.platform,
            toolchain=os.environ.get("DEVELOPER_DIR"),
            execution=VERIFIED_READ_V3_POLICY,
        )
    )


def remember_parse_attestation(**args):
    """Only the parser's freshly executed source reader can seed this entry."""
    if not _parse_enabled():
        return
    key = _parse_key(**args)
    if key is not None:
        encoded = compress(canonical_json(args["receipt"]).encode(), level=1)
        if len(encoded) <= POLICY["max_bytes"]:
            _retain(key, encoded)


def _project_parse(receipt, graph, *, native):
    if native:
        members = {r["source_id"] for r in receipt["records"] if r["status"] == "verified"}
        return replace(
            graph,
            blocks=tuple(
                replace(b, quality="verified") if b.source_id in members else b
                for b in graph.blocks
            ),
        )
    from proofops.application.evidence.span_citations import span_verified_graph
    from proofops.domain.values import SourceRef

    # The frozen OCR wrapper projects its BASE receipt, not its outer receipt.
    # Restore the base identity lost when _finish_evidence added its metadata.
    base = {
        k: v
        for k, v in receipt.items()
        if k not in {"run_id", "page_collections", "rendered_reader_profile", "artifact_sha256"}
    }
    members = {sid for t in base["tables"] if t["status"] == "verified" for sid in t["member_ids"]}
    table_ids = {t["table_id"] for t in base["tables"] if t["status"] == "verified"}
    checked = replace(
        graph,
        blocks=tuple(
            replace(b, quality="verified") if b.source_id in members else b for b in graph.blocks
        ),
        issues=tuple(
            replace(
                i, state="resolved", reason="EV1 native/rendered grid checked; binding undetermined"
            )
            if i.kind == "table_vision_not_run" and i.source_ids and set(i.source_ids) <= table_ids
            else i
            for i in graph.issues
        ),
    )
    refs = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in base["records"]
        if r["kind"] == "paragraph" and r["status"] == "verified"
    )
    return span_verified_graph(
        checked, tuple(getattr(graph, "verified_spans", ()) or ()) + refs, canonical_hash(base)
    )


def _fresh_parse_replay(**args):
    key = _parse_key(**args)
    with _lock:
        encoded = _results.get(key)
        if encoded is not None:
            _results.move_to_end(key)
    if encoded is None or decompress(encoded) != canonical_json(args["receipt"]).encode():
        return None
    return _project_parse(
        args["receipt"], args["graph"], native=args["reader_name"].startswith("native:")
    )


def _cold_evidence_replay(receipt, graph, source, tenant_id, original):
    from proofops.adapters.local import evidence_source_ocr_v1 as ev1

    if receipt.get("policy") != ev1.policy():
        raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
    reader = ev1.Reader(ev1.v4.PageOCRStore.from_env(), run_id=receipt["run_id"])
    verifier, seen = reader._evidence_reader(
        graph, source, tenant_id, receipt.get("page_collections", [])
    )
    base = verifier.attest_evidence_sources(
        graph, source, tenant_id=tenant_id, physical_pages=receipt.get("physical_pages")
    )
    expected = reader._finish_evidence(dict(base), seen)
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("EVIDENCE_SOURCE_RECEIPT_MISMATCH")
    if _transient(expected):
        return original(receipt, graph, source, tenant_id=tenant_id)
    return _project_parse(expected, graph, native=False)


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
            execution=_execution_policy(),
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
        if (
            discovery is None
            and reader_name.endswith(".evidence_source_ocr_v1")
            and _parse_projection_pinned(reader_name, policy)
        ):
            return _cold_evidence_replay(receipt, graph, source, tenant_id, recompute)
        args = (receipt, graph, source) + ((discovery,) if discovery is not None else ())
        return recompute(*args, tenant_id=tenant_id)

    execution = _execution_policy()
    if execution is None:
        return read()
    if _parse_enabled() and discovery is None:
        fresh = _fresh_parse_replay(
            reader_name=reader_name,
            policy=policy,
            receipt=receipt,
            graph=graph,
            source=source,
            tenant_id=tenant_id,
        )
        if fresh is not None:
            return fresh
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
    if _parse_enabled() and reader_name.endswith(".evidence_source_ocr_v1"):
        from proofops.adapters.local import evidence_source_ocr_v1

        live_claim_policy = evidence_source_ocr_v1.policy()
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
