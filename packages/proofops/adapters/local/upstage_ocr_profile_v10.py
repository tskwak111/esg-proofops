"""PA9 native owned-cell recovery; all historical readers and v6 prose stay intact."""

import io
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pdfplumber

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import table_claim_source_verification as tables
from proofops.adapters.local import upstage_ocr_profile_v6 as v6
from proofops.adapters.local import upstage_ocr_profile_v8 as table_base
from proofops.adapters.local import upstage_ocr_profile_v9 as previous
from proofops.adapters.parsing.gemini_vision import compact
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "upstage-ocr-page-v10"
PageOCRStore = v6.PageOCRStore
native_policy = v6.native_policy
table_policy_sha256 = v6.table_policy_sha256
table_span_policy = v6.table_span_policy
attest_tables = v6.attest_tables
replay_tables = v6.replay_tables


def reader_policy():
    return dict(
        v6.reader_policy(),
        profile=PROFILE,
        prose_reader_policy_sha256=canonical_hash(v6.reader_policy()),
        table_reader_policy_sha256=canonical_hash(table_base.reader_policy()),
        table_reader_sha256=sha256(Path(table_base.__file__).read_bytes()).hexdigest(),
        native_row_ownership="native-grid-pa9-v1",
        recovery="exact-native-painted-or-ruled-grid-header-row-column-v1",
        previous_reader_sha256=sha256(Path(previous.__file__).read_bytes()).hexdigest(),
    )


