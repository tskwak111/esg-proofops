"""Conservative native-number and independently parsed row agreement checks.

Agreement is a parser diagnostic, never a financial fact or source approval.
"""

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import replace
from uuid import UUID, uuid5

from proofops.application.ingest.graph_fusion import QualityIssue, fuse_candidates

NUMBER = re.compile(r"(?<![\d.,])[+−-]?\d+(?:,\d{3})*(?:\.\d+)?%?(?![\d.,])")


def compact(text):
    return "".join(unicodedata.normalize("NFC", text).split())


def numbers(text):
    # Keep signs, decimal points, percent and magnitude; no fuzzy numeric matching.
    return Counter(NUMBER.findall(unicodedata.normalize("NFKC", text)))


def key(block):
    return block.source.parser_run_id + "/" + block.source.source_native_id


def overlap(a, b):
    if a is None or b is None:
        return 0
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    denominator = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return area / denominator if denominator > 0 else 0


def native_check(block, raw_page):
    required = numbers(block.source.raw_text)
    if not required:
        return True
    box = block.source.native_bbox
    if box is None:
        return False
    # Only glyph centres inside this exact native region, not anywhere on the page.
    chars = []
    for char in raw_page["chars"]:
        x0, y0, x1, y1 = char["bbox"]
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        chars.append(
            char["text"] if box[0] - 1 <= x <= box[2] + 1 and box[1] - 1 <= y <= box[3] + 1 else " "
        )
    return not (required - numbers("".join(chars)))


def _rows(batch):
    tables = {b.source.source_native_id: b for b in batch.blocks if b.kind == "table"}
    grouped = defaultdict(list)
    for block in batch.blocks:
        if block.kind == "table_cell":
            grouped[(block.table_native_id, block.row_number)].append(block)
    rows = []
    for (table_id, _), cells in grouped.items():
        table = tables.get(table_id)
        if table is None:
            continue
        cells.sort(key=lambda c: (c.column_number, c.source.source_native_id))
        # Full table header/order is deliberately strict: ambiguity stays reviewable.
        table_rows = sorted(r for t, r in grouped if t == table_id)
        header = sorted(grouped[(table_id, table_rows[0])], key=lambda c: c.column_number)
        signature = (
            tuple((compact(c.source.raw_text), c.column_span, c.row_span) for c in header),
            tuple((compact(c.source.raw_text), c.column_span, c.row_span) for c in cells),
        )
        rows.append((table, cells, signature))
    return rows


def compare(local, other, pages, check=None):
    """Bidirectional checks prevent missing/extra numeric rows from becoming consensus."""
    if local.parser_family == other.parser_family:
        raise ValueError("INDEPENDENT_PARSER_FAMILY_REQUIRED")
    if check is None:

        def check(block):
            return native_check(block, pages[str(block.source.physical_page)])

    result = {}
    for left, right in ((local, other), (other, local)):
        right_rows = _rows(right)
        for table, cells, signature in _rows(left):
            matches = [
                rc
                for rt, rc, rs in right_rows
                if table.source.physical_page == rt.source.physical_page
                and signature == rs
                and overlap(table.bbox, rt.bbox) >= 0.5
                and all(
                    a.bbox and b.bbox and overlap(a.bbox, b.bbox) >= 0.5
                    for a, b in zip(cells, rc, strict=True)
                )
            ]
            good = len(matches) == 1 and all(check(c) for c in cells + matches[0])
            for cell in cells:
                result[key(cell)] = "consensus" if good else "parse_conflict"
        for block in left.blocks:
            if block.kind in {"table_cell", "table", "table_row", "figure", "unknown"}:
                continue
            if not numbers(block.source.raw_text):
                continue
            matches = [
                b
                for b in right.blocks
                if b.kind == block.kind
                and b.source.physical_page == block.source.physical_page
                and compact(b.source.raw_text) == compact(block.source.raw_text)
                and overlap(b.bbox, block.bbox) >= 0.5
            ]
            good = len(matches) == 1 and all(check(b) for b in [block, *matches])
            result[key(block)] = "consensus" if good else "parse_conflict"
    return result


