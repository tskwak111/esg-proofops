"""Opt-in H7 EV1 admission over original bytes, never repaired parser candidates."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from pdfplumber.utils.exceptions import PdfminerException
from pypdf.errors import PdfReadError

from proofops.adapters.local import evidence_source_h6 as previous
from proofops.adapters.local import source_h7
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash

PROFILE = "evidence-source-h7-v1"
SCHEMA = "evidence_source_h7_attestation_v1"


def policy():
    return dict(
        previous.policy(),
        profile=PROFILE,
        original_reader=source_h7.policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        failure="page-coordinate-or-text-or-layout-or-pixels-unresolved; original-bytes-only",
    )


def attest_evidence_sources(
    graph, source, *, tenant_id, physical_pages=None, run_id=None, max_pixels=source_h7.MAX_PIXELS
):
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("EVIDENCE_SOURCE_MISMATCH")
    pages = (
        tuple(sorted({b.page_num for b in graph.blocks}))
        if physical_pages is None
        else tuple(physical_pages)
    )
    if (
        not pages
        or any(type(p) is not int or p < 1 for p in pages)
        or tuple(sorted(set(pages))) != pages
    ):
        raise ValueError("EVIDENCE_PAGE_SELECTION_INVALID")
    module = _exec_private(
        Path(__file__).parent,
        "evidence_source_verification_v1.py",
        "proofops.adapters.local._h7_evidence",
    )
    module.policy = policy
    raster = source_h7.RasterReader(source, max_pixels=max_pixels)
    module._rendered_text = raster.read
    try:
        try:
            result = module.attest_evidence_sources(
                graph, source, tenant_id=tenant_id, physical_pages=pages
            )
            reader = "pdfplumber-original"
        except PdfminerException:
            records = [
                dict(
                    source_id=b.source_id,
                    page=b.page_num,
                    kind=b.kind,
                    status="unresolved",
                    reason="relationship_validation_required",
                )
                for b in graph.blocks
                if b.page_num in pages
            ]
            selected = {r["source_id"]: r for r in records}
            cache = {}
            with pdfium.PdfDocument(source) as native:
                if pages[-1] > len(native):
                    raise ValueError("EVIDENCE_PAGE_SELECTION_INVALID")
                try:
                    document = source_h7.OriginalDocument(source, native)
                except (ValueError, PdfReadError, KeyError, TypeError) as error:
                    for record in records:
                        record.update(
                            reason="original_metadata_unresolved", error=type(error).__name__
                        )
                else:
                    for block in graph.blocks:
                        if block.source_id not in selected or block.kind != "paragraph":
                            continue
                        record = selected[block.source_id]
                        if block.quality not in {
                            "verified",
                            "unverified",
                        } or not module.q8._has_winner(block):
                            record["reason"] = "source_quality_unresolved"
                            continue
                        if any(
                            e.source_id == block.source_id and e.relation == "table_parent"
                            for e in graph.edges
                        ):
                            record["reason"] = "table_prose_requires_ownership"
                            continue
                        try:
                            record.update(
                                module._literal(document, native, graph, block, cache, prose=True)
                            )
                        except (
                            ValueError,
                            PdfReadError,
                            pdfium.PdfiumError,
                            KeyError,
                            TypeError,
                        ) as error:
                            record.update(
                                reason="original_page_mapping_or_layout_unresolved",
                                error=str(error)
                                if isinstance(error, ValueError)
                                else type(error).__name__,
                            )
            result = dict(
                tenant_id=tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                input_graph_sha256=canonical_hash(asdict(graph)),
                physical_pages=pages,
                records=records,
                tables=[],
                semantic_binding="undetermined",
                scope="exact-prose-only; damaged-original-table-ownership-unresolved",
            )
            reader = "PDFium-and-pypdf-original"
        result.update(
            schema=SCHEMA,
            policy=policy(),
            run_id=run_id,
            original_reader=reader,
            max_pixels=max_pixels,
            paid_calls=0,
        )
        result.pop("artifact_sha256", None)
        result["artifact_sha256"] = canonical_hash(result)
        return result
    finally:
        raster.close()


def replay_evidence_sources(receipt, graph, source, *, tenant_id):
    if receipt.get("policy") != policy() or receipt.get("schema") != SCHEMA:
        raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
    expected = attest_evidence_sources(
        graph,
        source,
        tenant_id=tenant_id,
        physical_pages=receipt.get("physical_pages"),
        run_id=receipt.get("run_id"),
        max_pixels=receipt.get("max_pixels"),
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("EVIDENCE_SOURCE_RECEIPT_MISMATCH")
    # Reuse EV1's exact scope/application, with instance-private recomputation.
    module = _exec_private(
        Path(__file__).parent,
        "evidence_source_verification_v1.py",
        "proofops.adapters.local._h7_evidence_replay",
    )
    module.policy = policy
    module.attest_evidence_sources = lambda *a, **k: expected
    return module.replay_evidence_sources(expected, graph, source, tenant_id=tenant_id)
