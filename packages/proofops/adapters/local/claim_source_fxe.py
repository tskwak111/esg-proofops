"""FXA glyph/visibility guards with portable, original-region pixel confirmation.

This additive reader changes neither parser offsets nor historical v4 bytes.
Only literal native paragraphs can use it; OCR is never a source of corrections.
"""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from pypdf.errors import PdfReadError

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import claim_source_verification_v4 as v4
from proofops.adapters.local import source_fxe, source_h7
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.provenance import canonical_hash


def claim_source_policy():
    return dict(
        schema="claim_source_render_conditioned_policy_v1",
        profile="claim-source-fxe-v1",
        base=v4.claim_source_policy(),
        raster=source_fxe.policy(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        admission="FXA-native-glyph-offset-guards; exact-quote-in-original-region-pixels",
    )


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or sha256(source).hexdigest() != graph.source_sha256
    ):
        raise ValueError("CLAIM_SOURCE_MISMATCH")
    blocks = {b.source_id: b for b in graph.blocks}
    table_members = {e.source_id for e in graph.edges if e.relation == "table_parent"}
    records, page_cache = [], {}
    raster = source_fxe.RasterReader(source)
    try:
        with pdfium.PdfDocument(source) as native:
            document = source_h7.OriginalDocument(source, native)
            for ref in refs:
                record = dict(ref=asdict(ref), status="unresolved", reason="source_invalid")
                records.append(record)
                block = blocks.get(ref.source_id)
                if block is None or ref.source_id in table_members:
                    continue
                try:
                    record.update(
                        v4._native_record(
                            document, native, graph, block, ref, tenant_id, page_cache
                        )
                    )
                    if record["status"] != "pixel_required":
                        continue
                    normalization = record["normalization"]
                    glyphs = normalization["glyphs"]
                    # Crop the quote's actual glyphs, retaining the full ref and
                    # its exact parser/native offset map. All original paint,
                    # clips, overlays and annotations still render in this ROI.
                    box = (
                        min(g["bbox"][0] for g in glyphs),
                        min(g["bbox"][1] for g in glyphs),
                        max(g["bbox"][2] for g in glyphs),
                        max(g["bbox"][3] for g in glyphs),
                    )
                    page = document.pages[ref.page_num - 1]
                    attempts, matches = [], []
                    # Retain the historical block crop as a second bounded
                    # context when a tightly clipped line is harder to read.
                    for region in dict.fromkeys((box, tuple(ref.bbox))):
                        attempts.extend(raster.read(page, region, padding_px=p) for p in (0, 6))
                        matches = [
                            r
                            for r in attempts
                            if r.get("status") == "read"
                            and strict._unique_quote(
                                v4.v3._plain(r.get("text", "")), normalization["canonical_quote"]
                            )
                        ]
                        if matches:
                            break
                    record.update(
                        status="verified" if matches else "unresolved",
                        reason=None if matches else "rendered_quote_unresolved",
                        pixel_attempts=attempts,
                        rendered_read_sha256=canonical_hash(matches[0]) if matches else None,
                    )
                except (ValueError, PdfReadError, pdfium.PdfiumError, KeyError, TypeError) as error:
                    record.update(
                        status="unresolved",
                        reason="original_page_mapping_or_layout_unresolved",
                        error=type(error).__name__,
                    )
    finally:
        raster.close()
    receipt = dict(
        schema="claim_source_fxe_attestation_v1",
        policy=claim_source_policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        records=records,
    )
    return receipt | dict(artifact_sha256=canonical_hash(receipt))
