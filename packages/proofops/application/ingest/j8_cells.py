"""Opt-in literal cell candidates. Structure is checked; evidence stays unapproved."""

import re
import unicodedata

from proofops.application.ingest import w9_tables as w9
from proofops.application.ingest.j3_recall import ACTION, BULLET, _trim
from proofops.application.ingest.table_row_candidates import row_candidates

PROFILE = "j8-owned-cell-candidates-v1"
APPLIED = r"(?:19|20)\d{2}\s*년\s*적용"
CONTEXT = r"(?:^|\n)\s*[*※]\s*(?:적용\s*기술|산정\s*방법|방법론|주석|참고|단위)\s*[:：]"
NAMED_IMPLEMENTATION = r"[A-Z]{2,}[A-Za-z0-9]*.*(?:개발|적용)"
ACTION_PATTERN = ACTION + r"|확대|사용|활용|발전"
ENVIRONMENT = w9.ENV.pattern + r"|데이터센터|냉각|냉방|공조|서버.*폐열|제설"
PLAN_HEADER = r"^(?:세부\s*)?개선\s*과제$|^추진\s*과제$|^계획$"
STATUS_HEADER = r"^달성\s*현황$|^이행\s*현황$|^성과$"
POLICY = dict(
    profile=PROFILE,
    action=ACTION_PATTERN,
    environment_pattern=ENVIRONMENT,
    applied=APPLIED,
    context=CONTEXT,
    named_implementation=NAMED_IMPLEMENTATION,
    boundary="explicit-nonoverlapping-origin-grid; exact-cell-and-bullet-offsets",
    headers="context-only-except-dated-implemented-means-in-application-effect-matrix",
    introductions="context-only-with-bullets-except-named-developed-applied-systems",
    duplicates="same-row-plan/status-columns-identical-body-terminal-completion-prefers-status",
    plan_header=PLAN_HEADER,
    status_header=STATUS_HEADER,
    environment="own-cell-or-explicit-same-row-or-spanned-column; never-blank-forward-fill",
    numeric="w9-latest-year-observations-only; prior-years-comparison-only; no-footnote-values",
    coordinates="same-parser-table-edge/page/grid; preserve-unlocated; reject-invalid",
    roles="first-column-action-vs-bullet-vs-dated-means; selection-hints-only",
    evidence="native-v10-unchanged; no-parent-verified/present/grade-credit",
    max_candidates=64,
)


def checked_grid(text, cells):
    if not cells:
        if text.strip():
            raise ValueError("J8_GRID_MISSING")
        return []
    occupied = set()
    for c in cells:
        r, col, rs, cs = (c[k] for k in ("row", "column", "row_span", "column_span"))
        if (
            any(type(v) is not int for v in (r, col, rs, cs))
            or min(r, col) < 0
            or min(rs, cs) < 1
            or r + rs > 500
            or col + cs > 100
        ):
            raise ValueError("J8_GRID_INVALID")
        for position in ((y, x) for y in range(r, r + rs) for x in range(col, col + cs)):
            if position in occupied:
                raise ValueError("J8_GRID_OVERLAP")
            occupied.add(position)
    return w9.grid(text, cells)


def graph_cells(table, graph):
    cells = w9.graph_cells(table, graph)
    origin = table.candidates[table.winner]
    blocks = {b.source_id: b for b in graph.blocks}
    for cell in cells:
        block = blocks[cell["source_id"]]
        candidates = [
            c
            for c in block.candidates
            if (
                c.source.parser_run_id,
                c.source.physical_page,
                c.table_native_id,
                c.row_number,
                c.column_number,
            )
            == (
                origin.source.parser_run_id,
                table.page_num,
                origin.source.source_native_id,
                cell["row"],
                cell["column"],
            )
        ]
        if len(candidates) != 1:
            raise ValueError("J8_CELL_OWNERSHIP_INVALID")
        c = candidates[0]
        if (
            c.has_invalid_geometry
            or c.source.document_version_id != graph.document_version_id
            or c.source.parse_manifest_id != graph.parse_manifest_id
        ):
            raise ValueError("J8_CELL_GEOMETRY_INVALID")
        box, parent = c.bbox, origin.bbox
        if (
            box is not None
            and parent is not None
            and not (
                parent[0] <= box[0] < box[2] <= parent[2]
                and parent[1] <= box[1] < box[3] <= parent[3]
            )
        ):
            raise ValueError("J8_CELL_GEOMETRY_INVALID")
        cell["bbox"] = box
        cell["location_quality"] = "located" if box is not None else "unlocated"
    checked_grid(table.normalized_text, cells)
    return cells


def observations(text, *, cells=None, context="", limit=24):
    # Numeric observations keep the existing literal whole row, value/unit/year
    # source guard, and comparison metadata. Generic cell candidates never fill
    # gaps in a year grid that failed to yield a usable observation.
    if cells is not None:
        checked_grid(text, cells)
    return w9.observations(text, cells=cells, context=context, limit=limit)


