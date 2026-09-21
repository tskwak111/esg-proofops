"""Bounded process-local reuse of successfully recomputed native receipts."""

import os
import sys
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
from json import dumps, loads
from marshal import dumps as marshal_dumps
from marshal import loads as marshal_loads
from threading import Lock
from zlib import compress, decompress

from proofops.adapters.local.run_artifacts import native_paragraph_policy
from proofops.adapters.local.source_verification import replay_native_sources
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

_replays: OrderedDict[str, frozenset[str]] = OrderedDict()
_raster_replays: OrderedDict[str, tuple[frozenset[str], str, str]] = OrderedDict()
_claim_replays: OrderedDict[str, tuple] = OrderedDict()
_claim_attestations: OrderedDict[str, bytes] = OrderedDict()
_lock = Lock()
_MAX_REPLAYS = 64
_MAX_CLAIM_ATTESTATION_BYTES = 64 * 1024 * 1024
# Projection below matches this reader's replay tail; other versions replay normally.
_CLAIM_PROJECTION_VERIFIER = "8b95383c73d76b2bf838e51f208448c8b1995271a6639e5726df659e7cef2a61"


def _claim_attestation_key(reader, policy, graph, source, tenant_id):
    return canonical_hash(
        dict(
            tenant_id=tenant_id,
            source_sha256=sha256(source).hexdigest(),
            graph=asdict(graph),
            policy=policy,
            reader=reader.__name__,
            platform=sys.platform,
            toolchain=os.environ.get("DEVELOPER_DIR"),
            readers=[version(name) for name in ("pdfplumber", "pdfminer.six", "pypdfium2")],
        )
    )


def _reusable_claim_record(record, receipt):
    return record["status"] == "verified" or (
        record["status"] == "unresolved"
        and record.get("reason") == "rendered_quote_unresolved"
        and receipt["readings"]
        .get(record["ref"]["source_id"], {})
        .get("rendered", {})
        .get("status")
        == "read"
    )


def _remember_claim_attestation(key, receipt):
    # Completed negative OCR is reusable as unresolved, never as evidence approval.
    records = [r for r in receipt["records"] if _reusable_claim_record(r, receipt)]
    sources = {r["ref"]["source_id"] for r in records}
    cached = dict(receipt, records=records, readings={s: receipt["readings"][s] for s in sources})
    # Internal process-only bytes; marshal retains tuple/list identity in native refs.
    encoded = compress(marshal_dumps(cached), level=1)
    with _lock:
        _claim_attestations.pop(key, None)
        # Share the former 8 x 8-MiB budget: full-report receipts can exceed 8 MiB.
        if records and len(encoded) <= _MAX_CLAIM_ATTESTATION_BYTES:
            _claim_attestations[key] = encoded
            while (
                len(_claim_attestations) > 8
                or sum(map(len, _claim_attestations.values())) > _MAX_CLAIM_ATTESTATION_BYTES
            ):
                _claim_attestations.popitem(last=False)


def attest_claims_cached(*, reader, graph, source, refs, tenant_id):
    """Compose unchanged reader records; re-read new refs, never infer verification."""
    refs = tuple(refs)
    key = _claim_attestation_key(reader, reader.claim_source_policy(), graph, source, tenant_id)
    with _lock:
        encoded = _claim_attestations.get(key)
        if encoded is not None:
            _claim_attestations.move_to_end(key)
    cached = marshal_loads(decompress(encoded)) if encoded is not None else None
    if cached is None:
        result = reader.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
    else:
        records = {canonical_hash(r["ref"]): r for r in cached["records"]}
        ref_keys = [canonical_hash(asdict(ref)) for ref in refs]
        missing = tuple(ref for ref, ref_key in zip(refs, ref_keys) if ref_key not in records)
        fresh = (
            reader.attest_claim_spans(graph, source, missing, tenant_id=tenant_id)
            if missing
            else cached
        )
        header = {
            k: v for k, v in cached.items() if k not in {"records", "readings", "artifact_sha256"}
        }
        same_header = header == {
            k: v for k, v in fresh.items() if k not in {"records", "readings", "artifact_sha256"}
        }
        same_readings = all(
            canonical_hash(reading) == canonical_hash(cached["readings"][source_id])
            for source_id, reading in fresh["readings"].items()
            if source_id in cached["readings"]
        )
        if not same_header or not same_readings:
            # A changed/unavailable reader must never inherit an older approval.
            result = reader.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        else:
            records.update((canonical_hash(r["ref"]), r) for r in fresh["records"])
            selected = [records[ref_key] for ref_key in ref_keys]
            readings = cached["readings"] | fresh["readings"]
            result = dict(
                header,
                records=selected,
                readings={
                    r["ref"]["source_id"]: readings[r["ref"]["source_id"]]
                    for r in selected
                    if "reading_sha256" in r
                },
            )
            result["artifact_sha256"] = canonical_hash(result)
    _remember_claim_attestation(key, result)
    return deepcopy(result)


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


