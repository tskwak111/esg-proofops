"""Opt-in EV1 source admission. Exact prose spans or a fully checked table grid.

No model calls, semantic binding, grades, old receipt edits or default changes.
Caller pins policy(), stores a new receipt, and replays it on original bytes.
"""

import io
import re
from contextlib import closing
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from pdfminer.pdftypes import resolve1

from proofops.adapters.local import claim_source_verification_v3 as sv1
from proofops.adapters.local import table_span_source_verification as q8
from proofops.adapters.local.source_verification import _rendered_text
from proofops.application.evidence import span_citations
from proofops.application.ingest.gri import _validate_graph
from proofops.domain.numeric import unassigned_note_ids
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "evidence-source-v1"
SCHEMA = "evidence_source_attestation_v1"
MAX_TABLE_CELLS = 400


def policy():
    local = Path(__file__).parent
    return dict(
        schema="evidence_source_policy_v1",
        profile=PROFILE,
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        prose_policy=sv1.claim_source_policy(),
        table_layout_policy=q8.line_span_policy(),
        files={
            name: sha256((local / name).read_bytes()).hexdigest()
            for name in (
                "source_verification.py",
                "native_ocr.swift",
            )
        },
        readers={name: version(name) for name in ("pdfplumber", "pdfminer.six", "pypdfium2")},
    )


def _prose_layout(page, box, glyphs):
    """Conservative eligibility, never a reconstruction of a flattened table.

    Gaps over two ink heights or a crop bounded by nearby horizontal rules need
    explicit table ownership. This may withhold prose; it cannot waive a table
    guard. The value is a geometric admission limit, not a domain threshold.
    """
    height = max(g["bbox"][3] - g["bbox"][1] for g in glyphs)
    for a, b in zip(glyphs, glyphs[1:]):
        x, y = a["bbox"], b["bbox"]
        same_line = min(x[3], y[3]) > max(x[1], y[1])
        if same_line:
            if y[0] < x[0] - 0.001 or y[0] - x[2] > 2 * height:
                return "column_or_reading_order_requires_table"
        elif y[1] < x[1] or y[1] - x[3] > 2 * height:
            return "discontinuous_prose_requires_review"
    # Merge collinear rule fragments (ODL often missed these open-border tables).
    rules = {}
    for edge in page.edges:
        if edge.get("orientation") == "h":
            rules.setdefault(round(edge["top"], 2), []).append((edge["x0"], edge["x1"]))
    spanning = []
    for top, fragments in rules.items():
        merged = []
        for left, right in sorted(fragments):
            if merged and left <= merged[-1][1] + 0.5:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        if any(
            left <= box[0] + 2 * height and right >= box[2] - 2 * height for left, right in merged
        ):
            spanning.append(top)
    if any(box[1] - 4 * height <= y <= box[1] + 0.001 for y in spanning) and any(
        box[3] - 0.001 <= y <= box[3] + 4 * height for y in spanning
    ):
        return "ruled_region_requires_table_ownership"
    if any(box[1] + 0.001 < y < box[3] - 0.001 for y in spanning):
        return "ruled_region_requires_table_ownership"
    return None


