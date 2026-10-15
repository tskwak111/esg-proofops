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

from proofops.application.analysis_profile import (
    S3_VERIFIED_READ_V13_POLICY,
    VERIFIED_READ_V2_POLICY,
    VERIFIED_READ_V3_POLICY,
    VERIFIED_READ_V4_POLICY,
    VERIFIED_READ_V5_POLICY,
    VERIFIED_READ_V6_POLICY,
    VERIFIED_READ_V7_POLICY,
    VERIFIED_READ_V8_POLICY,
    VERIFIED_READ_V9_POLICY,
    VERIFIED_READ_V10_POLICY,
    VERIFIED_READ_V11_POLICY,
    VERIFIED_READ_V12_POLICY,
)
from proofops.application.analysis_profile import VERIFIED_READ_POLICY as POLICY
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
        VERIFIED_READ_V4_POLICY["profile"],
        VERIFIED_READ_V5_POLICY["profile"],
        VERIFIED_READ_V6_POLICY["profile"],
        VERIFIED_READ_V7_POLICY["profile"],
        VERIFIED_READ_V8_POLICY["profile"],
        VERIFIED_READ_V9_POLICY["profile"],
        VERIFIED_READ_V10_POLICY["profile"],
        VERIFIED_READ_V11_POLICY["profile"],
        VERIFIED_READ_V12_POLICY["profile"],
        S3_VERIFIED_READ_V13_POLICY["profile"],
    )


def _execution_policy():
    for policy in (
        POLICY,
        VERIFIED_READ_V2_POLICY,
        VERIFIED_READ_V3_POLICY,
        VERIFIED_READ_V4_POLICY,
        VERIFIED_READ_V5_POLICY,
        VERIFIED_READ_V6_POLICY,
        VERIFIED_READ_V7_POLICY,
        VERIFIED_READ_V8_POLICY,
        VERIFIED_READ_V9_POLICY,
        VERIFIED_READ_V10_POLICY,
        VERIFIED_READ_V11_POLICY,
        VERIFIED_READ_V12_POLICY,
        S3_VERIFIED_READ_V13_POLICY,
    ):
        if os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") == policy["profile"]:
            return policy
    return None


def _parse_enabled():
    return _execution_policy() in (
        VERIFIED_READ_V3_POLICY,
        VERIFIED_READ_V4_POLICY,
        VERIFIED_READ_V5_POLICY,
        VERIFIED_READ_V6_POLICY,
        VERIFIED_READ_V7_POLICY,
        VERIFIED_READ_V8_POLICY,
        VERIFIED_READ_V9_POLICY,
        VERIFIED_READ_V10_POLICY,
        VERIFIED_READ_V11_POLICY,
        VERIFIED_READ_V12_POLICY,
        S3_VERIFIED_READ_V13_POLICY,
    )


def _parse_projection_pinned(reader_name, policy):
    from pathlib import Path

    from proofops.adapters.local import evidence_source_ocr_v1 as ev1
    from proofops.adapters.local import evidence_source_verification_v1 as base
    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

    if not _parse_enabled():
        return False
    if _execution_policy() in (
        VERIFIED_READ_V10_POLICY,
        VERIFIED_READ_V11_POLICY,
        VERIFIED_READ_V12_POLICY,
        S3_VERIFIED_READ_V13_POLICY,
    ):
        try:
            if reader_name.startswith("native:"):
                page_ocr_profile(policy["mode"], policy=policy, native=True)
                return True
            from proofops.adapters.local.evidence_source_policies import evidence_source_reader

            return evidence_source_reader(policy).__name__ == reader_name
        except (ValueError, KeyError, TypeError):
            return False
    if _execution_policy() == VERIFIED_READ_V9_POLICY:
        if reader_name == "native:upstage-ocr-page-v17":
            reader = page_ocr_profile("upstage-ocr-page-v17", policy=policy, native=True)
            return (
                policy == reader.native_policy()
                and sha256(Path(reader.__file__).read_bytes()).hexdigest()
                == VERIFIED_READ_V9_POLICY["v17_replay_sha256"]
            )
        from proofops.adapters.local import evidence_source_hx3

        if reader_name == evidence_source_hx3.__name__:
            return (
                policy == evidence_source_hx3.policy()
                and sha256(Path(base.__file__).read_bytes()).hexdigest()
                == "d006dd1f3534080ad947b28fbfbedd57e97580b67ea3bb397dbb403ce01b01f6"
            )
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

    if _execution_policy() == S3_VERIFIED_READ_V13_POLICY and receipt.get(
        "table_acquisition_holds"
    ):
        return None
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
            execution=_execution_policy(),
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
    return span_verified_graph(
        checked,
        tuple(getattr(graph, "verified_spans", ()) or ()) + refs,
        receipt["artifact_sha256"] if hx3 else canonical_hash(base),
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
            len(_results) > (_execution_policy() or POLICY)["max_entries"]
            or sum(map(len, _results.values())) > POLICY["max_bytes"]
        ):
            _results.popitem(last=False)


