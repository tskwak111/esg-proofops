"""Explicit read-only OS compatibility; byte-pinned verifiers stay unchanged.

All source/policy/graph gates still execute. An adjudicated stored receipt is
used only by a private replay function after a complete fresh comparison, so
historical span/artifact identities survive without rewriting stored bytes.
No reader output, OS string, canonical hash function or shared module is changed.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import OrderedDict
from contextvars import ContextVar
from copy import deepcopy
from threading import Lock
from types import FunctionType

from proofops.domain.provenance import canonical_hash

PROFILE = "receipt-env-drift-v1"
STRICT = "strict-v1"
PROFILE_ENV = "PROOFOPS_RECEIPT_READ_PROFILE"
# Apple Vision reports version AND build in this one field. Revision, compute,
# languages, reader versions, executable/policy hashes are deliberately absent.
ENVIRONMENT_FIELDS = frozenset({"os"})
_ATTESTERS = {
    "replay_native_sources": "attest_native_sources",
    "replay_tables": "attest_tables",
    "replay_claim_spans": "attest_claim_spans",
    "replay_render_resolution": "apply_render_resolution",
    "replay_bullet_alignment": "apply_bullet_alignment",
    "replay_claim_span_typography": "apply_claim_span_typography",
    "replay_context_cells": "attest_context_cells",
}
_DERIVED_FIELDS = frozenset(
    {
        "artifact_sha256",
        "reading_sha256",
        "rendered_read_sha256",
        "base_attestation_sha256",
        "baseline_attestation_sha256",
        "bullet_alignment_attestation_sha256",
    }
)
_meta: OrderedDict[tuple[str, str], dict] = OrderedDict()
_lock = Lock()
_table_read: ContextVar[tuple | None] = ContextVar("receipt_table_read", default=None)
_logger = logging.getLogger(__name__)
# Dedicated, metadata-only audit output survives the API's runtime formatter,
# which deliberately discards arbitrary logger messages. Never log OCR text.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_handler)
_logger.setLevel(logging.INFO)
_logger.propagate = False


def read_profile():
    profile = os.environ.get(PROFILE_ENV, STRICT)
    if profile not in {STRICT, PROFILE}:
        raise ValueError("RECEIPT_READ_PROFILE_UNKNOWN")
    return profile


def receipt_read_metadata(receipt, *, profile=None):
    """Process-local receipt sidecar, separate from the immutable artifact."""
    profile = read_profile() if profile is None else profile
    with _lock:
        value = _meta.get((profile, canonical_hash(receipt)))
        return deepcopy(value) if value is not None else None


def _layers(receipt):
    """Rebuild exact lower-layer preimages embedded by the existing wrappers."""
    common = {
        key: receipt[key]
        for key in (
            "tenant_id",
            "document_version_id",
            "parse_manifest_id",
            "source_sha256",
            "graph_sha256",
            "readings",
        )
    }
    schema = receipt["schema"]
    policy = receipt["policy"]
    if schema == "claim_span_typography_attestation_v1":
        lower = dict(
            common,
            schema="claim_span_bullet_alignment_attestation_v1",
            policy=policy["base"],
            records=receipt["bullet_alignment_records"],
            baseline_records=receipt["baseline_records"],
            base_records=receipt["base_records"],
            base_attestation_sha256=receipt["base_attestation_sha256"],
            baseline_attestation_sha256=receipt["baseline_attestation_sha256"],
            render_retries=receipt["render_retries"],
            bullet_alignments=receipt["bullet_alignments"],
        )
        yield "bullet_alignment_attestation_sha256", lower
        receipt, policy, schema = lower, lower["policy"], lower["schema"]
    if schema == "claim_span_bullet_alignment_attestation_v1":
        lower = dict(
            common,
            schema="claim_span_render_resolution_attestation_v1",
            policy=policy["base"],
            records=receipt["baseline_records"],
            base_records=receipt["base_records"],
            base_attestation_sha256=receipt["base_attestation_sha256"],
            render_retries=receipt["render_retries"],
        )
        yield "baseline_attestation_sha256", lower
        receipt, policy, schema = lower, lower["policy"], lower["schema"]
    if schema == "claim_span_render_resolution_attestation_v1":
        yield (
            "base_attestation_sha256",
            dict(
                common,
                schema="claim_source_attestation_v1",
                policy=policy["base"],
                records=receipt["base_records"],
            ),
        )


def _pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _derived_hashes(receipt):
    """Validate each digest against its own schema-bound preimage, even if equal.

    Paths, rather than a global set of digest values, bind the two receipts'
    corresponding references. A hash from an unrelated reading cannot qualify.
    """
    hashes = {}

    def bind(value, field, preimage, path):
        digest = canonical_hash(preimage)
        if value[field] != digest:
            raise ValueError("RECEIPT_DERIVED_HASH_MISMATCH")
        hashes[_pointer(path, field)] = digest

    def walk(value, path=""):
        if isinstance(value, dict):
            if "artifact_sha256" in value:
                bind(
                    value,
                    "artifact_sha256",
                    {k: v for k, v in value.items() if k != "artifact_sha256"},
                    path,
                )
            schema = value.get("schema")
            if schema in {
                "claim_span_render_resolution_attestation_v1",
                "claim_span_bullet_alignment_attestation_v1",
                "claim_span_typography_attestation_v1",
            }:
                for field, lower in _layers(value):
                    bind(value, field, lower, path)
            if "readings" in value:
                readings = value["readings"]
                for field in (
                    "records",
                    "base_records",
                    "baseline_records",
                    "bullet_alignment_records",
                ):
                    for index, record in enumerate(value.get(field, ())):
                        if "reading_sha256" in record:
                            source_id = record.get("ref", record).get("source_id")
                            bind(
                                record,
                                "reading_sha256",
                                readings[source_id],
                                _pointer(_pointer(path, field), index),
                            )
                if schema == "claim_span_typography_attestation_v1":
                    for index, entry in value["typography_reads"].items():
                        source_id = value["records"][int(index)]["ref"]["source_id"]
                        if entry["source_id"] != source_id:
                            raise ValueError("RECEIPT_DERIVED_HASH_MISMATCH")
                        if entry["path"] == "bullet_alignment_rendered_read":
                            rendered = value["bullet_alignments"][source_id].get("rendered")
                        elif entry["path"] == "base_rendered_read":
                            rendered = readings[source_id].get("rendered")
                        elif entry["path"] == "no_rendered_read":
                            rendered = None
                        else:
                            raise ValueError("RECEIPT_DERIVED_HASH_MISMATCH")
                        if rendered is None:
                            if entry["rendered_read_sha256"] is not None:
                                raise ValueError("RECEIPT_DERIVED_HASH_MISMATCH")
                        else:
                            bind(
                                entry,
                                "rendered_read_sha256",
                                rendered,
                                _pointer(_pointer(path, "typography_reads"), index),
                            )
                if schema == "glyph_alignment_attestation_v1":
                    for index, entry in value["glyph_alignments"].items():
                        if "rendered_read_sha256" in entry:
                            source_id = value["records"][int(index)]["ref"]["source_id"]
                            bind(
                                entry,
                                "rendered_read_sha256",
                                readings[source_id]["rendered"],
                                _pointer(_pointer(path, "glyph_alignments"), index),
                            )
            for key, item in value.items():
                walk(item, _pointer(path, key))
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                walk(item, _pointer(path, index))

    try:
        walk(receipt)
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("RECEIPT_DERIVED_HASH_MISMATCH") from error
    return hashes


def compare_receipts(saved, current, *, profile=STRICT):
    """Accept exact receipts, or ONLY same-shaped Apple Vision OS value changes."""
    if profile not in {STRICT, PROFILE}:
        raise ValueError("RECEIPT_READ_PROFILE_UNKNOWN")
    old_hash, new_hash = canonical_hash(saved), canonical_hash(current)
    drift = []
    old_derived = _derived_hashes(saved)
    new_derived = _derived_hashes(current)
    if old_hash != new_hash:
        if profile == STRICT:
            raise ValueError("RECEIPT_CONTENT_MISMATCH")

        def compare(old, new, path=""):
            if isinstance(old, dict) and isinstance(new, dict):
                if old.keys() != new.keys():
                    raise ValueError("RECEIPT_CONTENT_MISMATCH")
                for key in old:
                    here = _pointer(path, key)
                    if canonical_hash(old[key]) == canonical_hash(new[key]):
                        continue
                    if (
                        key in ENVIRONMENT_FIELDS
                        and re.search(r"/(?:rendered|rendered_attempts/\d+)$", path)
                        and not any(part in path.split("/") for part in ("policy", "base"))
                        and old.get("reader") == "Apple Vision"
                        and old.get("status") == new.get("status") == "read"
                        and "image_sha256" in old
                        and isinstance(old[key], str)
                        and isinstance(new[key], str)
                    ):
                        drift.append(dict(path=here, stored=old[key], current=new[key]))
                    elif (
                        key in _DERIVED_FIELDS
                        and isinstance(old[key], str)
                        and isinstance(new[key], str)
                        and old_derived.get(here) == old[key]
                        and new_derived.get(here) == new[key]
                    ):
                        continue
                    else:
                        compare(old[key], new[key], here)
            elif isinstance(old, list | tuple) and isinstance(new, list | tuple):
                if len(old) != len(new):
                    raise ValueError("RECEIPT_CONTENT_MISMATCH")
                for index, (a, b) in enumerate(zip(old, new, strict=True)):
                    compare(a, b, path + "/" + str(index))
            elif canonical_hash(old) != canonical_hash(new):
                raise ValueError("RECEIPT_CONTENT_MISMATCH")

        compare(saved, current)
        if not drift:
            raise ValueError("RECEIPT_CONTENT_MISMATCH")
    metadata = dict(
        read_profile=profile,
        comparison_path="environment_drift" if drift else "strict",
        stored_receipt_sha256=old_hash,
        current_receipt_sha256=new_hash,
        environment_drift=drift,
    )
    with _lock:
        _meta[profile, old_hash] = metadata
        _meta.move_to_end((profile, old_hash))
        while len(_meta) > 256:
            _meta.popitem(last=False)
    # Uvicorn may disable existing loggers after the adapters were imported.
    _logger.disabled = False
    _logger.info(
        json.dumps(dict(event="receipt_read_compatibility", **metadata), ensure_ascii=False)
    )
    return deepcopy(metadata)


def replay_receipt(function, receipt, *args, profile=None, **kwargs):
    """Private replay binding; execute existing admission and promotion unchanged.

    The original attester recomputes from actual source bytes. Only AFTER the
    complete comparison succeeds does the replay tail use the historical receipt
    identity. The original global namespace, hash function and reader are intact.
    """
    profile = read_profile() if profile is None else profile
    if profile == STRICT:
        result = function(receipt, *args, **kwargs)
        compare_receipts(receipt, receipt, profile=profile)
        return result
    if profile != PROFILE:
        raise ValueError("RECEIPT_READ_PROFILE_UNKNOWN")
    namespace = function.__globals__.copy()
    bindings = {
        name: namespace[attester]
        for name, attester in _ATTESTERS.items()
        if name in namespace and attester in namespace
    }
    if not bindings:
        raise ValueError("RECEIPT_READ_REPLAY_UNSUPPORTED")
    # Clone only this module's functions. Imported readers keep their real policy
    # and __file__ bytes; no shared globals or frozen source files are rewritten.
    for name, value in list(namespace.items()):
        if isinstance(value, FunctionType) and value.__globals__ is function.__globals__:
            cloned = FunctionType(
                value.__code__, namespace, value.__name__, value.__defaults__, value.__closure__
            )
            cloned.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = cloned
    for name, attester in bindings.items():
        if _ATTESTERS[name] == "attest_context_cells":
            attester = _context_attester(attester, profile)

        def adjudicate(*a, _attester=attester, **kw):
            recomputed = _attester(*a, **kw)
            expected = recomputed[0] if isinstance(recomputed, tuple) else recomputed
            compare_receipts(receipt, expected, profile=profile)
            if isinstance(recomputed, tuple):
                # Fresh proof keeps its own complete hash and real OS-bound identities.
                # Read metadata travels separately through the receipt sidecar.
                return deepcopy(receipt), recomputed[1]
            return deepcopy(receipt)

        namespace[_ATTESTERS[name]] = adjudicate
    return namespace[function.__name__](receipt, *args, **kwargs)


def replay_raster_with_profile(function, *args, **kwargs):
    """Bind native replay in a private raster composition, retaining its policy bytes."""
    if read_profile() == STRICT:
        return function(*args, **kwargs)
    namespace = function.__globals__.copy()
    for name, value in list(namespace.items()):
        if isinstance(value, FunctionType) and value.__globals__ is function.__globals__:
            cloned = FunctionType(
                value.__code__, namespace, value.__name__, value.__defaults__, value.__closure__
            )
            cloned.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = cloned
    native = function.__globals__["replay_native_sources"]
    namespace["replay_native_sources"] = lambda *a, **kw: replay_receipt(native, *a, **kw)
    visibility = namespace.get("corroborate_native_visibility")
    if visibility is not None:
        namespace["corroborate_native_visibility"] = lambda *a, **kw: replay_raster_with_profile(
            visibility, *a, **kw
        )
    return namespace[function.__name__](*args, **kwargs)


def _context_attester(function, profile):
    """Revalidate the embedded header before preserving its historical identity."""
    namespace = function.__globals__.copy()
    original = namespace["_column_head_literals"]
    reader = namespace["v3"]

    def headers(receipt, graph, source, tenant_id):
        if receipt is None:
            return original(receipt, graph, source, tenant_id)
        current = reader.attest_tables(graph, source, tenant_id=tenant_id)
        compare_receipts(receipt, current, profile=profile)
        heads, _digest = original(current, graph, source, tenant_id)
        return heads, receipt["artifact_sha256"]

    namespace["_column_head_literals"] = headers
    cloned = FunctionType(
        function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__
    )
    cloned.__kwdefaults__ = function.__kwdefaults__
    return cloned


def record_table_read(receipt, graph):
    """Keep table read metadata request-local and bind it to this graph identity."""
    _table_read.set(
        (
            (graph.tenant_id, graph.document_version_id, graph.parse_manifest_id),
            receipt_read_metadata(receipt),
        )
    )


def table_read_metadata(graph):
    value = _table_read.get()
    identity = graph.tenant_id, graph.document_version_id, graph.parse_manifest_id
    return deepcopy(value[1]) if value is not None and value[0] == identity else None
