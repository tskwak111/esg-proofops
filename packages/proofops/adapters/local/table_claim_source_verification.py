"""Opt-in table claim spans; reuse the existing cell/row PDF attestation.

Only exact spans become citable. Whole-table refs must map by raw offsets to
one literal row; no header or neighbouring-row values are joined into a claim.
Legacy paragraph and table policies, receipts and block qualities stay intact.
"""

import io
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pdfplumber
from pdfminer.pdftypes import resolve1

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import glyph_alignment_verification as baseline
from proofops.adapters.local import reviewed_context_verification as contexts
from proofops.adapters.local import selected_cell_table_verification as selected_cells
from proofops.adapters.local import table_span_source_verification as tables
from proofops.application.evidence import span_citations
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "table-claim-spans-v1"
SCHEMA = "table_claim_source_attestation_v1"


def claim_source_policy():
    return dict(
        schema=baseline.claim_source_policy()["schema"],
        profile=PROFILE,
        base=baseline.claim_source_policy(),
        table_policy=tables.table_span_policy(),
        selected_cell_policy_sha256=selected_cells.policy_sha256(),
        context_policy=contexts.context_cell_policy(),
        line_policy=tables.line_span_policy(),
        table_verifier_sha256=sha256(Path(tables.__file__).read_bytes()).hexdigest(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def _table_row_ref(graph, block, ref, tenant_id):
    """Map a table raw-offset span to exactly one original row, never search a page."""
    if (
        block.quality not in {"verified", "unverified"}
        or not tables._has_winner(block)
        or not tables._candidate_bound(graph, block.candidates[block.winner])
        or not tables._checked_ref(graph, ref, block, tenant_id)
    ):
        return None
    ids = {
        edge.source_id
        for edge in graph.edges
        if edge.relation == "table_parent" and edge.target_id == block.source_id
    }
    rows = sorted(
        (b for b in graph.blocks if b.source_id in ids and b.kind == "table_row"),
        key=lambda b: (b.candidates[b.winner].bbox[1], b.source_id)
        if tables._has_winner(b) and b.candidates[b.winner].bbox
        else (float("inf"), b.source_id),
    )
    if not rows or "\n".join(row.raw_text for row in rows) != block.raw_text:
        return None
    cursor = 0
    for row in rows:
        end = cursor + len(row.raw_text)
        if cursor <= ref.char_start < ref.char_end <= end:
            if row.page_num != block.page_num or tables._row_cells(graph, row) is None:
                return None
            start, stop = ref.char_start - cursor, ref.char_end - cursor
            if row.raw_text[start:stop] != ref.quote:
                return None
            return row.source_ref(normalized_char_start=start, normalized_char_end=stop)
        cursor = end + 1
    return None


def _flat_segments(graph, block, ref, tenant_id):
    if not tables._checked_ref(graph, ref, block, tenant_id):
        raise ValueError("source_invalid")
    table = contexts._table_owner(graph, block) if block.kind == "table_cell" else block
    members, blocks, grid = selected_cells._grid(graph, table)
    if any(
        not tables._has_winner(blocks[sid])
        or not tables._candidate_bound(graph, blocks[sid].candidates[blocks[sid].winner])
        for sid in members
    ):
        raise ValueError("source_invalid")
    if block.kind == "table_cell":
        return table, [(block, ref)]
    # Serialized row ordinal and column ordinal must match the declared grid.
    # Missing/merged slots can be blank, but never supply text from their origin.
    lines = table.raw_text.split("\n")
    if any(r >= len(lines) or c >= len(lines[r].split("\t")) for r, c in grid):
        raise ValueError("table_raw_grid_mismatch")
    for row, line in enumerate(lines):
        for col, text in enumerate(line.split("\t")):
            cell = grid.get((row, col))
            if text != (cell.raw_text if cell else ""):
                raise ValueError("table_raw_grid_mismatch")
    cursor = 0
    for row, line in enumerate(lines):
        end = cursor + len(line)
        if cursor <= ref.char_start < ref.char_end <= end:
            parts = []
            cell_offset = cursor
            for col, text in enumerate(line.split("\t")):
                left, right = (
                    max(cell_offset, ref.char_start),
                    min(cell_offset + len(text), ref.char_end),
                )
                if left < right:
                    cell = grid[(row, col)]
                    cell_ref = cell.source_ref(
                        normalized_char_start=left - cell_offset,
                        normalized_char_end=right - cell_offset,
                    )
                    parts.append((cell, cell_ref))
                cell_offset += len(text) + 1
            if not parts:
                raise ValueError("table_span_empty")
            return table, parts
        cursor = end + 1
    raise ValueError("table_span_not_one_row")


def _attest_flat(graph, source, refs, indices, records, tenant_id):
    plans, proofs = [], dict(mappings=[], selected_receipt=None, context_receipts=[])
    blocks = {b.source_id: b for b in graph.blocks}
    with pdfplumber.open(io.BytesIO(source)) as document:
        interactive = "OCProperties" in document.doc.catalog or (
            "AcroForm" in document.doc.catalog
            and not strict._pushbuttons_only(resolve1(document.doc.catalog.get("AcroForm")))
        )
        for index in indices:
            ref, block = refs[index], blocks[refs[index].source_id]
            try:
                table, parts = _flat_segments(graph, block, ref, tenant_id)
                if not 1 <= block.page_num <= len(document.pages):
                    raise ValueError("page_unavailable")
                page = document.pages[block.page_num - 1]
                if interactive or any(
                    strict._appearance_overlaps(page, cell.bbox) for cell, _ in parts
                ):
                    raise ValueError("interactive_visibility_requires_review")
                for cell, cell_ref in parts:
                    if not tables._checked_ref(graph, cell_ref, cell, tenant_id):
                        raise ValueError("source_invalid")
                plans.append((index, table, parts))
                proofs["mappings"].append(
                    dict(
                        record_index=index,
                        table_id=table.source_id,
                        cell_refs=[asdict(r) for _, r in parts],
                    )
                )
            except ValueError as error:
                records[index].update(status="unresolved", reason=str(error))
    if not plans:
        return proofs
    numeric = any(
        selected_cells._NUMERIC.fullmatch(cell.raw_text.strip())
        for _, _, parts in plans
        for cell, _ in parts
    )
    verified, reasons = set(), {}
    if numeric:
        receipt = selected_cells.attest_tables(graph, source, tenant_id=tenant_id)
        proofs["selected_receipt"] = receipt
        for table_record in receipt["records"]:
            for selection in table_record["selections"]:
                for cell in selection["cells"]:
                    if (
                        cell.get("attestation") == "native_and_rendered"
                        and cell.get("rendered_exact")
                        and (
                            cell["source_id"] in selection["promoted_source_ids"]
                            or not selected_cells._NUMERIC.fullmatch(cell["native_text"].strip())
                        )
                    ):
                        verified.add(cell["source_id"])
            for hold in table_record.get("held_selections", []):
                reasons[(table_record["table_id"], hold["value_row"], hold["value_column"])] = hold[
                    "reason"
                ]
    requested = sorted(
        {
            cell.source_id
            for _, _, parts in plans
            for cell, _ in parts
            if cell.source_id not in verified
            and not selected_cells._NUMERIC.fullmatch(cell.raw_text.strip())
        }
    )
    for start in range(0, len(requested), contexts.MAX_CELLS):
        receipt = contexts.attest_context_cells(
            graph, source, requested[start : start + contexts.MAX_CELLS], tenant_id=tenant_id
        )
        proofs["context_receipts"].append(receipt)
        for result in receipt["records"]:
            if result["status"] == "verified":
                verified.add(result["source_id"])
            else:
                reasons[result["source_id"]] = result["reason"]
    for index, table, parts in plans:
        held = next((cell for cell, _ in parts if cell.source_id not in verified), None)
        if held is None:
            records[index].update(status="verified", reason=None)
        else:
            candidate = held.candidates[held.winner]
            reason = reasons.get(held.source_id) or reasons.get(
                (table.source_id, candidate.row_number, candidate.column_number)
            )
            records[index].update(status="unresolved", reason=reason or "selected_cell_unresolved")
    return proofs


def attest_claim_spans(graph, source, refs, *, tenant_id):
    refs = tuple(refs)
    base = baseline.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
    blocks = {b.source_id: b for b in graph.blocks}
    selected, indices, mappings, flat = [], [], [], []
    records = [dict(r) for r in base["records"]]
    for index, ref in enumerate(refs):
        block = blocks.get(ref.source_id)
        if block is None or block.kind not in {"table", "table_row", "table_cell"}:
            continue
        target = ref
        if block.kind == "table":
            target = _table_row_ref(graph, block, ref, tenant_id)
            if target is None:
                flat.append(index)
                continue
        indices.append(index)
        selected.append(target)
        mappings.append(dict(record_index=index, original_ref=asdict(ref), row_ref=asdict(target)))
    table_receipt = tables.attest_table_spans(graph, source, tuple(selected), tenant_id=tenant_id)
    for index, result in zip(indices, table_receipt["records"], strict=True):
        records[index].update(status=result["status"], reason=result["reason"])
        if result["reason"] == "cell_structure_unresolved":
            flat.append(index)
    flat_proof = _attest_flat(graph, source, refs, flat, records, tenant_id)
    receipt = dict(
        schema=SCHEMA,
        policy=claim_source_policy(),
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        baseline_receipt=base,
        table_receipt=table_receipt,
        flat_grid_proof=flat_proof,
        mappings=mappings,
        records=records,
        readings=base["readings"],
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    return receipt


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    expected = attest_claim_spans(
        graph, source, strict.discovery_refs(discovery), tenant_id=tenant_id
    )
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("TABLE_CLAIM_RECEIPT_MISMATCH")
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
    )
    existing = tuple(getattr(graph, "verified_spans", ()) or ())
    scoped = span_citations.span_verified_graph(
        graph, existing + newly, expected["artifact_sha256"]
    )
    claims = []
    for claim in discovery.claims:
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        checked = tuple(
            span_citations.verify_source_ref(r, scoped, tenant_id=tenant_id)
            for r in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=checked)
            if checked and all(r.verification_state == "verified" for r in checked)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped
