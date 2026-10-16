"""W9 same-table observations and literal cell spans; no evidence admission.

Metric paths are display metadata. Only explicit spans and narrowly labelled
regional/intensity subgroups contribute parents; blank cells are never filled.
"""

import re
import unicodedata

from proofops.application.ingest import pb1_tables as legacy
from proofops.domain.provenance import canonical_hash

PROFILE = "pb1-w9-v1"
UNIT = re.compile(
    r"(?:천|만)?(?:tCO[₂2](?:eq|e)?|MWh|GJ|TJ|kWh|톤|t|kg|m[³3]|㎥|%|MW|대)"
    r"(?:/(?:백만원|천원|원|대|년|연|매출액|생산량))?",
    re.I,
)
ENV = re.compile(legacy.ENV.pattern + r"|대기오염|수질오염|질소산화|황산화|COD|TOC|Dust", re.I)
FINANCIAL = re.compile(r"자본변동표|자본잉여금|이익잉여금|지배기업 소유주지분|금융자산")
POLICY = dict(
    legacy.POLICY,
    profile=PROFILE,
    units=UNIT.pattern,
    environment="same-table-header-and-labels; section-alone-never-licenses-financial-table",
    environment_pattern=ENV.pattern,
    financial_pattern=FINANCIAL.pattern,
    boundary="explicit-parser-grid-for-multiline-cells; legacy-single-line-rows",
    context_cells="labelled-applied-technology-cell-is-context-only",
    cell_claims="explicit-bullet-boundaries-within-cell; internal-wraps-preserved",
    cell_eligibility=(
        "existing-row-policy-with-cell-intro/non-numeric-row-label; no-evidence-credit"
    ),
    metric="display-only: explicit-row/column-spans; regional/intensity-subgroups; no-blank-fill",
    figures="no-generic-claims-from-provider-chart-tables; independent-reader-required",
)


def grid(text, cells=None):
    """Reconstruct the exact sparse origin grid, retaining literal raw offsets."""
    if cells is None:
        cells = [
            dict(text=value, row=r, column=c, row_span=1, column_span=1)
            for r, line in enumerate(text.split("\n"))
            for c, value in enumerate(line.split("\t"))
        ]
    if not cells:
        return []
    nr = max(c["row"] + c["row_span"] for c in cells)
    nc = max(c["column"] + c["column_span"] for c in cells)
    origins = {(c["row"], c["column"]): c for c in cells}
    if len(origins) != len(cells) or nr > 500 or nc > 100:
        raise ValueError("W9_GRID_INVALID")
    rows, raw = [], ""
    for r in range(nr):
        entries, start = [], len(raw)
        for col in range(nc):
            cell = origins.get((r, col))
            value = cell["text"] if cell else ""
            begin = len(raw)
            raw += value
            entries.append(dict(text=value, start=begin, end=len(raw), cell=cell, column=col))
            if col + 1 < nc:
                raw += "\t"
        rows.append(dict(row=r, start=start, end=len(raw), entries=entries))
        if r + 1 < nr:
            raw += "\n"
    if raw != text:
        raise ValueError("W9_GRID_TEXT_MISMATCH")
    return rows


def graph_cells(table, graph):
    """Keep every matching parser origin, including fused identical cells."""
    origin = table.candidates[table.winner]
    ids = {
        e.source_id
        for e in graph.edges
        if e.relation == "table_parent" and e.target_id == table.source_id
    }
    cells = []
    for block in graph.blocks:
        if block.source_id not in ids or block.kind != "table_cell":
            continue
        for c in block.candidates:
            if (c.source.parser_run_id, c.source.physical_page, c.table_native_id) == (
                origin.source.parser_run_id,
                table.page_num,
                origin.source.source_native_id,
            ):
                cells.append(
                    dict(
                        text=unicodedata.normalize("NFC", c.source.raw_text),
                        row=c.row_number,
                        column=c.column_number,
                        row_span=c.row_span,
                        column_span=c.column_span,
                        source_id=block.source_id,
                    )
                )
    return cells


