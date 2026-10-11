"""PB1 adds exact native cell/row proofs; immutable v6 prose replay stays available."""

import io
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pdfplumber

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import table_claim_source_verification as tables
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.local_raster_reader import interactive_catalog_requires_review
from proofops.adapters.parsing.gemini_vision import _ground, compact
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v7"
PageOCRStore = v6.PageOCRStore


def reader_policy():
    return dict(
        v6.reader_policy(),
        profile=PROFILE,
        table_cells="native-literal-grid-pb1-v1",
        native_unit_read="literal-x-ordered-glyphs-in-row-band",
    )


def claim_source_policy():
    return dict(
        v6.claim_source_policy(),
        profile=PROFILE,
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(v6.native_policy(), mode=PROFILE, reader=reader_policy())


def table_policy_sha256():
    from proofops.adapters.local.selected_cell_table_verification import policy_sha256

    return canonical_hash(dict(reader=native_policy(), selected_cell_policy=policy_sha256()))


def table_span_policy():
    return dict(v6.table_span_policy(), profile=PROFILE, reader=reader_policy())


_wrapper = _exec_private(
    Path(__file__).parent, "upstage_ocr_profile_v6.py", "proofops.adapters.local._ocr_v7"
)
for _name in (
    "PROFILE",
    "reader_policy",
    "claim_source_policy",
    "native_policy",
    "table_policy_sha256",
    "table_span_policy",
):
    setattr(_wrapper, _name, globals()[_name])
    setattr(_wrapper._wrapper, _name, globals()[_name])
    setattr(_wrapper._wrapper._composition, _name, globals()[_name])


def _segments(graph, block, ref, tenant_id):
    if not tables.tables._checked_ref(graph, ref, block, tenant_id):
        raise ValueError("source_invalid")
    if block.kind == "table_cell":
        raise ValueError("pb1_value_requires_row")
    ids = {
        e.source_id
        for e in graph.edges
        if e.relation == "table_parent" and e.target_id == block.source_id
    }
    grid = {}
    for cell in graph.blocks:
        if cell.source_id not in ids or cell.kind != "table_cell" or cell.winner is None:
            continue
        c = cell.candidates[cell.winner]
        key = c.row_number, c.column_number
        if key in grid:
            raise ValueError("duplicate_cell_origin")
        grid[key] = cell
    offset = 0
    for row, line in enumerate(block.raw_text.split("\n")):
        end = offset + len(line)
        if offset <= ref.char_start < ref.char_end <= end:
            parts = []
            cursor = offset
            for col, text in enumerate(line.split("\t")):
                cell = grid.get((row, col))
                if text != (cell.raw_text if cell else ""):
                    raise ValueError("table_raw_grid_mismatch")
                left, right = max(cursor, ref.char_start), min(cursor + len(text), ref.char_end)
                if left < right:
                    parts.append(
                        (
                            cell,
                            cell.source_ref(
                                normalized_char_start=left - cursor,
                                normalized_char_end=right - cursor,
                            ),
                        )
                    )
                cursor += len(text) + 1
            from proofops.application.ingest.pb1_tables import observations

            context = " ".join(block.candidates[block.winner].context)
            observation = next(
                (
                    r
                    for r in observations(block.normalized_text, context=context)
                    if r["row"] == row
                ),
                None,
            )
            if observation is None:
                raise ValueError("pb1_observation_unresolved")
            header = observation["year_header"]
            year_cell = grid.get((header["row"], header["column"]))
            if year_cell is None:
                raise ValueError("pb1_year_header_unresolved")
            parts.append((year_cell, year_cell.source_ref()))
            return block, parts
        offset = end + 1
    raise ValueError("table_span_not_one_row")


def cell_proof(graph, source, refs, *, tenant_id):
    """Every quoted cell must match native PDF characters/numbers within its own box."""
    blocks = {b.source_id: b for b in graph.blocks}
    records = []
    hidden = interactive_catalog_requires_review(source)
    with pdfplumber.open(io.BytesIO(source)) as document:
        cache = {}
        for ref in refs:
            block = blocks[ref.source_id]
            record = dict(ref=asdict(ref), status="unresolved", reason="cell_structure_unresolved")
            records.append(record)
            if hidden:
                record["reason"] = "interactive_visibility_requires_review"
                continue
            try:
                table, parts = _segments(graph, block, ref, tenant_id)
                proofs = []
                page = document.pages[ref.page_num - 1]
                if page.rotation or tuple(page.cropbox[:2]) != (0, 0):
                    raise ValueError("geometry_unsupported")
                if ref.page_num not in cache:
                    cache[ref.page_num] = page.extract_words()
                for cell, cell_ref in parts:
                    if (
                        cell.bbox is None
                        or not tables.tables._checked_ref(graph, cell_ref, cell, tenant_id)
                        or strict._appearance_overlaps(page, cell.bbox)
                    ):
                        raise ValueError("cell_source_unresolved")
                    box = cell.bbox
                    words = [
                        w
                        for w in cache[ref.page_num]
                        if box[0] - 0.5 <= w["x0"]
                        and w["x1"] <= box[2] + 0.5
                        and box[1] - 0.5 <= w["top"]
                        and w["bottom"] <= box[3] + 0.5
                    ]
                    grounded, _ = _ground(cell_ref.quote, words, box)
                    if grounded is None:
                        chars = [
                            c
                            for c in page.chars
                            if box[0] - 0.1 <= c["x0"]
                            and c["x1"] <= box[2] + 0.1
                            and box[1] - 0.1 <= c["top"]
                            and c["bottom"] <= box[3] + 0.1
                        ]
                        literal = "".join(c["text"] for c in sorted(chars, key=lambda c: c["x0"]))
                        if not chars or compact(literal) != compact(cell_ref.quote):
                            raise ValueError("cell_native_literal_unresolved")
                        grounded = box
                    proofs.append(
                        dict(
                            source_ref=asdict(cell_ref),
                            native_bbox=grounded,
                            row=cell.candidates[cell.winner].row_number,
                            column=cell.candidates[cell.winner].column_number,
                        )
                    )
                record.update(
                    status="verified", reason=None, table_id=table.source_id, cell_proofs=proofs
                )
            except (ValueError, KeyError) as error:
                record["reason"] = str(error)
    return records


class Reader(_wrapper.Reader):
    def _claim_receipt(self, modules, graph, source, refs, *, tenant_id):
        receipt = super()._claim_receipt(modules, graph, source, refs, tenant_id=tenant_id)
        blocks = {b.source_id: b for b in graph.blocks}
        indices = [
            i for i, r in enumerate(refs) if blocks[r.source_id].kind in {"table", "table_cell"}
        ]
        if indices:
            proof = cell_proof(graph, source, [refs[i] for i in indices], tenant_id=tenant_id)
            receipt["pb1_cell_proofs"] = proof
            for i, record in zip(indices, proof, strict=True):
                receipt["records"][i].update(status=record["status"], reason=record["reason"])
        receipt["policy"] = claim_source_policy()
        receipt.pop("artifact_sha256", None)
        receipt["artifact_sha256"] = canonical_hash(receipt)
        return receipt


_wrapper._wrapper._composition.Reader = Reader
_wrapper._wrapper.Reader = Reader
for_run = _wrapper.for_run
attest_claim_spans = _wrapper.attest_claim_spans


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from dataclasses import replace

    from proofops.application.evidence.span_citations import span_verified_graph
    from proofops.domain.values import SourceRef

    discovery, scoped = _wrapper.replay_claim_spans(
        receipt, graph, source, discovery, tenant_id=tenant_id
    )
    refs = tuple(
        replace(SourceRef(**cell["source_ref"]), verification_state="verified")
        for proof in receipt.get("pb1_cell_proofs", [])
        if proof["status"] == "verified"
        for cell in proof["cell_proofs"]
    )
    if refs:
        scoped = span_verified_graph(
            scoped, (*scoped.verified_spans, *refs), receipt["artifact_sha256"]
        )
    return discovery, scoped


attest_tables = _wrapper.attest_tables
replay_tables = _wrapper.replay_tables
