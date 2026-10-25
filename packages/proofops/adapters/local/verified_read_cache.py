"""Bounded, process-only reuse after an exact original-source recomputation.

The pickle bytes below are created here and retained only in this process. No
file, user-supplied serialization or persistent cache is ever deserialized.
"""

from __future__ import annotations

import os as os
import pickle
import sys as sys
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import asdict as asdict
from dataclasses import replace
from hashlib import sha256 as sha256
from threading import Lock
from typing import TYPE_CHECKING, TypedDict, cast, overload
from zlib import compress, decompress

from proofops.adapters.local.verified_read_cache_keys import (
    _execution_policy as _execution_policy,
)
from proofops.adapters.local.verified_read_cache_keys import (
    _fresh_key as _fresh_key,
)
from proofops.adapters.local.verified_read_cache_keys import (
    _parse_enabled as _parse_enabled,
)
from proofops.adapters.local.verified_read_cache_keys import (
    _parse_key as _parse_key,
)
from proofops.adapters.local.verified_read_cache_keys import (
    _parse_projection_pinned as _parse_projection_pinned,
)
from proofops.adapters.local.verified_read_cache_keys import (
    fresh_execution_enabled as fresh_execution_enabled,
)
from proofops.application import analysis_profile as _profiles
from proofops.domain.provenance import canonical_hash as canonical_hash
from proofops.domain.rulepacks import canonical_json

if TYPE_CHECKING:
    from types import ModuleType
    from typing import Any, Unpack

    from proofops.application.claims import ClaimDiscovery
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.domain.values import SourceRef


class ParseReplayArgs(TypedDict):
    reader_name: str
    policy: dict[str, Any]
    receipt: dict[str, Any]
    graph: CanonicalDocumentGraph
    source: bytes
    tenant_id: str


# Keep policy objects on the original module for callers and runtime patch hooks.
POLICY = _profiles.VERIFIED_READ_POLICY
S3_VERIFIED_READ_V13_POLICY = _profiles.S3_VERIFIED_READ_V13_POLICY
VERIFIED_READ_V2_POLICY = _profiles.VERIFIED_READ_V2_POLICY
VERIFIED_READ_V3_POLICY = _profiles.VERIFIED_READ_V3_POLICY
VERIFIED_READ_V4_POLICY = _profiles.VERIFIED_READ_V4_POLICY
VERIFIED_READ_V5_POLICY = _profiles.VERIFIED_READ_V5_POLICY
VERIFIED_READ_V6_POLICY = _profiles.VERIFIED_READ_V6_POLICY
VERIFIED_READ_V7_POLICY = _profiles.VERIFIED_READ_V7_POLICY
VERIFIED_READ_V8_POLICY = _profiles.VERIFIED_READ_V8_POLICY
VERIFIED_READ_V9_POLICY = _profiles.VERIFIED_READ_V9_POLICY
VERIFIED_READ_V10_POLICY = _profiles.VERIFIED_READ_V10_POLICY
VERIFIED_READ_V11_POLICY = _profiles.VERIFIED_READ_V11_POLICY
VERIFIED_READ_V12_POLICY = _profiles.VERIFIED_READ_V12_POLICY

_results: OrderedDict[str | None, bytes] = OrderedDict()
_inflight: dict[str, Future[bytes]] = {}
_lock = Lock()
_OCR_REPLAY_TAIL_SHA256 = "8d4b5caddb377ca1e9dc10998588449b85415aff6e4910372774d355db643102"


def remember_parse_attestation(**args: Unpack[ParseReplayArgs]) -> None:
    """Only the parser's freshly executed source reader can seed this entry."""
    if not _parse_enabled():
        return
    key = _parse_key(**args)
    if key is not None:
        encoded = compress(canonical_json(args["receipt"]).encode(), level=1)
        if len(encoded) <= cast("int", POLICY["max_bytes"]):
            _retain(key, encoded)


