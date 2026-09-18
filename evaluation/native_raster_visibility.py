"""Experimental composed visibility proof; not wired to published parser checkpoints.

Native text/geometry must already pass. Only readable OCR disagreement is eligible
for an independently pinned exact raster reading. This never approves semantics.
"""

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local.source_verification import replay_native_sources
from proofops.domain.provenance import canonical_hash

from evaluation.raster_ocr import replay_raster_ocr


def corroborate_native_visibility(
    native, request, receipt, graph, source, *, request_sha256, receipt_sha256, tenant_id
):
    if not isinstance(native, dict) or native.get("schema") != "native_paragraph_attestation_v2":
        raise ValueError("NATIVE_GLYPH_ATTESTATION_REQUIRED")
    baseline = replay_native_sources(native, graph, source, tenant_id=tenant_id)
    eligible = {
        row["source_id"]
        for row in native["records"]
        if row["status"] == "unresolved"
        and row["reason"] == "rendered_text_unresolved"
        and row.get("rendered", {}).get("status") == "read"
        and row["rendered"].get("text", "").strip()
    }
    readings = replay_raster_ocr(
        request,
        receipt,
        graph,
        source,
        request_sha256=request_sha256,
        receipt_sha256=receipt_sha256,
        tenant_id=tenant_id,
    )
    if any(row["source_id"] not in eligible for row in readings):
        raise ValueError("NATIVE_OCR_FALLBACK_INELIGIBLE")
    corroborated = {row["source_id"] for row in readings if row["exact_normalized_match"]}
    result = replace(
        baseline,
        blocks=tuple(
            replace(block, quality="verified") if block.source_id in corroborated else block
            for block in baseline.blocks
        ),
    )
    proof = dict(
        schema="experimental_native_raster_visibility_v1",
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        input_graph_sha256=canonical_hash(asdict(graph)),
        output_graph_sha256=canonical_hash(asdict(result)),
        policy_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        native_attestation_sha256=canonical_hash(native),
        request_sha256=request_sha256,
        receipt_sha256=receipt_sha256,
        corroborated_source_ids=sorted(corroborated),
    )
    proof["artifact_sha256"] = canonical_hash(proof)
    return result, proof
