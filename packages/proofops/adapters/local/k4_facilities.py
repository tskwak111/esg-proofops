"""Native-proof facility dimensions for display/review; no element/grade credit."""

import io
import re
from dataclasses import asdict, replace
from hashlib import sha256

import pdfplumber

from proofops.adapters.local import upstage_ocr_profile_v10 as native
from proofops.adapters.local.upstage_ocr_profile_v11 import _column_owners
from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref
from proofops.application.ingest.k1_boundaries import OBSERVATION
from proofops.application.ingest.w9_tables import graph_cells, grid
from proofops.application.tagging.k4_contract import (
    FACILITY_LABELS as FACILITY,
)
from proofops.application.tagging.k4_contract import (
    FACILITY_POLICY as POLICY,
)
from proofops.domain.provenance import canonical_hash

PROFILE = POLICY["profile"]


def restore_facilities(graph, source, claims, *, tenant_id):
    if tenant_id != graph.tenant_id or sha256(source).hexdigest() != graph.source_sha256:
        raise ValueError("K4_FACILITY_SOURCE_MISMATCH")
    if not claims:
        # No facility dimension can be attributed without a claim. Retain the
        # source guard, but do not reopen unreadable bytes for an empty scope.
        return {}
    blocks = {b.source_id: b for b in graph.blocks}
    results = {}
    with pdfplumber.open(io.BytesIO(source)) as pdf:
        owners = {}
        for claim in claims:
            if claim.tenant_id != tenant_id or len(claim.source_refs) != 1:
                continue
            ref = claim.source_refs[0]
            if verify_source_ref(ref, graph, tenant_id=tenant_id).verification_state != "verified":
                continue
            table = blocks.get(ref.source_id)
            if table is None or table.kind != "table" or table.winner is None:
                continue
            try:
                rows = grid(table.raw_text, graph_cells(table, graph))
                entries = [
                    e
                    for row in rows
                    for e in row["entries"]
                    if e["cell"] and e["start"] <= ref.char_start < ref.char_end <= e["end"]
                ]
                if len(entries) != 1:
                    continue
                focal = entries[0]
                page = pdf.pages[ref.page_num - 1]
                if page.rotation or tuple(page.cropbox[:2]) != (0, 0):
                    continue
                if table.source_id not in owners:
                    owners[table.source_id] = _column_owners(page, graph, table)
                regions, headings = owners[table.source_id]
                col = focal["column"]
                # This profile applies only to tables whose complete top row is
                # facility labels. Generic metric/year tables stay unresolved.
                if not all(
                    re.fullmatch(FACILITY, h["quote"].strip())
                    and not re.fullmatch(r"(?:19|20)\d{2}|지표명|단위|구분|항목", h["quote"])
                    for h in headings
                ):
                    continue
                prior = [
                    e
                    for row in rows
                    for e in row["entries"]
                    if e["cell"]
                    and e["column"] == col
                    and e["end"] <= ref.char_start
                    and re.fullmatch(FACILITY, e["text"].strip())
                ]
                # K1's explicit trailing noun label belongs to the next bullet
                # only after native geometry confirms it precedes that bullet.
                inline = [
                    m
                    for m in re.finditer(OBSERVATION, focal["text"])
                    if focal["start"] + m.end("label") <= ref.char_start
                ]
                header = max(prior, key=lambda e: e["end"]) if prior else None
                if inline:
                    match = inline[-1]
                    if not re.fullmatch(FACILITY, match["label"].strip()):
                        continue
                    a, b = (
                        focal["start"] + match.start("label"),
                        focal["start"] + match.end("label"),
                    )
                elif header:
                    a, b = header["start"], header["end"]
                else:
                    continue
                label = table.raw_text[a:b]
                heading_box = native._literal(page, regions[col], label)
                value_box = native._literal(page, regions[col], ref.quote)
                if heading_box[3] >= value_box[1] or native.strict._appearance_overlaps(
                    page, heading_box
                ):
                    continue
                heading_ref = table.source_ref(normalized_char_start=a, normalized_char_end=b)
                header_cell = (
                    blocks.get(header["cell"]["source_id"]) if header and not inline else None
                )
                if header_cell is not None and header_cell.bbox is not None:
                    heading_ref = header_cell.source_ref()
                if not native._within(heading_box, heading_ref.bbox, 0.5):
                    continue
                proof = dict(
                    policy=POLICY,
                    tenant_id=tenant_id,
                    document_version_id=graph.document_version_id,
                    parse_manifest_id=graph.parse_manifest_id,
                    source_sha256=graph.source_sha256,
                    input_graph_sha256=canonical_hash(asdict(graph)),
                    claim_ref=asdict(ref),
                    header_ref=asdict(heading_ref),
                    native_header_bbox=heading_box,
                    native_claim_bbox=value_box,
                    column=col,
                    table_source_id=table.source_id,
                    table_header_start=a,
                    table_header_end=b,
                )
                proof_hash = canonical_hash(proof)
                admitted = span_verified_graph(
                    graph,
                    (
                        *getattr(graph, "verified_spans", ()),
                        replace(heading_ref, verification_state="verified"),
                    ),
                    proof_hash,
                )
                checked = verify_source_ref(heading_ref, admitted, tenant_id=tenant_id)
                if checked.verification_state != "verified":
                    continue
                results[claim.claim_id] = dict(
                    facility=dict(
                        state="source_verified",
                        value=label.strip(),
                        source_refs=[asdict(checked)],
                        proof=proof,
                        proof_sha256=proof_hash,
                        rule_credit=False,
                    ),
                )
            except (ValueError, KeyError, TypeError):
                continue  # Ambiguous source/layout remains an explicit unresolved dimension.
    return results
