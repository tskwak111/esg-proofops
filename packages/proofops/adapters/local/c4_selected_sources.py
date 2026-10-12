"""C4 general original certification prose, using EV1 glyph/layout and SV3 pixels.

This reader adds an exact span receipt; it never marks its parent verified.
Any original paragraph is eligible for exact span verification. OCR disagreement stays open.
Historical EV1/SV3 files, policies and receipts are unchanged.
"""

import io
import re
from contextlib import closing
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from proofops.adapters.local import claim_source_verification_v3 as sv3
from proofops.adapters.local import evidence_source_verification_v1 as ev1
from proofops.application.evidence.span_citations import span_verified_graph
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef


def policy():
    return dict(
        profile="c4-selected-ev1-prose-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        base=ev1.policy(),
        scope="same original paragraph; exact glyph crop; no parent promotion",
    )


def attest(graph, source, refs, *, tenant_id):
    if graph.tenant_id != tenant_id or sha256(source).hexdigest() != graph.source_sha256:
        raise ValueError("C4_SELECTED_SOURCE_IDENTITY_MISMATCH")
    blocks = {b.source_id: b for b in graph.blocks}
    records, cache = [], {}
    with pdfplumber.open(io.BytesIO(source)) as doc, pdfium.PdfDocument(source) as native:
        for ref in refs:
            record = dict(ref=asdict(ref), status="unresolved", reason="selection_not_eligible")
            records.append(record)
            block = blocks.get(ref.source_id)
            context = bool(re.fullmatch(r"(?:19|20)\d{2}", ref.quote))
            if (
                not block
                or block.winner is None
                or block.kind != "paragraph"
                or not ev1.q8._checked_ref(graph, ref, block, tenant_id)
                or (not context and ("경영시스템" not in ref.quote or "인증" not in ref.quote))
                or (context and "보고서" not in block.normalized_text)
                or any(
                    e.source_id == block.source_id and e.relation == "table_parent"
                    for e in graph.edges
                )
            ):
                continue
            entries = cache.setdefault(ref.page_num, sv3._native_page(native, ref.page_num))
            page = doc.pages[ref.page_num - 1]
            with closing(native[ref.page_num - 1]) as np, closing(np.get_textpage()) as tp:
                text = tp.get_text_bounded(
                    ref.bbox[0], page.height - ref.bbox[3], ref.bbox[2], page.height - ref.bbox[1]
                )
            alignment = sv3._canonical(ref.quote, text)
            glyphs = (
                sv3._quote_glyphs(
                    entries or [],
                    alignment["canonical_quote"],
                    ref.bbox,
                    alignment["changed_boundaries"],
                )
                if alignment
                else None
            )
            if not glyphs:
                record["reason"] = "selected_glyphs_unresolved"
                continue
            boxes = [g["bbox"] for g in glyphs]
            box = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            if not context and (reason := ev1._prose_layout(page, box, glyphs)):
                record["reason"] = reason
                continue
            checked = sv3._recover(
                doc, native, block, replace(ref, bbox=box), cache, {}, graph.source_sha256
            )
            record.update(checked)
            record["selected_pixel_bbox_pt"] = box
    body = dict(
        schema="c4_selected_source_receipt_v1",
        policy=policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        input_graph_sha256=canonical_hash(asdict(graph)),
        records=records,
    )
    return body | dict(artifact_sha256=canonical_hash(body))


def replay(receipt, graph, source, *, tenant_id):
    if receipt.get("policy") != policy():
        raise ValueError("C4_SELECTED_SOURCE_POLICY_MISMATCH")
    refs = tuple(SourceRef(**r["ref"]) for r in receipt["records"])
    expected = attest(graph, source, refs, tenant_id=tenant_id)
    if canonical_hash(expected) != canonical_hash(receipt):
        raise ValueError("C4_SELECTED_SOURCE_REPLAY_MISMATCH")
    verified = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
    )
    return span_verified_graph(graph, verified, expected["artifact_sha256"])