def _project_parse(
    receipt: dict[str, Any], graph: CanonicalDocumentGraph, *, native: bool
) -> CanonicalDocumentGraph:
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
    if receipt.get("schema") == "evidence_source_i17_attestation_v1":
        if receipt["source_sha256"] != graph.source_sha256:
            raise ValueError("EVIDENCE_SOURCE_MISMATCH")
        if "tables" not in receipt["base_receipt"] or receipt.get("scope", "").startswith(
            "empty-selection"
        ):
            return graph
        return _project_parse(receipt["base_receipt"], graph, native=False)
    hx3 = receipt.get("schema") in {
        "evidence_source_hx3_attestation_v1",
        "evidence_source_hx4_attestation_v1",
    }
    if hx3:
        base = receipt
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
    return_value: CanonicalDocumentGraph = span_verified_graph(
        checked,
        tuple(getattr(graph, "verified_spans", ()) or ()) + refs,
        receipt["artifact_sha256"] if hx3 else canonical_hash(base),
    )
    return return_value


def _fresh_parse_replay(**args: Unpack[ParseReplayArgs]) -> CanonicalDocumentGraph | None:
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


def _cold_evidence_replay(
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    tenant_id: str,
    original: Callable[..., CanonicalDocumentGraph | tuple[ClaimDiscovery, CanonicalDocumentGraph]],
) -> CanonicalDocumentGraph:
    from proofops.adapters.local import evidence_source_ocr_v1 as ev1

    if receipt.get("policy") != ev1.policy():
        raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
    reader = ev1.Reader(getattr(ev1, "v4").PageOCRStore.from_env(), run_id=receipt["run_id"])
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
        return cast("CanonicalDocumentGraph", original(receipt, graph, source, tenant_id=tenant_id))
    return _project_parse(expected, graph, native=False)


def _retain(key: str, encoded: bytes) -> None:
    with _lock:
        _results[key] = encoded
        _results.move_to_end(key)
        while len(_results) > cast("int", (_execution_policy() or POLICY)["max_entries"]) or sum(
            map(len, _results.values())
        ) > cast("int", POLICY["max_bytes"]):
            _results.popitem(last=False)


def remember_fresh_attestation(
    *,
    reader: ModuleType,
    policy: dict[str, Any],
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    refs: tuple[SourceRef, ...],
    tenant_id: str,
) -> None:
    """Called ONLY after the trusted reader just verified these original bytes.

    Keep the whole receipt, never stitch records or import a persisted cache.
    Fresh receipts and replay results share one four-entry / 32-MiB bound.
    """
    if not fresh_execution_enabled():
        return
    key = _fresh_key(reader, policy, receipt, graph, source, refs, tenant_id)
    if key is not None:
        encoded = compress(canonical_json(receipt).encode(), level=1)
        if len(encoded) <= cast("int", POLICY["max_bytes"]):
            _retain(key, encoded)


def reuse_fresh_attestation(
    *,
    reader: ModuleType,
    policy: dict[str, Any],
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    discovery: ClaimDiscovery,
    tenant_id: str,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph] | None:
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.native_replay_cache import _project_whole_attestation
    from proofops.adapters.local.receipt_environment_compat import (
        compare_receipts as _compare_receipts,
    )
    from proofops.adapters.local.receipt_environment_compat import read_profile as _read_profile

    compare_receipts: Callable[..., dict[str, Any]] = _compare_receipts
    read_profile: Callable[..., str] = _read_profile

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
    if policy.get("profile") == "upstage-ocr-page-v9":
        return _project_v9(receipt, graph, discovery, tenant_id)
    if _execution_policy() in (
        VERIFIED_READ_V10_POLICY,
        VERIFIED_READ_V11_POLICY,
        VERIFIED_READ_V12_POLICY,
        S3_VERIFIED_READ_V13_POLICY,
    ) or policy.get("profile") in (
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
        "upstage-ocr-page-v12",
        "upstage-ocr-page-v13",
        "upstage-ocr-page-v14",
        "upstage-ocr-page-v15",
        "upstage-ocr-page-v16",
        "upstage-ocr-page-v17",
    ):
        return _project_owned_cells(receipt, graph, discovery, tenant_id, failed_state="candidate")
    return _project_whole_attestation(receipt, graph, discovery, tenant_id, refs_field="records")