def _unit(value):
    return UNIT.fullmatch("".join(value.split())) is not None


def _parents(rows, row, first_year):
    selected = []
    for parent in rows[: row + 1]:
        for e in parent["entries"][:first_year]:
            c = e["cell"]
            if c and c["text"] and c["row"] <= row < c["row"] + c["row_span"]:
                if not _unit(c["text"]) and not legacy.HEADER.fullmatch(c["text"].strip()):
                    selected.append(e)
    # Same-column labelled subgroups only; these are display metadata, not refs.
    leaves = rows[row]["entries"][:first_year]
    for leaf in leaves:
        label = leaf["text"].strip()
        regional = label in {"국내", "해외"}
        intensity = label.startswith("원단위")
        if not (regional or intensity):
            continue
        for previous in reversed(rows[1:row]):
            p = previous["entries"][leaf["column"]]
            if not p["text"].strip() or p["text"].strip() in {"국내", "해외"}:
                continue
            if (
                regional
                and "Scope" in p["text"]
                or intensity
                and re.search(r"Dust|COD|TOC|NOx|SOx|VOCs|HAPs|SS|T-N|T-P", p["text"], re.I)
            ):
                selected.append(p)
            break
    return sorted(selected, key=lambda e: (e["column"], e["start"]))


def observations(text, *, cells=None, context="", limit=24):
    # Legacy native readers ask whether a generic span is a numeric observation
    # without passing its grid. A multiline non-year table is not a year grid;
    # never reinterpret its internal wraps as structural rows.
    if cells is None and not any(
        legacy.YEAR.fullmatch(cell.strip())
        for line in text.split("\n")[:4]
        for cell in line.split("\t")
    ):
        return []
    rows = grid(text, cells)
    years, header_end = {}, -1
    for row in rows[:4]:
        for e in row["entries"]:
            if legacy.YEAR.fullmatch(e["text"].strip()):
                year = re.search(r"\d{4}", e["text"])[0]
                col = e["column"]
                if col in years and years[col]["year"] != year:
                    return []
                years[col] = dict(year=year, row=row["row"], column=col, quote=e["text"])
                header_end = max(header_end, row["row"])
    if not years or len({h["year"] for h in years.values()}) != len(years):
        return []
    current, first = max(years, key=lambda col: years[col]["year"]), min(years)
    labels = " ".join(e["text"] for row in rows for e in row["entries"][:first])
    if FINANCIAL.search(labels) or not ENV.search(labels):
        return []
    results = []
    for row in rows[header_end + 1 :]:
        es = row["entries"]
        units = [e for e in es[:first] if _unit(e["text"])]
        local = [e for e in es[:first] if e["text"].strip() and not _unit(e["text"])]
        value = es[current]["text"].strip()
        if (
            len(units) != 1
            or not local
            or legacy.FOOTNOTE.match(local[0]["text"])
            or legacy.HEADER.fullmatch(local[0]["text"].strip())
            or not legacy.NUMERIC.fullmatch(value)
            or legacy.YEAR.fullmatch(value)
        ):
            continue
        parents = _parents(rows, row["row"], first)
        column_parents = [
            e
            for head in rows[: header_end + 1]
            for e in head["entries"]
            if (c := e["cell"])
            and c["text"]
            and c["column"] <= current < c["column"] + c["column_span"]
            and not legacy.YEAR.fullmatch(c["text"].strip())
            and not legacy.HEADER.fullmatch(c["text"].strip())
            and not _unit(c["text"])
        ]
        parents += column_parents
        path = list(dict.fromkeys(e["text"] for e in parents))
        results.append(
            dict(
                start=row["start"],
                end=row["end"],
                quote=text[row["start"] : row["end"]],
                row=row["row"],
                value_column=current,
                value=value,
                unit=units[0]["text"],
                metric=" / ".join(path),
                metric_path=path,
                column_path=[e["text"] for e in column_parents],
                metric_path_sources=[
                    dict(
                        row=e["cell"]["row"],
                        column=e["column"],
                        start=e["start"],
                        end=e["end"],
                        quote=e["text"],
                    )
                    for e in parents
                ],
                metric_path_usage="display_only_not_evidence",
                year=years[current]["year"],
                year_header=years[current],
                comparisons=[
                    dict(year=h["year"], value=es[col]["text"], column=col)
                    for col, h in sorted(years.items())
                    if col != current
                ],
                policy_sha256=canonical_hash(POLICY),
            )
        )
    return results[: min(limit, POLICY["max_rows_per_table"])]