def _literal(document, native, graph, block, page_cache, *, prose):
    ref = block.source_ref()
    if not q8._checked_ref(graph, ref, block, graph.tenant_id):
        return dict(status="unresolved", reason="source_invalid")
    candidate = block.candidates[block.winner]
    box, geometry = candidate.bbox, candidate.geometry
    if not 1 <= block.page_num <= len(document.pages):
        return dict(status="unresolved", reason="geometry_unsupported")
    page = document.pages[block.page_num - 1]
    if (
        box is None
        or candidate.has_invalid_geometry
        or page.rotation
        or geometry.rotation
        or tuple(page.mediabox[:2]) != (0, 0)
        or tuple(page.cropbox) != tuple(page.mediabox)
        or tuple(geometry.crop_box[:2]) != (0, 0)
        or abs(page.width - geometry.width_pt) > 0.001
        or abs(page.height - geometry.height_pt) > 0.001
    ):
        return dict(status="unresolved", reason="geometry_unsupported")
    form = resolve1(document.doc.catalog.get("AcroForm"))
    if (
        "OCProperties" in document.doc.catalog
        or ("AcroForm" in document.doc.catalog and not isinstance(form, dict))
        or (isinstance(form, dict) and any(k in form for k in ("XFA", "NeedsRendering")))
    ):
        return dict(status="unresolved", reason="interactive_visibility_requires_review")
    if block.page_num not in page_cache:
        page_cache[block.page_num] = sv1._native_page(native, block.page_num)
    entries = page_cache[block.page_num]
    if not entries:
        return dict(status="unresolved", reason="glyph_geometry_unresolved")
    with closing(native[block.page_num - 1]) as np, closing(np.get_textpage()) as tp:
        text = tp.get_text_bounded(box[0], page.height - box[3], box[2], page.height - box[1])
    alignment = sv1._canonical(ref.quote, text)
    if alignment is None or sv1._plain(text) != alignment["canonical_quote"]:
        return dict(
            status="unresolved",
            reason="native_quote_or_sensitive_spacing_mismatch",
            native_text=text,
        )
    glyphs = sv1._quote_glyphs(
        entries, alignment["canonical_quote"], box, alignment["changed_boundaries"]
    )
    if not glyphs:
        return dict(status="unresolved", reason="clipped_ambiguous_or_cross_row_quote")
    selected = {g["index"] for g in glyphs}
    if any(e["index"] not in selected and sv1._intersects(e["bbox"], box) for e in entries):
        return dict(status="unresolved", reason="foreign_or_clipped_glyph_in_region")
    if sv1._annotation_blocker(page, [g["bbox"] for g in glyphs]):
        return dict(status="unresolved", reason="interactive_visibility_requires_review")
    if prose:
        # ODL also emits open-border table cells as standalone paragraphs. A
        # negative table detector may withhold prose; never use it to approve a
        # guessed grid. Short fragments likewise require explicit relationships.
        if sum(c.isalpha() for c in ref.quote) < 16:
            return dict(status="unresolved", reason="prose_fragment_requires_relationship")
        key = (block.page_num, "table_regions")
        if key not in page_cache:
            page_cache[key] = [
                t.bbox
                for t in page.find_tables(
                    {
                        "vertical_strategy": "text",
                        "horizontal_strategy": "lines",
                        "min_words_vertical": 3,
                    }
                )
            ]
        if any(sv1._intersects(region, box) for region in page_cache[key]):
            return dict(status="unresolved", reason="detected_table_requires_ownership")
    if prose and (reason := _prose_layout(page, box, glyphs)):
        return dict(status="unresolved", reason=reason)
    rendered = _rendered_text(page, box, padding_px=6)
    proof = dict(
        source_sha256=graph.source_sha256,
        physical_page=block.page_num,
        bbox=list(box),
        parser_quote=ref.quote,
        native_text=text,
        glyphs=glyphs,
        **alignment,
        rendered=rendered,
    )
    good = (
        rendered.get("status") == "read"
        and sv1._plain(rendered.get("text", "")) == alignment["canonical_quote"]
    )
    return dict(
        status="verified" if good else "unresolved",
        reason=None if good else "rendered_quote_unresolved",
        ref=asdict(ref),
        proof=proof,
    )


def _table_members(graph, table):
    rows = [
        b
        for b in graph.blocks
        if b.kind == "table_row"
        and any(
            e.source_id == b.source_id
            and e.target_id == table.source_id
            and e.relation == "table_parent"
            for e in graph.edges
        )
    ]
    if (
        not rows
        or any(not q8._has_winner(row) for row in rows)
        or (layout := q8._table_layout(graph, rows[0])) is None
    ):
        return None
    ordered = sorted(layout["rows"].values(), key=lambda r: r["box"][1])
    cells = [c for r in ordered for c in r["cells"]]
    columns = [tuple(c.candidates[c.winner].column_number for c in r["cells"]) for r in ordered]
    if (
        len(ordered) < 2
        or not 4 <= len(cells) <= MAX_TABLE_CELLS
        or any(len(r["cells"]) < 2 for r in ordered)
        or any(cols != columns[0] for cols in columns)
        or re.search(r"\d+\)|[*†‡]", table.raw_text)
        or any(q8._row_cells(graph, r["block"]) is None for r in ordered)
        or table.raw_text != "\n".join(r["block"].raw_text for r in ordered)
    ):
        return None
    return [r["block"] for r in ordered], cells