def replay_raster_cached(
    snapshot, message, native, graph, source, registrations, receipts, *, native_policy=None
):
    """Reuse a completed v5 replay without relaxing its durable read checks."""
    from proofops.adapters.local.frozen_raster_replay import (
        raster_policy_requires_pinned_native,
        replay_raster_records_frozen,
    )
    from proofops.adapters.local.raster_checkpoint import replay_raster_records
    from proofops.adapters.local.raster_visibility import raster_ocr_policy

    policy = raster_ocr_policy(
        mode=snapshot["raster_ocr_policy"]["mode"],
        max_pages=snapshot["raster_ocr_policy"]["max_pages"],
        max_calls=snapshot["raster_ocr_policy"]["max_calls"],
    )
    frozen = raster_policy_requires_pinned_native(snapshot)
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
            "native_policy": native_policy if frozen else None,
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
        if frozen:
            composed, coverage, refs = replay_raster_records_frozen(
                snapshot, message, native, graph, source, registrations, receipts, native_policy
            )
        else:
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


def _project_attested_claims(expected, graph, discovery, tenant_id):
    """The pinned reader's deterministic replay tail, using its existing helpers."""
    from proofops.application.evidence import span_citations
    from proofops.domain.values import SourceRef

    refs = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
    )
    scoped = span_citations.span_verified_graph(graph, refs, expected["artifact_sha256"])
    claims = []
    for claim in discovery.claims:
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        checked = tuple(
            span_citations.verify_source_ref(ref, scoped, tenant_id=tenant_id)
            for ref in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=checked)
            if checked and all(ref.verification_state == "verified" for ref in checked)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped


def replay_claims_cached(*, reader, policy, receipt, graph, source, discovery, tenant_id):
    """Reuse a successful original-byte replay only for identical pinned inputs."""
    reader_policy = reader.claim_source_policy() if hasattr(reader, "claim_source_policy") else None
    key = canonical_hash(
        dict(
            tenant_id=tenant_id,
            source_sha256=sha256(source).hexdigest(),
            graph=asdict(graph),
            discovery=asdict(discovery),
            receipt=receipt,
            policy=policy,
            reader_policy=reader_policy,
            reader=reader.__name__,
            platform=sys.platform,
            toolchain=os.environ.get("DEVELOPER_DIR"),
            readers=[version(name) for name in ("pdfplumber", "pdfminer.six", "pypdfium2")],
        )
    )
    with _lock:
        cached = _claim_replays.get(key)
        if cached is not None:
            _claim_replays.move_to_end(key)
    if cached is None:
        from proofops.adapters.local import claim_source_verification

        if (
            reader is claim_source_verification
            and policy == reader_policy
            and policy.get("verifier_sha256") == _CLAIM_PROJECTION_VERIFIER
        ):
            expected = attest_claims_cached(
                reader=reader,
                graph=graph,
                source=source,
                refs=reader.discovery_refs(discovery),
                tenant_id=tenant_id,
            )
            if canonical_json(receipt) != canonical_json(expected):
                raise ValueError("CLAIM_SOURCE_RECEIPT_MISMATCH")
            result = _project_attested_claims(expected, graph, discovery, tenant_id)
        else:
            # ponytail: unknown/frozen readers keep their original replay implementation.
            result = reader.replay_claim_spans(
                receipt, graph, source, discovery, tenant_id=tenant_id
            )
        if receipt.get("schema") == "claim_source_attestation_v1":
            # Seed only after the original-byte replay accepted the entire receipt.
            attestation_key = _claim_attestation_key(reader, policy, graph, source, tenant_id)
            _remember_claim_attestation(attestation_key, receipt)
            if not all(_reusable_claim_record(r, receipt) for r in receipt["records"]):
                # Unavailable/error reads (and other unresolved guards) must retry.
                return deepcopy(result)
        cached = deepcopy(result)
        with _lock:
            _claim_replays[key] = cached
            _claim_replays.move_to_end(key)
            # Results include graphs; bound memory separately from small native ID sets.
            while len(_claim_replays) > 8:
                _claim_replays.popitem(last=False)
    return deepcopy(cached)