def claim_source_policy():
    return dict(
        schema="claim_span_typography_policy_v1",
        profile=PROFILE,
        base_prose_policy_sha256=canonical_hash(v6.claim_source_policy()),
        reader=reader_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def _within(box, outer, tolerance=0.2):
    return (
        outer[0] - tolerance <= box[0] < box[2] <= outer[2] + tolerance
        and outer[1] - tolerance <= box[1] < box[3] <= outer[3] + tolerance
    )


def _literal(page, box, quote, *, whole=False):
    """Read only one native cell; preserve every non-whitespace character."""
    chars = [c for c in page.chars if _within((c["x0"], c["top"], c["x1"], c["bottom"]), box)]
    if not chars or len(chars) > 10000:
        raise ValueError("cell_native_literal_unresolved")
    target = compact(quote)
    if not target:
        raise ValueError("cell_native_literal_unresolved")
    orders = [chars]
    if max(c["top"] for c in chars) < min(c["bottom"] for c in chars):
        orders.append(sorted(chars, key=lambda c: c["x0"]))
    matches = {}
    for ordered in orders:
        pieces = [compact(c["text"]) for c in ordered]
        text = "".join(pieces)
        if whole and text != target:
            continue
        start = text.find(target)
        if start < 0 or text.find(target, start + 1) >= 0:
            continue
        end = start + len(target)
        # No truncation of a native number, decimal or percent token.
        if (
            target[0].isdigit()
            and start
            and text[start - 1] in "0123456789.,%/-"
            or target[-1].isdigit()
            and end < len(text)
            and text[end] in "0123456789.,%/-"
        ):
            continue
        indices = [i for i, piece in enumerate(pieces) for _ in piece]
        selected = ordered[indices[start] : indices[end - 1] + 1]
        bbox = (
            min(c["x0"] for c in selected),
            min(c["top"] for c in selected),
            max(c["x1"] for c in selected),
            max(c["bottom"] for c in selected),
        )
        matches[bbox] = bbox
    if len(matches) != 1:
        raise ValueError("cell_native_literal_unresolved")
    matched = next(iter(matches.values()))
    if strict._appearance_overlaps(page, matched):
        raise ValueError("cell_native_literal_unresolved")
    return matched


def _grid(graph, table):
    children = {
        e.source_id
        for e in graph.edges
        if e.relation == "table_parent" and e.target_id == table.source_id
    }
    origin = table.candidates[table.winner]
    grid = {}
    for block in graph.blocks:
        if block.kind != "table_cell" or block.source_id not in children:
            continue
        for index, candidate in enumerate(block.candidates):
            if (
                candidate.source.parser_run_id,
                candidate.source.physical_page,
                candidate.table_native_id,
            ) != (origin.source.parser_run_id, table.page_num, origin.source.source_native_id):
                continue
            key = candidate.row_number, candidate.column_number
            if key in grid:
                raise ValueError("duplicate_cell_origin")
            grid[key] = replace(block, winner=index)
    if not grid or len(grid) > 1024:
        raise ValueError("native_grid_unresolved")
    return grid


def _painted_grid(page, table, grid, nr, nc):
    rects = {
        tuple(round(r[k], 3) for k in ("x0", "top", "x1", "bottom"))
        for r in page.rects
        if _within((r["x0"], r["top"], r["x1"], r["bottom"]), table.bbox, 2)
        and r["x1"] - r["x0"] > 4
        and r["bottom"] - r["top"] > 4
    }
    if not rects or len(rects) > 4096:
        raise ValueError("native_grid_unresolved")
    heads = []
    for (row, col), cell in sorted(grid.items()):
        if row != 0 or not cell.raw_text.strip():
            continue
        found = []
        for box in rects:
            try:
                _literal(page, box, cell.raw_text, whole=True)
            except ValueError:
                continue
            found.append(box)
        if len(found) != 1:
            raise ValueError("header_native_owner_unresolved")
        heads.append((col, cell.candidates[cell.winner].column_span, found[0]))
    if len(heads) < 2:
        raise ValueError("header_native_owner_unresolved")
    head_y = heads[0][2][1], heads[0][2][3]
    if any((b[1], b[3]) != head_y for _, _, b in heads):
        raise ValueError("header_native_row_unresolved")
    if any(a[2][2] > b[2][0] + 0.01 for a, b in zip(heads, heads[1:])):
        raise ValueError("header_native_order_unresolved")
    columns = {}
    for col, span, box in heads:
        if type(span) is not int or span < 1:
            raise ValueError("header_native_owner_unresolved")
        for c in range(col, col + span):
            if c in columns:
                raise ValueError("header_native_owner_unresolved")
            columns[c] = box[0], box[2]
    if set(columns) == set(range(1, nc)):
        columns[0] = table.bbox[0], columns[1][0]
    if set(columns) != set(range(nc)):
        raise ValueError("header_native_owner_unresolved")
    alternatives = []
    for _, _, head in heads:
        ys = sorted(
            {
                (b[1], b[3])
                for b in rects
                if abs(b[0] - head[0]) < 0.02 and abs(b[2] - head[2]) < 0.02
            }
        )
        if len(ys) == nr and ys[0] == head_y and all(a[1] <= b[0] for a, b in zip(ys, ys[1:])):
            alternatives.append(ys)
    if not alternatives or any(rows != alternatives[0] for rows in alternatives):
        raise ValueError("native_grid_row_count_unresolved")
    return {
        (row, col): (x[0], y[0], x[1], y[1])
        for row, y in enumerate(alternatives[0])
        for col, x in columns.items()
    }


def _ruled_grid(page, table, grid, nr, nc):
    bounds = table.bbox
    # Partial strokes may form one rule, but a short rule from another card
    # cannot establish a common native row across the whole table.
    lines = [
        edge
        for edge in page.edges
        if abs(edge["top"] - edge["bottom"]) < 0.05
        and _within((edge["x0"], edge["top"] - 0.01, edge["x1"], edge["bottom"] + 0.01), bounds, 2)
    ]
    groups = {}
    for line in lines:
        groups.setdefault(round(line["top"], 2), []).append((line["x0"], line["x1"]))
    ys = []
    for y, spans in sorted(groups.items()):
        spans.sort()
        end = spans[0][1]
        covered = end - spans[0][0]
        gap = 0
        for left, right in spans[1:]:
            gap = max(gap, left - end)
            covered += max(0, right - max(end, left))
            end = max(end, right)
        if covered >= 0.95 * (bounds[2] - bounds[0]) and gap <= 3:
            ys.append(max(bounds[1], min(y, bounds[3])))
    if len(ys) != nr + 1 or any(a >= b for a, b in zip(ys, ys[1:])):
        raise ValueError("native_grid_row_count_unresolved")
    xs = sorted(
        {
            round(edge["x0"], 2)
            for edge in page.edges
            if abs(edge["x0"] - edge["x1"]) < 0.05
            and ys[0] - 2 <= edge["top"] < edge["bottom"] <= ys[1] + 2
            and edge["bottom"] - edge["top"] >= 0.8 * (ys[1] - ys[0])
            and bounds[0] + 2 < edge["x0"] < bounds[2] - 2
        }
    )
    if len(xs) != nc - 1:
        raise ValueError("header_native_owner_unresolved")
    xs = [bounds[0], *xs, bounds[2]]
    regions = {(r, c): (xs[c], ys[r], xs[c + 1], ys[r + 1]) for r in range(nr) for c in range(nc)}
    for (r, c), cell in grid.items():
        if r == 0 and cell.raw_text.strip():
            span = cell.candidates[cell.winner].column_span
            _literal(page, (xs[c], ys[0], xs[c + span], ys[1]), cell.raw_text, whole=True)
    return regions


def _owned_grid(page, graph, table):
    grid = _grid(graph, table)
    nr = max(r + b.candidates[b.winner].row_span for (r, c), b in grid.items())
    nc = max(c + b.candidates[b.winner].column_span for (r, c), b in grid.items())
    if not 2 <= nr <= 128 or not 2 <= nc <= 32:
        raise ValueError("native_grid_unresolved")
    try:
        return _painted_grid(page, table, grid, nr, nc), grid
    except ValueError:
        return _ruled_grid(page, table, grid, nr, nc), grid


def cell_proof(graph, source, refs, *, tenant_id):
    refs = tuple(refs)
    if sha256(source).hexdigest() != graph.source_sha256:
        return [dict(ref=asdict(r), status="unresolved", reason="source_invalid") for r in refs]
    records = previous.cell_proof(graph, source, refs, tenant_id=tenant_id)
    blocks = {b.source_id: b for b in graph.blocks}
    with pdfplumber.open(io.BytesIO(source)) as document:
        owners = {}
        for ref, record in zip(refs, records, strict=True):
            if record["reason"] not in {"cell_native_literal_unresolved", "cell_source_unresolved"}:
                continue  # A failed PB4 ownership check is never relaxed.
            try:
                table, parts = table_base._segments(graph, blocks[ref.source_id], ref, tenant_id)
                page = document.pages[ref.page_num - 1]
                if page.rotation or tuple(page.cropbox[:2]) != (0, 0):
                    raise ValueError("geometry_unsupported")
                if table.source_id not in owners:
                    owners[table.source_id] = _owned_grid(page, graph, table)
                regions, grid = owners[table.source_id]
                proof = []
                for cell, cell_ref in parts:
                    candidate = cell.candidates[cell.winner]
                    owner = regions[candidate.row_number, candidate.column_number]
                    matched = _literal(
                        page,
                        owner,
                        cell_ref.quote,
                        whole=cell_ref.char_start == 0 and cell_ref.char_end == len(cell.raw_text),
                    )
                    if cell.bbox is not None:
                        if not _within(matched, cell.bbox, 0.5) or not tables.tables._checked_ref(
                            graph, cell_ref, cell, tenant_id
                        ):
                            raise ValueError("cell_source_unresolved")
                    proof.append(
                        dict(
                            source_ref=asdict(cell_ref),
                            native_bbox=matched,
                            owner_bbox=owner,
                            row=candidate.row_number,
                            column=candidate.column_number,
                            recovered_selection=cell.bbox is None,
                        )
                    )
                from proofops.application.ingest.pb1_tables import observations

                context = " ".join(table.candidates[table.winner].context)
                observation = next(
                    (
                        o
                        for o in observations(table.normalized_text, context=context)
                        if o["start"] == ref.char_start and o["end"] == ref.char_end
                    ),
                    None,
                )
                if observation:
                    # Explicit comparison years are independently read in their
                    # own header columns; an unreadable header contributes no P2.
                    for comparison in observation["comparisons"]:
                        heads = [
                            b
                            for (r, c), b in grid.items()
                            if c == comparison["column"]
                            and r < observation["row"]
                            and b.raw_text.strip()
                            in (comparison["year"], comparison["year"] + "년")
                        ]
                        if len(heads) != 1:
                            continue
                        head = heads[0]
                        candidate = head.candidates[head.winner]
                        owner = regions[candidate.row_number, candidate.column_number]
                        try:
                            matched = _literal(page, owner, head.raw_text, whole=True)
                        except ValueError:
                            continue
                        if head.bbox is not None and not _within(matched, head.bbox, 0.5):
                            continue
                        proof.append(
                            dict(
                                source_ref=asdict(head.source_ref()),
                                native_bbox=matched,
                                owner_bbox=owner,
                                row=candidate.row_number,
                                column=candidate.column_number,
                                recovered_selection=head.bbox is None,
                            )
                        )
                record.update(
                    status="verified",
                    reason=None,
                    table_id=table.source_id,
                    cell_proofs=proof,
                    ownership="native-grid-pa9-v1",
                )
            except (ValueError, KeyError) as error:
                record["recovery_reason"] = str(error)
    return records


def _extend(baseline, graph, source, refs, *, tenant_id):
    blocks = {b.source_id: b for b in graph.blocks}
    indices = [i for i, r in enumerate(refs) if blocks[r.source_id].kind in {"table", "table_cell"}]
    proofs = (
        cell_proof(graph, source, [refs[i] for i in indices], tenant_id=tenant_id)
        if indices
        else []
    )
    records = deepcopy(baseline["records"])
    for index, proof in zip(indices, proofs, strict=True):
        records[index].update(status=proof["status"], reason=proof["reason"])
    receipt = dict(
        schema="claim_source_pa9_extension_v1",
        policy=claim_source_policy(),
        baseline_receipt=baseline,
        records=records,
        pb1_cell_proofs=proofs,
        **{
            k: baseline[k]
            for k in (
                "tenant_id",
                "document_version_id",
                "parse_manifest_id",
                "run_id",
                "source_sha256",
                "graph_sha256",
            )
        },
    )
    receipt["artifact_sha256"] = canonical_hash(receipt)
    return receipt


class Reader(v6.Reader):
    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        baseline = super().attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        return _extend(baseline, graph, source, refs, tenant_id=tenant_id)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        baseline = super().recompute_claim_receipt(
            receipt["baseline_receipt"], graph, source, tuple(refs), tenant_id=tenant_id
        )
        expected = _extend(baseline, graph, source, tuple(refs), tenant_id=tenant_id)
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected


def for_run(run_id):
    return Reader(PageOCRStore.from_env(), run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    if run_id is None:
        raise ValueError("OCR_RUN_REQUIRED")
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    from proofops.adapters.local.claim_source_verification import discovery_refs
    from proofops.application.evidence.span_citations import span_verified_graph, verify_source_ref

    refs = discovery_refs(discovery)
    checked = for_run(receipt["run_id"]).recompute_claim_receipt(
        receipt, graph, source, refs, tenant_id=tenant_id
    )
    approved = {
        (r["ref"]["source_id"], r["ref"]["char_start"], r["ref"]["char_end"])
        for r in checked["records"]
        if r["status"] == "verified"
    }
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in checked["records"]
        if r["status"] == "verified"
    )
    cells = tuple(
        replace(SourceRef(**c["source_ref"]), verification_state="verified")
        for p in checked["pb1_cell_proofs"]
        if p["status"] == "verified"
        for c in p["cell_proofs"]
        if not c.get("recovered_selection")
    )
    existing = tuple(getattr(graph, "verified_spans", ()))
    seen = {(r.source_id, r.char_start, r.char_end) for r in existing}
    scoped = span_verified_graph(
        graph,
        existing
        + tuple(r for r in (*newly, *cells) if (r.source_id, r.char_start, r.char_end) not in seen),
        checked["artifact_sha256"],
    )
    blocks = {b.source_id: b for b in graph.blocks}
    claims = []
    for claim in discovery.claims:
        table_claim = any(
            blocks[r.source_id].kind in {"table", "table_cell"} for r in claim.source_refs
        )
        if table_claim and not all(
            (r.source_id, r.char_start, r.char_end) in approved for r in claim.source_refs
        ):
            # A whole-table flag or an inherited span cannot override this
            # reader's failed native ownership proof for the selected row.
            claims.append(
                replace(
                    claim,
                    source_quality="unverified"
                    if claim.source_quality == "verified"
                    else claim.source_quality,
                    source_refs=tuple(
                        replace(r, verification_state="candidate")
                        if r.verification_state == "verified"
                        else r
                        for r in claim.source_refs
                    ),
                )
            )
            continue
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        sources = tuple(
            verify_source_ref(r, scoped, tenant_id=tenant_id) for r in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=sources)
            if sources and all(r.verification_state == "verified" for r in sources)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped
