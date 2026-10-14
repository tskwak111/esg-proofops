"""Preserve H7 proof semantics; larger hosted originals remain unverified."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import source_hx3
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.application.ingest.gri import _validate_graph
from proofops.application.input_failures import HOSTED_MAX_UPLOAD_BYTES
from proofops.domain.provenance import canonical_hash

# The private HX4 wrapper keeps empty-scope handling and adds HX3 item holds.
previous = _exec_private(
    Path(__file__).parent, "evidence_source_hx4.py", "proofops.adapters.local._i17_evidence"
)
_original_exec = previous._wrapper._exec_private


def _guarded_module(*args, **kwargs):
    module = _original_exec(*args, **kwargs)
    module._literal = source_hx3.hold_read(module._literal)
    return module


previous._wrapper._exec_private = _guarded_module

PROFILE = "evidence-source-i17-v1"
LEGACY_PROOF_BYTES = 100 * 1024 * 1024


def policy():
    return dict(
        previous.policy(),
        profile=PROFILE,
        previous_policy_sha256=canonical_hash(previous.policy()),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        max_input_bytes=HOSTED_MAX_UPLOAD_BYTES,
        max_verified_input_bytes=LEGACY_PROOF_BYTES,
        item_holds=source_hx3.policy(),
        admission="larger-originals-unresolved; no-proof-reader-limit-bypass",
    )


def attest_evidence_sources(graph, source, *, tenant_id, physical_pages=None, **kwargs):
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= HOSTED_MAX_UPLOAD_BYTES
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("EVIDENCE_SOURCE_MISMATCH")
    pages = (
        tuple(sorted({b.page_num for b in graph.blocks}))
        if physical_pages is None
        else tuple(physical_pages)
    )
    if tuple(sorted(set(pages))) != pages or any(type(p) is not int or p < 1 for p in pages):
        raise ValueError("EVIDENCE_PAGE_SELECTION_INVALID")
    base = (
        dict(
            input_graph_sha256=canonical_hash(asdict(graph)),
            source_sha256=graph.source_sha256,
            physical_pages=list(pages),
            records=[
                dict(source_id=b.source_id, status="unresolved", reason="SOURCE_PROOF_INPUT_LIMIT")
                for b in graph.blocks
                if b.page_num in pages
            ],
        )
        if len(source) > LEGACY_PROOF_BYTES
        else previous.attest_evidence_sources(
            graph, source, tenant_id=tenant_id, physical_pages=pages, **kwargs
        )
    )
    result = dict(
        base,
        schema="evidence_source_i17_attestation_v1",
        policy=policy(),
        base_receipt=base,
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        run_id=kwargs.get("run_id"),
    )
    result["artifact_sha256"] = canonical_hash(
        {k: v for k, v in result.items() if k != "artifact_sha256"}
    )
    return result


def replay_evidence_sources(receipt, graph, source, *, tenant_id):
    expected = attest_evidence_sources(
        graph,
        source,
        tenant_id=tenant_id,
        physical_pages=receipt.get("physical_pages"),
        run_id=receipt.get("run_id"),
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("EVIDENCE_SOURCE_RECEIPT_MISMATCH")
    if len(source) > LEGACY_PROOF_BYTES:
        return graph
    return previous.replay_evidence_sources(
        receipt["base_receipt"], graph, source, tenant_id=tenant_id
    )