def audit(batches, pages, *, crosscheck=True):
    checked = {}

    def check(block):
        identity = (block.source.physical_page, block.source.native_bbox, block.source.raw_text)
        if identity not in checked:
            checked[identity] = native_check(block, pages[str(block.source.physical_page)])
        return checked[identity]

    local = batches[0]
    standard = [b for b in batches if b.parser_name == "upstage_async_standard"]
    enhanced = [b for b in batches if b.parser_name == "upstage_async_enhanced"]
    decisions = {}
    for provider in standard + enhanced:
        selected = {b.source.physical_page for b in provider.blocks}
        subset = replace(
            local,
            blocks=tuple(b for b in local.blocks if b.source.physical_page in selected),
            edges=(),
        )
        decisions.update(compare(subset, provider, pages, check))
    enhanced_pages = {b.source.physical_page for batch in enhanced for b in batch.blocks}
    figures = [b for batch in batches for b in batch.blocks if b.kind == "figure"]
    records = []
    for batch in batches:
        for block in batch.blocks:
            page = block.source.physical_page
            reason = decisions.get(key(block), "not_numeric")
            if numbers(block.source.raw_text) and block.kind not in {
                "table",
                "table_row",
                "unknown",
            }:
                reason = decisions.get(key(block), "crosscheck_missing")
            if block.kind == "table_cell":
                reason = decisions.get(key(block), "crosscheck_missing")
            if not check(block):
                reason = "numeric_not_in_native_region"
            if "table_grid_overlap" in block.context:
                reason = "table_grid_overlap"
            if any(ord(c) < 32 and not c.isspace() for c in block.source.raw_text):
                reason = "invalid_text_control_character"
            if block.kind == "figure" or any(
                f.source.physical_page == page and overlap(block.bbox, f.bbox) >= 0.8
                for f in figures
            ):
                reason = "chart_requires_vision_review"
            if batch.parser_name == "upstage_async_standard" and page in enhanced_pages:
                reason = "superseded_by_enhanced"
            records.append(
                dict(key=key(block), page=page, reason=reason, crosscheck_enabled=crosscheck)
            )
    # A container must not leak rejected cell text into extraction.
    states = {r["key"]: r for r in records}
    for batch in batches:
        for block in batch.blocks:
            if block.table_native_id and states[key(block)]["reason"] not in {
                "consensus",
                "not_numeric",
            }:
                parent_key = batch.parser_run_id + "/" + block.table_native_id
                if parent_key in states:
                    states[parent_key]["reason"] = "parse_conflict"
    return records


def guarded_graph(batches, records, *, tenant_id, pages=None):
    enhanced_pages = {
        b.source.physical_page
        for batch in batches
        if batch.parser_name == "upstage_async_enhanced"
        for b in batch.blocks
    }
    active = []
    for batch in batches:
        if batch.parser_name == "upstage_async_standard":
            kept = tuple(b for b in batch.blocks if b.source.physical_page not in enhanced_pages)
            ids = {b.source.source_native_id for b in kept}
            batch = replace(
                batch,
                blocks=kept,
                edges=tuple(
                    e
                    for e in batch.edges
                    if e.source_native_id in ids and e.target_native_id in ids
                ),
            )
        active.append(batch)
    graph = fuse_candidates(tuple(active), tenant_id=tenant_id, fusion_version=4)
    states = {r["key"]: r for r in records}
    blocks, issues = [], list(graph.issues)
    for block in graph.blocks:
        reasons = sorted(
            {
                states[key(c)]["reason"]
                for c in block.candidates
                if key(c) in states and states[key(c)]["reason"] not in {"consensus", "not_numeric"}
            }
        )
        if reasons:
            block = replace(block, winner=None, quality="conflicted")
            issues.append(
                QualityIssue(
                    str(uuid5(UUID(graph.parse_manifest_id), "docling-guard:" + block.source_id)),
                    "parse_conflict",
                    block.page_num,
                    (block.source_id,),
                    "open",
                    "; ".join(reasons),
                )
            )
        elif any(states.get(key(c), {}).get("reason") == "consensus" for c in block.candidates):
            issues.append(
                QualityIssue(
                    str(
                        uuid5(UUID(graph.parse_manifest_id), "docling-consensus:" + block.source_id)
                    ),
                    "parser_consensus",
                    block.page_num,
                    (block.source_id,),
                    "resolved",
                    "Independent parser agreement; source and semantic approval remain separate.",
                )
            )
        blocks.append(block)
    if pages is not None:
        for page, record in pages.items():
            if not any(c["text"].strip() for c in record["chars"]):
                issues.append(
                    QualityIssue(
                        str(
                            uuid5(UUID(graph.parse_manifest_id), "docling-unreadable:" + str(page))
                        ),
                        "no_extractable_text",
                        int(page),
                        (),
                        "unreadable",
                        "No text extracted; absence of evidence is not established.",
                    )
                )
    return replace(graph, blocks=tuple(blocks), issues=tuple(issues))