def _project_v9(
    checked: dict[str, Any],
    graph: CanonicalDocumentGraph,
    discovery: ClaimDiscovery,
    tenant_id: str,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph]:
    """Exact tail of the byte-pinned v9 reader after whole fresh receipt equality.

    Keep the explicit failed-row downgrade and independently attested cells;
    a whole-table flag must never substitute for native row ownership.
    """
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="unverified")


def _project_owned_cells(
    checked: dict[str, Any],
    graph: CanonicalDocumentGraph,
    discovery: ClaimDiscovery,
    tenant_id: str,
    *,
    failed_state: str,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph]:
    from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
    from proofops.domain.values import SourceRef

    approved = {
        (r["ref"]["source_id"], r["ref"]["char_start"], r["ref"]["char_end"])
        for r in checked["records"]
        if r["status"] == "verified"
    }
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in checked["records"]
        if r["status"] == "verified"
    )
    cells = tuple(
        replace(SourceRef(**c["source_ref"]), verification_state="verified")
        for p in checked["pb1_cell_proofs"]
        if p["status"] == "verified"
        for c in p["cell_proofs"]
        if not c.get("recovered_selection")
    )
    existing = tuple(getattr(graph, "verified_spans", ()))
    seen = {(r.source_id, r.char_start, r.char_end) for r in existing}
    scoped = span_verified_graph(
        graph,
        existing
        + tuple(r for r in (*newly, *cells) if (r.source_id, r.char_start, r.char_end) not in seen),
        checked["artifact_sha256"],
    )
    blocks = {b.source_id: b for b in graph.blocks}
    claims = []
    for claim in discovery.claims:
        table_claim = any(
            blocks[r.source_id].kind in {"table", "table_cell"} for r in claim.source_refs
        )
        if table_claim and not all(
            (r.source_id, r.char_start, r.char_end) in approved for r in claim.source_refs
        ):
            claims.append(
                replace(
                    claim,
                    source_quality="unverified"
                    if claim.source_quality == "verified"
                    else claim.source_quality,
                    source_refs=tuple(
                        replace(
                            r,
                            # Historical v9 also passes "unverified"; keep its projection unchanged.
                            verification_state=failed_state,  # type: ignore[arg-type]
                        )
                        if r.verification_state == "verified"
                        else r
                        for r in claim.source_refs
                    ),
                )
            )
            continue
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        sources = tuple(
            verify_source_ref(r, scoped, tenant_id=tenant_id) for r in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=sources)
            if sources and all(r.verification_state == "verified" for r in sources)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped


def _transient(value: object) -> bool:
    if isinstance(value, dict):
        reason = value.get("reason") or ""
        if "error" in value or reason in {
            "rendered_reader_unavailable",
            "render_limit",
            "local_raster_read_unresolved",
            "fallback_reader_unavailable",
            "ocr_reader_unavailable",
            "source_item_read_unresolved",
        }:
            return True
        return any(_transient(item) for item in value.values())
    return isinstance(value, list | tuple) and any(_transient(item) for item in value)


def _cold_v11_replay(
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    discovery: ClaimDiscovery,
    tenant_id: str,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph]:
    """Offline whole recomputation with two CPU workers; no new page OCR call."""
    from pathlib import Path

    from proofops.adapters.local import upstage_ocr_profile_v11 as reader
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.pa7_raster_cache import bounded_reader

    if (
        receipt.get("policy") != reader.claim_source_policy()
        or sha256(Path(reader.__file__).read_bytes()).hexdigest()
        != VERIFIED_READ_V6_POLICY["v11_replay_sha256"]
    ):
        raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
    with bounded_reader(reader, tenant_id=tenant_id, run_id=receipt["run_id"]) as instance:
        checked = instance.recompute_claim_receipt(
            receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
        )
    if canonical_hash(checked) != canonical_hash(receipt):
        raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="candidate")