def attest_evidence_sources(graph, source, *, tenant_id, physical_pages=None):
    """Complete block census; only explicitly selected original physical pages."""
    _validate_graph(graph, tenant_id)
    if (
        not isinstance(source, bytes)
        or len(source) > 100 * 1024 * 1024
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
    records = {
        b.source_id: dict(
            source_id=b.source_id,
            page=b.page_num,
            kind=b.kind,
            status="unresolved",
            reason="relationship_validation_required",
        )
        for b in graph.blocks
        if b.page_num in pages
    }
    page_cache, tables = {}, []
    with pdfplumber.open(io.BytesIO(source)) as document, pdfium.PdfDocument(source) as native:
        if pages[-1] > len(document.pages):
            raise ValueError("EVIDENCE_PAGE_SELECTION_INVALID")
        for block in graph.blocks:
            if block.source_id not in records:
                continue
            record = records[block.source_id]
            if block.quality not in {"verified", "unverified"} or not q8._has_winner(block):
                record["reason"] = "source_quality_unresolved"
                continue
            if block.kind != "paragraph":
                continue
            if any(
                e.source_id == block.source_id and e.relation == "table_parent" for e in graph.edges
            ):
                record["reason"] = "table_prose_requires_ownership"
                continue
            record.update(_literal(document, native, graph, block, page_cache, prose=True))
        for table in graph.blocks:
            if table.kind != "table" or table.source_id not in records:
                continue
            members = _table_members(graph, table)
            tr = dict(
                table_id=table.source_id,
                page=table.page_num,
                status="unresolved",
                reason="table_layout_unresolved",
                cells=[],
            )
            tables.append(tr)
            if members is None:
                continue
            rows, cells = members
            member_ids = {b.source_id for b in [table, *rows, *cells]}
            if any(unassigned_note_ids(graph, sid) for sid in member_ids) or any(
                i.state in {"open", "unreadable"}
                and member_ids.intersection(i.source_ids)
                and i.kind != "table_vision_not_run"
                for i in graph.issues
            ):
                tr["reason"] = "table_source_issue_unresolved"
                continue
            for cell in cells:
                result = _literal(document, native, graph, cell, page_cache, prose=False)
                tr["cells"].append(dict(source_id=cell.source_id, **result))
                if result["status"] != "verified":
                    tr["reason"] = result["reason"]
                    break
            else:
                tr.update(
                    status="verified",
                    reason=None,
                    member_ids=sorted(member_ids),
                    row_column_binding="physical_grid_only",
                    semantic_binding="undetermined",
                )
                for block in [table, *rows, *cells]:
                    records[block.source_id].update(
                        status="verified",
                        reason=None,
                        ref=asdict(block.source_ref()),
                        table_id=table.source_id,
                    )
            if tr["status"] != "verified":
                for block in [table, *rows, *cells]:
                    records[block.source_id]["reason"] = tr["reason"]
    receipt = dict(
        schema=SCHEMA,
        policy=policy(),
        tenant_id=tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        input_graph_sha256=canonical_hash(asdict(graph)),
        physical_pages=pages,
        records=list(records.values()),
        tables=tables,
        scope="exact_prose_spans_and_complete_unmerged_table_grids",
        semantic_binding="undetermined",
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    return receipt


def replay_evidence_sources(receipt, graph, source, *, tenant_id):
    """Fail closed on policy/content/tenant drift; do not trust caller flags."""
    if receipt.get("policy") != policy():
        raise ValueError("EVIDENCE_SOURCE_POLICY_MISMATCH")
    expected = attest_evidence_sources(
        graph, source, tenant_id=tenant_id, physical_pages=receipt.get("physical_pages")
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("EVIDENCE_SOURCE_RECEIPT_MISMATCH")
    members = {
        sid for t in expected["tables"] if t["status"] == "verified" for sid in t["member_ids"]
    }
    table_ids = {t["table_id"] for t in expected["tables"] if t["status"] == "verified"}
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
        for r in expected["records"]
        if r["kind"] == "paragraph" and r["status"] == "verified"
    )
    return span_citations.span_verified_graph(
        checked,
        tuple(getattr(graph, "verified_spans", ()) or ()) + refs,
        expected["artifact_sha256"],
    )