def _fresh_key(reader, policy, receipt, graph, source, refs, tenant_id):
    from pathlib import Path

    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    profile = policy.get("profile")
    registered = False
    if _execution_policy() in (
        VERIFIED_READ_V10_POLICY,
        VERIFIED_READ_V11_POLICY,
        VERIFIED_READ_V12_POLICY,
        S3_VERIFIED_READ_V13_POLICY,
    ):
        try:
            registered = reader is page_ocr_profile(profile, policy=policy)
        except ValueError:
            pass

    pinned_v9 = (
        _execution_policy()
        in (
            VERIFIED_READ_V4_POLICY,
            VERIFIED_READ_V5_POLICY,
            VERIFIED_READ_V6_POLICY,
            VERIFIED_READ_V7_POLICY,
            VERIFIED_READ_V8_POLICY,
            VERIFIED_READ_V9_POLICY,
            VERIFIED_READ_V10_POLICY,
        )
        and profile == "upstage-ocr-page-v9"
        and reader is page_ocr_profile(profile)
        and sha256(Path(reader.__file__).read_bytes()).hexdigest()
        == VERIFIED_READ_V4_POLICY["v9_replay_sha256"]
        and receipt.get("schema") == "claim_source_pb4_extension_v1"
    )
    pinned_v6 = (
        profile == "upstage-ocr-page-v6"
        and reader is page_ocr_profile(profile)
        and sha256(Path(upstage_ocr_profile.__file__).read_bytes()).hexdigest()
        == _OCR_REPLAY_TAIL_SHA256
    )
    pinned_v10 = (
        _execution_policy()
        in (
            VERIFIED_READ_V5_POLICY,
            VERIFIED_READ_V6_POLICY,
            VERIFIED_READ_V7_POLICY,
            VERIFIED_READ_V8_POLICY,
            VERIFIED_READ_V9_POLICY,
            VERIFIED_READ_V10_POLICY,
        )
        and profile == "upstage-ocr-page-v10"
        and reader is page_ocr_profile(profile)
        and sha256(Path(reader.__file__).read_bytes()).hexdigest()
        == VERIFIED_READ_V5_POLICY["v10_replay_sha256"]
        and receipt.get("schema") == "claim_source_pa9_extension_v1"
    )
    pinned_v11 = (
        _execution_policy()
        in (VERIFIED_READ_V6_POLICY, VERIFIED_READ_V7_POLICY, VERIFIED_READ_V8_POLICY)
        and profile == "upstage-ocr-page-v11"
        and reader is page_ocr_profile(profile)
        and sha256(Path(reader.__file__).read_bytes()).hexdigest()
        == VERIFIED_READ_V6_POLICY["v11_replay_sha256"]
        and receipt.get("schema") == "claim_source_k3_extension_v1"
    )
    pinned_v12 = (
        _execution_policy()
        in (VERIFIED_READ_V7_POLICY, VERIFIED_READ_V8_POLICY, VERIFIED_READ_V9_POLICY)
        and profile == "upstage-ocr-page-v12"
        and reader is page_ocr_profile(profile)
        and sha256(Path(reader.__file__).read_bytes()).hexdigest()
        == VERIFIED_READ_V7_POLICY["v12_replay_sha256"]
        and receipt.get("schema") == "claim_source_h1_extension_v1"
    )
    pinned_v13 = (
        _execution_policy() == VERIFIED_READ_V8_POLICY
        and profile == "upstage-ocr-page-v13"
        and reader is page_ocr_profile(profile)
        and sha256(Path(reader.__file__).read_bytes()).hexdigest()
        == VERIFIED_READ_V8_POLICY["v13_replay_sha256"]
        and receipt.get("schema") == "claim_source_k7_extension_v1"
    )
    pinned_v17 = (
        _execution_policy() == VERIFIED_READ_V9_POLICY
        and profile == "upstage-ocr-page-v17"
        and reader is page_ocr_profile(profile, policy=policy)
        and sha256(Path(reader.__file__).read_bytes()).hexdigest()
        == VERIFIED_READ_V9_POLICY["v17_replay_sha256"]
        and receipt.get("schema") == "claim_source_k7_extension_v1"
    )
    if (registered or pinned_v13 or pinned_v17) and (
        receipt.get("tenant_id") != tenant_id
        or graph.tenant_id != tenant_id
        or receipt.get("document_version_id") != graph.document_version_id
        or receipt.get("parse_manifest_id") != graph.parse_manifest_id
        or receipt.get("source_sha256") != sha256(source).hexdigest()
        or graph.source_sha256 != sha256(source).hexdigest()
        or receipt.get("graph_sha256") != canonical_hash(asdict(graph))
        or receipt.get("artifact_sha256")
        != canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
    ):
        return None
    if (
        not fresh_execution_enabled()
        or not (
            registered
            or pinned_v6
            or pinned_v9
            or pinned_v10
            or pinned_v11
            or pinned_v12
            or pinned_v13
            or pinned_v17
        )
        or reader.claim_source_policy() != policy
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


def _project_v9(checked, graph, discovery, tenant_id):
    """Exact tail of the byte-pinned v9 reader after whole fresh receipt equality.

    Keep the explicit failed-row downgrade and independently attested cells;
    a whole-table flag must never substitute for native row ownership.
    """
    return _project_owned_cells(checked, graph, discovery, tenant_id, failed_state="unverified")


def _project_owned_cells(checked, graph, discovery, tenant_id, *, failed_state):
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
                        replace(r, verification_state=failed_state)
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


def _transient(value):
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


def _cold_v11_replay(receipt, graph, source, discovery, tenant_id):
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


def _cold_v12_replay(receipt, graph, source, discovery, tenant_id):
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


def _cold_v13_replay(receipt, graph, source, discovery, tenant_id):
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


def replay_cached(
    *, reader_name, policy, receipt, graph, source, tenant_id, recompute, discovery=None
):
    if (
        _execution_policy() == S3_VERIFIED_READ_V13_POLICY
        and discovery is None
        and receipt.get("table_acquisition_holds")
    ):
        # D2 must replay its acquisition holds through its own reader every time.
        # Such failures cannot seed either a fresh projection or a whole-read cache.
        return recompute(receipt, graph, source, tenant_id=tenant_id)

    def read():
        if discovery is not None and (
            (
                _execution_policy() == VERIFIED_READ_V11_POLICY
                and policy.get("profile") == "upstage-ocr-page-v19"
            )
            or (
                _execution_policy() in (VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY)
                and policy.get("profile")
                in {"upstage-ocr-page-v19", "upstage-ocr-page-v20", "upstage-ocr-page-v21"}
            )
        ):
            from proofops.adapters.local.claim_source_policies import page_ocr_profile
            from proofops.adapters.local.claim_source_verification import discovery_refs
            from proofops.adapters.local.s2_reader_execution import reader_scope

            if _execution_policy() in (VERIFIED_READ_V12_POLICY, S3_VERIFIED_READ_V13_POLICY):
                from proofops.adapters.local.i21_reader_execution import reader_scope

            reader = page_ocr_profile(policy["profile"], policy=policy)
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
            result = _single_parse_replay(reader_name, policy, receipt, graph, source, tenant_id)
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

        if page_ocr_profile(policy["mode"], policy=policy, native=True).native_policy() != policy:
            raise ValueError("NATIVE_PARAGRAPH_POLICY_MISMATCH")
    from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES, page_ocr_profile
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile

    live_claim_policy = None
    profile = (policy or {}).get("profile", "")
    if fresh_execution_enabled() and (
        profile.startswith("upstage-ocr-page-") or profile in PAGE_OCR_PROFILES
    ):
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


def _single_parse_replay(reader_name, policy, receipt, graph, source, tenant_id):
    """Recompute every record once, then use the already checked projection.

    The v19 and I17 wrappers otherwise call their predecessor's replay after
    checking the entire outer receipt, repeating the same original-source proof.
    Restrict this execution change to those two shipped, registered readers.
    """
    from proofops.adapters.local import authorized_ocr_execution as execution
    from proofops.adapters.local import evidence_source_i17 as evidence
    from proofops.adapters.local.claim_source_policies import page_ocr_profile

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