def _cold_v12_replay(
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    discovery: ClaimDiscovery,
    tenant_id: str,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph]:
    """I5 offline whole recomputation with two CPU workers; no new page OCR call."""
    from pathlib import Path

    from proofops.adapters.local import upstage_ocr_profile_v12 as reader
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.pa7_raster_cache import bounded_reader

    if (
        receipt.get("policy") != reader.claim_source_policy()
        or sha256(Path(reader.__file__).read_bytes()).hexdigest()
        != VERIFIED_READ_V7_POLICY["v12_replay_sha256"]
    ):
        raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
    with bounded_reader(reader, tenant_id=tenant_id, run_id=receipt["run_id"]) as instance:
        checked = instance.recompute_claim_receipt(
            receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
        )
    if canonical_hash(checked) != canonical_hash(receipt):
        raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="candidate")


def _cold_v13_replay(
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    discovery: ClaimDiscovery,
    tenant_id: str,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph]:
    """S4 offline whole recomputation with two CPU workers; no new page OCR call."""
    from pathlib import Path

    from proofops.adapters.local import upstage_ocr_profile_v13 as reader
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.adapters.local.pa7_raster_cache import bounded_reader

    if (
        receipt.get("policy") != reader.claim_source_policy()
        or sha256(Path(reader.__file__).read_bytes()).hexdigest()
        != VERIFIED_READ_V8_POLICY["v13_replay_sha256"]
    ):
        raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
    with bounded_reader(reader, tenant_id=tenant_id, run_id=receipt["run_id"]) as instance:
        checked = instance.recompute_claim_receipt(
            receipt, graph, source, discovery_refs(discovery), tenant_id=tenant_id
        )
    if canonical_hash(checked) != canonical_hash(receipt):
        raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="candidate")


@overload
def replay_cached(
    *,
    reader_name: str,
    policy: dict[str, Any] | None,
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    tenant_id: str,
    recompute: Callable[..., CanonicalDocumentGraph],
    discovery: None = None,
) -> CanonicalDocumentGraph: ...


@overload
def replay_cached(
    *,
    reader_name: str,
    policy: dict[str, Any] | None,
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    tenant_id: str,
    recompute: Callable[..., tuple[ClaimDiscovery, CanonicalDocumentGraph]],
    discovery: ClaimDiscovery,
) -> tuple[ClaimDiscovery, CanonicalDocumentGraph]: ...