def observations_for(table, graph):
    return observations(table.normalized_text, cells=graph_cells(table, graph))


def _context(e, source_id, role):
    return dict(
        role=role, source_id=source_id, char_start=e["start"], char_end=e["end"], text=e["text"]
    )


def cell_entries(text, cells, *, source_id):
    rows = checked_grid(text, cells)
    if not rows:
        return []
    if any(w9.legacy.YEAR.fullmatch(e["text"].strip()) for row in rows[:4] for e in row["entries"]):
        return []
    plan_columns = {
        e["column"] for e in rows[0]["entries"] if re.fullmatch(PLAN_HEADER, e["text"].strip())
    }
    status_columns = {
        e["column"] for e in rows[0]["entries"] if re.fullmatch(STATUS_HEADER, e["text"].strip())
    }
    applied = {e["column"] for e in rows[0]["entries"] if re.search(APPLIED, e["text"])}
    labels = {row["entries"][0]["text"].strip() for row in rows[1:]}
    matrix = bool(applied) and "개선방안" in labels and bool(labels & {"효과", "(예상) 효과"})
    result = []
    for row in rows:
        for e in row["entries"]:
            if not e["cell"] or not e["text"].strip() or re.search(CONTEXT, e["text"]):
                continue
            if matrix:
                if e["column"] not in applied or (
                    row["row"] != 0
                    and row["entries"][0]["text"].strip() not in {"효과", "(예상) 효과"}
                ):
                    continue
            elif row["row"] == 0:
                continue
            # Only explicit spans cover a column/row; an earlier blank origin
            # does not authorize inheritance from an unrelated preceding row.
            heads = [
                h
                for h in rows[0]["entries"]
                if h["cell"]
                and h["text"]
                and h["column"] <= e["column"]
                and e["column"] + e["cell"]["column_span"] <= h["column"] + h["cell"]["column_span"]
                and h is not e
            ]
            parents = [_context(h, source_id, "same_source_column_header") for h in heads]
            row_heads = [
                h
                for previous in rows[: row["row"] + 1]
                for h in previous["entries"][: e["column"]]
                if h["cell"]
                and h["text"]
                and h["cell"]["column"] == 0
                and h["cell"]["row"] <= row["row"]
                and row["row"] + e["cell"]["row_span"] <= h["cell"]["row"] + h["cell"]["row_span"]
                and "\n" not in h["text"]
            ]
            parents += [_context(h, source_id, "same_source_row_label") for h in row_heads]
            bullets = [m.start() for m in re.finditer(BULLET, e["text"])]
            if bullets and e["text"][: bullets[0]].strip():
                a, b = _trim(text, e["start"], e["start"] + bullets[0])
                parents.append(
                    dict(
                        role="same_source_cell_label",
                        source_id=source_id,
                        char_start=a,
                        char_end=b,
                        text=text[a:b],
                    )
                )
            bounds = sorted(set([0, *bullets, len(e["text"])]))
            for a, b in zip(bounds, bounds[1:]):
                start, end = _trim(text, e["start"] + a, e["start"] + b)
                value = text[start:end]
                if len(value.strip("• \t\n")) < 8:
                    continue
                intro = bool(bullets and a == 0 and b == bullets[0])
                if intro and not re.search(NAMED_IMPLEMENTATION, value):
                    continue
                eligible = bool(row_candidates(value, kind="table_cell"))
                environmental = re.search(
                    ENVIRONMENT, " ".join([value, *[p["text"] for p in parents]]), re.I
                )
                if (
                    not matrix
                    and not eligible
                    and not (environmental and re.search(ACTION_PATTERN, value))
                ):
                    continue
                if not re.search(ACTION_PATTERN, value) and not eligible:
                    continue
                result.append(
                    dict(
                        sentence_id=f"{source_id}:{PROFILE}:{start}:{end}",
                        text=value,
                        char_start=start,
                        char_end=end,
                        row=row["row"],
                        column=e["column"],
                        cell_source_id=e["cell"].get("source_id"),
                        candidate_role=(
                            "dated_implemented_means"
                            if matrix and row["row"] == 0
                            else "self_contained_kpi_action"
                            if e["column"] == 0 and not bullets
                            else "cell_item"
                        ),
                        parent_context=parents,
                        binding_status="undetermined",
                    )
                )
    # Only exact same-row duplicates differing by a terminal completion marker.
    # Different facilities, years, quantities or conditions remain independent.
    completed = {
        (e["row"], unicodedata.normalize("NFC", e["text"].strip("• \t\n")[:-2]).strip())
        for e in result
        if e["column"] in status_columns and e["text"].endswith("완료")
    }
    return [
        e
        for e in result
        if e["column"] not in plan_columns
        or (e["row"], unicodedata.normalize("NFC", e["text"].strip("• \t\n"))) not in completed
    ]