def observations_for(table, graph):
    context = " ".join(table.candidates[table.winner].context)
    if PROFILE not in table.candidates[table.winner].context:
        return legacy.observations(table.normalized_text, context=context)
    return observations(table.normalized_text, cells=graph_cells(table, graph), context=context)


def cell_entries(text, cells, *, source_id):
    """Generic non-time-series candidates stay inside one explicit parser cell."""
    from proofops.application.ingest.table_row_candidates import row_candidates

    rows, entries = grid(text, cells), []
    for row in rows[1:]:
        for e in row["entries"]:
            if not e["cell"] or not e["text"]:
                continue
            if re.search(r"(?:^|\n)\s*[*※]\s*적용\s*기술\s*[:：]", e["text"]):
                continue
            heads = [
                h
                for h in rows[0]["entries"]
                if h["cell"] and h["column"] <= e["column"] < h["column"] + h["cell"]["column_span"]
            ]
            axes = tuple(h["text"] for h in heads)
            bullets = [m.start() for m in re.finditer(r"(?m)^[ \t]*•", e["text"])]
            bounds = [0, *bullets, len(e["text"])] if bullets else [0, len(e["text"])]
            intro = e["text"][: bullets[0]].strip() if bullets else ""
            row_label = row["entries"][0]
            row_context = (
                row_label["text"]
                if e["column"] > 0
                and "\n" not in row_label["text"]
                and not re.search(r"\d", row_label["text"])
                and ENV.search(row_label["text"])
                else ""
            )
            parent = [
                dict(
                    role="same_source_column_header",
                    source_id=source_id,
                    char_start=h["start"],
                    char_end=h["end"],
                    text=h["text"],
                )
                for h in heads
                if h["text"]
            ]
            if intro:
                parent.append(
                    dict(
                        role="same_source_cell_label",
                        source_id=source_id,
                        char_start=e["start"],
                        char_end=e["start"] + len(intro),
                        text=intro,
                    )
                )
            if row_context:
                parent.append(
                    dict(
                        role="same_source_row_label",
                        source_id=source_id,
                        char_start=row_label["start"],
                        char_end=row_label["end"],
                        text=row_context,
                    )
                )
            for a, b in zip(bounds, bounds[1:]):
                fragment = e["text"][a:b]
                left = a + len(fragment) - len(fragment.lstrip())
                right = b - len(fragment) + len(fragment.rstrip())
                value = e["text"][left:right]
                if not value:
                    continue
                eligible = row_candidates(value, kind="table_cell", table_context=axes)
                label = intro or row_context
                if not eligible and value.startswith("•") and label:
                    eligible = row_candidates(
                        label + "\t" + value, kind="table_row", table_context=axes
                    )
                if not eligible:
                    continue
                start, end = e["start"] + left, e["start"] + right
                entries.append(
                    dict(
                        sentence_id=f"{source_id}:{PROFILE}:{start}:{end}",
                        text=text[start:end],
                        char_start=start,
                        char_end=end,
                        row=row["row"],
                        column=e["column"],
                        parent_context=parent,
                        binding_status="undetermined",
                    )
                )
    return entries