def replay_cached(
    *,
    reader_name: str,
    policy: dict[str, Any] | None,
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    tenant_id: str,
    recompute: Callable[
        ..., CanonicalDocumentGraph | tuple[ClaimDiscovery, CanonicalDocumentGraph]
    ],
    discovery: ClaimDiscovery | None = None,
) -> CanonicalDocumentGraph | tuple[ClaimDiscovery, CanonicalDocumentGraph]:
    if (
        _execution_policy() == S3_VERIFIED_READ_V13_POLICY
        and discovery is None
        and receipt.get("table_acquisition_holds")
    ):
        # D2 must replay its acquisition holds through its own reader every time.
        # Such failures cannot seed either a fresh projection or a whole-read cache.
        return recompute(receipt, graph, source, tenant_id=tenant_id)

    def read() -> CanonicalDocumentGraph | tuple[ClaimDiscovery, CanonicalDocumentGraph]:
        if discovery is not None and (
            (
                _execution_policy() == VERIFIED_READ_V11_POLICY
                and cast("dict[str, Any]", policy).get("profile") == "upstage-ocr-page-v19"
            )
            or (
                _execution_policy() in (VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY)
                and cast("dict[str, Any]", policy).get("profile")
                in {"upstage-ocr-page-v19", "upstage-ocr-page-v20", "upstage-ocr-page-v21"}
            )
        ):
            from proofops.adapters.local.claim_source_policies import (
                page_ocr_profile as _page_ocr_profile,
            )

            page_ocr_profile: Callable[..., ModuleType] = _page_ocr_profile
            from proofops.adapters.local.claim_source_verification import discovery_refs
            from proofops.adapters.local.s2_reader_execution import reader_scope

            if _execution_policy() in (VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY):
                from proofops.adapters.local.i21_reader_execution import reader_scope

            reader = page_ocr_profile(cast("dict[str, Any]", policy)["profile"], policy=policy)
            with reader_scope(reader, run_id=receipt["run_id"], tenant_id=tenant_id) as instance:
                checked = instance.recompute_claim_receipt(
                    receipt,
                    graph,
                    source,
                    discovery_refs(discovery),
                    tenant_id=tenant_id,
                )
            return _project_owned_cells(
                checked, graph, discovery, tenant_id, failed_state="candidate"
            )
        if (
            _execution_policy()
            in (VERIFIED_READ_V11_POLICY, VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY)
            and discovery is None
        ):
            result = _single_parse_replay(
                reader_name, cast("dict[str, Any]", policy), receipt, graph, source, tenant_id
            )
            if result is not None:
                return result
        if (
            _execution_policy() == VERIFIED_READ_V8_POLICY
            and discovery is not None
            and reader_name.endswith(".upstage_ocr_profile_v13")
        ):
            try:
                return _cold_v13_replay(receipt, graph, source, discovery, tenant_id)
            except ValueError as error:
                if str(error) not in {
                    "PA7_RASTER_READER_BINDING_MISMATCH",
                    "OCR_POLICY_OR_RUN_MISMATCH",
                }:
                    raise
                return recompute(receipt, graph, source, discovery, tenant_id=tenant_id)
        if (
            _execution_policy()
            in (VERIFIED_READ_V7_POLICY, VERIFIED_READ_V8_POLICY, VERIFIED_READ_V9_POLICY)
            and discovery is not None
            and reader_name.endswith(".upstage_ocr_profile_v12")
        ):
            return _cold_v12_replay(receipt, graph, source, discovery, tenant_id)
        if (
            _execution_policy()
            in (VERIFIED_READ_V6_POLICY, VERIFIED_READ_V7_POLICY, VERIFIED_READ_V8_POLICY)
            and discovery is not None
            and reader_name.endswith(".upstage_ocr_profile_v11")
        ):
            return _cold_v11_replay(receipt, graph, source, discovery, tenant_id)
        if (
            discovery is None
            and reader_name.endswith(".evidence_source_ocr_v1")
            and _parse_projection_pinned(reader_name, cast("dict[str, Any]", policy))
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
            policy=cast("dict[str, Any]", policy),
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
        from proofops.adapters.local.claim_source_policies import (
            page_ocr_profile as _page_ocr_profile,
        )

        page_ocr_profile: Callable[..., ModuleType] = _page_ocr_profile

        if (
            page_ocr_profile(
                cast("dict[str, Any]", policy)["mode"], policy=policy, native=True
            ).native_policy()
            != policy
        ):
            raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
    from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES
    from proofops.adapters.local.claim_source_policies import page_ocr_profile as _page_ocr_profile

    page_ocr_profile = cast("Callable[..., ModuleType]", _page_ocr_profile)
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile as _read_profile

    read_profile: Callable[..., str] = _read_profile

    live_claim_policy = None
    profile = (policy or {}).get("profile", "")
    if fresh_execution_enabled() and (
        profile.startswith("upstage-ocr-page-") or profile in PAGE_OCR_PROFILES
    ):
        live_claim_policy = page_ocr_profile(
            cast("dict[str, Any]", policy)["profile"]
        ).claim_source_policy()
    if _parse_enabled() and reader_name.endswith(".evidence_source_ocr_v1"):
        from proofops.adapters.local import evidence_source_ocr_v1

        live_claim_policy = evidence_source_ocr_v1.policy()
    key = canonical_hash(
        dict(
            tenant_id=tenant_id,
            reader=reader_name,
            policy=cast("dict[str, Any]", policy),
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
        return_value: CanonicalDocumentGraph | tuple[ClaimDiscovery, CanonicalDocumentGraph] = (
            pickle.loads(decompress(encoded))
        )
        return return_value
    # Every miss either joins an existing future or creates the owner future.
    assert future is not None
    if not owner:
        return_value = pickle.loads(decompress(future.result()))
        return return_value
    try:
        result = read()  # every admission/quantity/tenant/receipt guard runs cold
        encoded = compress(pickle.dumps(result, protocol=5), level=1)
        if (
            not _transient(receipt)
            and not _transient(result)
            and len(encoded) <= cast("int", POLICY["max_bytes"])
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


def _single_parse_replay(
    reader_name: str,
    policy: dict[str, Any],
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    tenant_id: str,
) -> CanonicalDocumentGraph | None:
    """Recompute every record once, then use the already checked projection.

    The v19 and I17 wrappers otherwise call their predecessor's replay after
    checking the entire outer receipt, repeating the same original-source proof.
    Restrict this execution change to those two shipped, registered readers.
    """
    from proofops.adapters.local import authorized_ocr_execution as execution
    from proofops.adapters.local import evidence_source_i17 as evidence
    from proofops.adapters.local.claim_source_policies import page_ocr_profile as _page_ocr_profile

    page_ocr_profile: Callable[..., ModuleType] = _page_ocr_profile

    if not _parse_projection_pinned(reader_name, policy):
        return None
    if reader_name == "native:upstage-ocr-page-v21" and (
        receipt.get("table_acquisition_holds")
        or (
            "policy_sha256" in receipt
            and receipt["policy_sha256"]
            != page_ocr_profile(policy["mode"], policy=policy, native=True).table_policy_sha256()
        )
    ):
        return None
    if (
        reader_name == "native:upstage-ocr-page-v19"
        or (
            _execution_policy() in (VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY)
            and reader_name == "native:upstage-ocr-page-v20"
        )
        or (
            _execution_policy() == S3_VERIFIED_READ_V13_POLICY
            and reader_name == "native:upstage-ocr-page-v21"
        )
    ):
        from proofops.adapters.local.s2_reader_execution import reader_scope

        if _execution_policy() in (VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY):
            from proofops.adapters.local.i21_reader_execution import reader_scope

        reader = page_ocr_profile(policy["mode"], policy=policy, native=True)
        with reader_scope(reader, run_id=receipt["run_id"], tenant_id=tenant_id) as instance:
            with execution.retained_collections(instance, receipt):
                if "policy_sha256" in receipt:
                    expected = instance.attest_tables(graph, source, tenant_id=tenant_id)
                else:
                    expected = instance.attest_native_sources(
                        graph,
                        source,
                        tenant_id=tenant_id,
                        geometry_mode=receipt.get("geometry_mode", "glyph"),
                    )
    elif reader_name == evidence.__name__:
        expected = evidence.attest_evidence_sources(
            graph,
            source,
            tenant_id=tenant_id,
            physical_pages=receipt.get("physical_pages"),
            run_id=receipt.get("run_id"),
        )
    else:
        return None
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("SOURCE_PARSE_RECEIPT_MISMATCH")
    remember_parse_attestation(
        reader_name=reader_name,
        policy=policy,
        receipt=expected,
        graph=graph,
        source=source,
        tenant_id=tenant_id,
    )
    return _project_parse(expected, graph, native=reader_name.startswith("native:"))
