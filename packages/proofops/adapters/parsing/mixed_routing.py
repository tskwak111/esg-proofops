"""MP1 opt-in page routing. Readability is a routing hint, never source approval."""

import io
import re
from dataclasses import replace

from pypdf import PdfReader


def readable(text):
    return (
        isinstance(text, str)
        and len(re.findall(r"[a-zA-Z가-힣]", text)) >= 20
        and "(cid:" not in text
        and sum(text.count(c) for c in ("\ufffd", "\x00")) <= len(text) // 100
    )


def plan(source, profile, selected, candidates):
    if len(selected) > 30 or not set(profile.claim_physical_pages) <= set(selected):
        raise ValueError("MIXED_PAGE_SELECTION_INVALID")
    reader = PdfReader(io.BytesIO(source.content))
    local, rejected = [], []
    for page in sorted(set(selected) - set(profile.claim_physical_pages)):
        try:
            native = reader.pages[page - 1].extract_text()
        except Exception:
            native = ""  # preserve unreadable; no whole-document/paid expansion
        odl = "\n".join(
            b.source.raw_text
            for batch in candidates
            if batch.parser_name == "opendataloader"
            for b in batch.blocks
            if b.source.physical_page == page
        )
        (local if readable(native) and readable(odl) else rejected).append(page)
    return dict(
        version="mixed-v1",
        claim_pages=list(profile.claim_physical_pages),
        local_pages=local,
        rejected_native_pages=rejected,
        ocr_pages=rejected[: profile.mixed_ocr_max_pages],
    )


def keep(batch, pages):
    blocks = tuple(b for b in batch.blocks if b.source.physical_page in pages)
    ids = {b.source.source_native_id for b in blocks}
    return replace(
        batch,
        blocks=blocks,
        edges=tuple(
            e for e in batch.edges if e.source_native_id in ids and e.target_native_id in ids
        ),
    )


def annotate(batch):
    return replace(
        batch,
        blocks=tuple(
            replace(
                b,
                context=b.context
                + (
                    "mixed_parser_name=" + batch.parser_name,
                    "mixed_parser_version=" + batch.parser_version,
                ),
            )
            for b in batch.blocks
        ),
    )


def provenance(routing, candidates, selected):
    if routing["version"] != "mixed-v1":
        raise ValueError("unsupported page routing version")
    records = []
    for page in selected:
        batches = [b for b in candidates if any(x.source.physical_page == page for x in b.blocks)]
        route = (
            "upstage"
            if page in routing["claim_pages"] or page in routing["ocr_pages"]
            else "opendataloader"
            if page in routing["local_pages"]
            else "unreadable"
        )
        if any(
            not (b.parser_name.startswith("upstage_async_") or b.parser_name == "gemini_vision")
            if route == "upstage"
            else b.parser_name not in {"opendataloader", "pdfplumber"}
            for b in batches
        ) or (route == "unreadable" and batches):
            raise ValueError("page parser routing mismatch")
        records.append(
            dict(
                physical_page=page,
                role="claim" if page in routing["claim_pages"] else "evidence_only",
                route=route,
                parser_names=sorted({b.parser_name for b in batches}),
                parser_run_ids=sorted({b.parser_run_id for b in batches}),
                state="candidate" if batches else "unreadable",
                source_confirmation="required",  # glyph/render/table receipt must admit sources
            )
        )
    return records


def with_failures(graph, failures):
    """Keep candidates and explicit unreadable issues, never turn failure into absence."""
    from proofops.application.ingest.graph_fusion import QualityIssue
    from proofops.domain.provenance import canonical_hash

    issues = tuple(
        QualityIssue(
            canonical_hash([page, record]),
            "parser_batch_failed",
            page,
            (),
            "unreadable",
            record["error_code"],
        )
        for record in failures
        for page in record["pages"]
    )
    return replace(graph, issues=graph.issues + issues)
