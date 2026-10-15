"""QT1 selected-table coverage recovery. Literal candidates, never evidence approval.

Only checked parser origin cells and explicit spans supply row/column context.
Missing values remain literal; years come only from headers or uniquely linked
numbered notes. Provider chart transcriptions without an owned grid stay unknown.
"""

import re
from dataclasses import asdict

from proofops.application.ingest import j8_cells, w9_tables
from proofops.domain.provenance import canonical_hash

YEAR = re.compile(r"((?:19|20)\d{2})(?:\s*년)?(?:\s*(?:실적|성과))?(?:\d{1,2}\))?")
UNIT = re.compile(
    r"(?:천|만)?\s*(?:tCO[₂2](?:-?(?:eq|e))?|MWh|GJ|TJ|kWh|톤|t|kg|m[³3]|㎥|%|MW|대|개)"
    r"(?:\s*/\s*[^\d\t\n()]+)?",
    re.I,
)
VALUE = re.compile(r"(?:[+−-]?\d[\d,.]*(?:\s*(?:%|개|톤|kg|TJ|GJ|MWh|GWh))?(?:\d+\))?|[-–—]|N/A)")
ENV = re.compile(
    j8_cells.ENVIRONMENT
    + r"|폐전자|수자원|기후|넷제로|친환경|재활용|플라스틱|ISO\s*(?:14001|50001)",
    re.I,
)
ACTION = re.compile(
    j8_cells.ACTION_PATTERN
    + r"|최적화|개선|전환|절감|감소|기부|진행|승인|보고|취득|수립|감축|재이용"
)
FINANCIAL = re.compile(
    w9_tables.FINANCIAL.pattern + r"|매출액|영업이익|자산총계|부채총계|당기순이익"
)
NOTE = re.compile(r"(?<![0-9A-Za-z(])(\d{1,2})\)")
CAPTION_YEAR = re.compile(r"^(?:19|20)\d{2}년|\((?:19|20)\d{2}년\s*기준\)")
POLICY = dict(
    profile="selected-table-coverage-qt1-v1",
    base=j8_cells.POLICY,
    year=YEAR.pattern,
    unit=UNIT.pattern,
    value=VALUE.pattern,
    environment=ENV.pattern,
    action=ACTION.pattern,
    financial=FINANCIAL.pattern,
    note=NOTE.pattern,
    caption_year=CAPTION_YEAR.pattern,
    coverage="exact-owned-value-or-action-cell-spans; partial-row-never-counts-as-complete",
    inheritance="explicit-row/column-span-only; shared-year-only-target/actual-header",
    context="literal-cell-refs; uniquely-owned-caption-and-numbered-notes; no-global-years",
    figures="unlocated-or-no-owned-grid-deferred; no-generated-chart-values",
    authority="candidates-only; no-present/grades/verification; fresh-tagging-required",
    automatic="literal-measurement-or-risk-cells-only; narrative-gaps-remain-review-candidates",
    max_candidates=128,
)


def _cell(e):
    c = e["cell"]
    return dict(
        start=e["start"],
        end=e["end"],
        quote=e["text"],
        row=c["row"],
        column=c["column"],
        row_span=c["row_span"],
        column_span=c["column_span"],
        cell_source_id=c.get("source_id"),
        bbox=c.get("bbox"),
    )


def _covers(c, row=None, column=None):
    return (row is None or c["row"] <= row < c["row"] + c["row_span"]) and (
        column is None or c["column"] <= column < c["column"] + c["column_span"]
    )


def inventory(text, cells, *, context=()):
    """Inventory independently meaningful rows/cells without assigning a track."""
    rows = j8_cells.checked_grid(text, cells)
    if not rows or len(rows[0]["entries"]) < 2:
        return []
    first = rows[0]["entries"]
    # Headerless activity matrices have a literal bullet in their first data row.
    header_end = 0 if any("•" in e["text"] for e in first) else 1
    if len(rows) > 1 and any("SSP" in e["text"] for e in rows[1]["entries"]):
        header_end = 2
    headers = [
        _cell(e) for row in rows[:header_end] for e in row["entries"] if e["cell"] and e["text"]
    ]
    section = " ".join(c.removeprefix("section=") for c in context if c.startswith("section="))
    first_headers = [_cell(e) for e in first if e["cell"] and e["text"]]
    shared_years = [h for h in first_headers if YEAR.fullmatch(h["quote"].strip())]
    roles = [h["quote"] for h in first_headers if h not in shared_years]
    shared_year = (
        shared_years[0]
        if len(shared_years) == 1
        and roles
        and all(re.fullmatch(r"(?:목표|성과|실적)(?:\d+\))?", r.strip()) for r in roles)
        else None
    )
    timeline = bool(first_headers) and all(
        YEAR.fullmatch(h["quote"].strip()) for h in first_headers
    )
    result = []
    for row in rows[header_end:]:
        owned = [_cell(e) for e in row["entries"] if e["cell"] and e["text"].strip()]
        parents = [
            _cell(e)
            for prior in rows[: row["row"]]
            for e in prior["entries"]
            if e["cell"]
            and e["text"].strip()
            and e["cell"]["row"] >= header_end
            and _covers(e["cell"], row=row["row"])
        ]
        labels = [
            c
            for c in owned + parents
            if not VALUE.fullmatch(c["quote"].strip()) and not UNIT.fullmatch(c["quote"].strip())
        ]
        if not owned or not labels and not timeline:
            continue
        label_text = " ".join(c["quote"] for c in labels)
        if FINANCIAL.search(label_text) or re.fullmatch(r"(?:합계|총계)", label_text.strip()):
            continue
        # Section identifies the environmental table only; it cannot supply a value/year.
        environmental = ENV.search(" ".join([label_text, section, *[h["quote"] for h in headers]]))
        if not environmental:
            continue
        units = [c for c in owned + parents if UNIT.fullmatch(c["quote"].strip())]
        if not units:
            for c in labels:
                for m in re.finditer(r"\(([^()]+)\)", c["quote"]):
                    if UNIT.fullmatch(m[1]):
                        units.append(
                            c
                            | dict(
                                start=c["start"] + m.start(1), end=c["start"] + m.end(1), quote=m[1]
                            )
                        )
        values = []
        for c in owned:
            if c in units:
                continue
            scalar = bool(VALUE.fullmatch(c["quote"].strip()))
            risk = bool(
                re.fullmatch(
                    r"(?:매우\s*)?(?:낮음|중간|높음)(?:\s*~\s*(?:낮음|중간|높음))?",
                    c["quote"].strip(),
                )
            )
            if scalar and not (
                units
                or any(YEAR.fullmatch(h["quote"].strip()) for h in headers)
                or re.search(r"%|개|톤|kg|[MGkT]Wh|[TG]J", c["quote"])
            ):
                continue
            if not (scalar or risk or timeline and ACTION.search(c["quote"])):
                continue
            heads = [h for h in headers if _covers(h, column=c["column"])]
            year_heads = [h for h in heads if YEAR.fullmatch(h["quote"].strip())]
            if not year_heads and shared_year:
                year_heads = [shared_year]
            year_source = year_heads[0] if len(year_heads) == 1 else None
            values.append(
                c
                | dict(
                    year=YEAR.fullmatch(year_source["quote"].strip())[1] if year_source else None,
                    year_source=year_source,
                    column_headers=heads,
                )
            )
        if values and not timeline:
            targets = [(row["start"], row["end"], values)]
        else:
            targets = [
                (c["start"], c["end"], [v for v in values if v["start"] == c["start"]])
                for c in owned
                if len(c["quote"].strip()) >= 10
                and ACTION.search(c["quote"])
                and (
                    c["column"] > 0
                    or timeline
                    or any(
                        re.search(r"중량|부피|사용량", h["quote"]) and _covers(h, column=0)
                        for h in headers
                    )
                )
            ]
            # Board decisions and training records are complete dated rows, not date claims.
            if re.search(r"날짜", " ".join(h["quote"] for h in headers)) and ENV.search(label_text):
                targets = [(row["start"], row["end"], [])]
        for start, end, selected_values in targets:
            if not selected_values:
                for c in owned:
                    if not start <= c["start"] < c["end"] <= end:
                        continue
                    for match in re.finditer(
                        r"(?<![\d,.])\d[\d,.]*\s*(?:tCO[₂2](?:-?(?:eq|e))?|kg|m[³3]|GWh|MWh|TJ|GJ|톤|%)",
                        c["quote"],
                    ):
                        selected_values.append(
                            c
                            | dict(
                                start=c["start"] + match.start(),
                                end=c["start"] + match.end(),
                                quote=match[0],
                                year=None,
                                year_source=None,
                                column_headers=[
                                    h for h in headers if _covers(h, column=c["column"])
                                ],
                            )
                        )
            required = selected_values or [
                c for c in owned if start <= c["start"] < c["end"] <= end
            ]
            result.append(
                dict(
                    start=start,
                    end=end,
                    quote=text[start:end],
                    row=row["row"],
                    cells=owned,
                    headers=headers,
                    row_headers=parents,
                    values=selected_values,
                    unit=units[0] if len(units) == 1 else None,
                    required_cells=required,
                    binding_status="undetermined",
                    eligible_for_scoring=False,
                    recovery_eligible=bool(selected_values) and not timeline,
                    policy_sha256=canonical_hash(POLICY),
                )
            )
    if len(result) > POLICY["max_candidates"]:
        raise ValueError("EXTRACTION_SOURCE_SENTENCES_UNBOUNDED")
    return result


def reconcile(text, candidates, spans):
    """Keep selections unchanged and add only complete, nonoverlapping missing units."""
    result, coverage = list(spans), []
    for candidate in candidates:
        required = candidate["required_cells"]
        missing = [
            c
            for c in required
            if not any(
                s["kind"] == "claim" and s["char_start"] <= c["start"] < c["end"] <= s["char_end"]
                for s in spans
            )
        ]
        coverage.append(
            dict(
                start=candidate["start"],
                end=candidate["end"],
                status="covered"
                if not missing
                else "partial"
                if any(
                    s["char_start"] < candidate["end"] and candidate["start"] < s["char_end"]
                    for s in spans
                )
                else "missing",
                missing_cells=[dict(row=c["row"], column=c["column"]) for c in missing],
            )
        )
        if not missing or not candidate["recovery_eligible"]:
            continue
        # Never change a partially selected quote or add overlapping source claims.
        chunks = [dict(start=candidate["start"], end=candidate["end"])]
        if any(
            s["char_start"] < candidate["end"] and candidate["start"] < s["char_end"]
            for s in result
        ):
            chunks = missing
        for c in chunks:
            start, end = c["start"], c["end"]
            if any(s["char_start"] < end and start < s["char_end"] for s in result):
                continue
            result.append(
                dict(
                    char_start=start,
                    char_end=end,
                    quote=text[start:end],
                    kind="claim",
                    reason=None,
                    topic_ids=["environment"],
                )
            )
    return sorted(result, key=lambda s: s["char_start"]), coverage


def _reference(block, start=0, end=None):
    return asdict(
        block.source_ref(
            normalized_char_start=start,
            normalized_char_end=len(block.normalized_text) if end is None else end,
        )
    )


def table_context(table, graph):
    """Local captions and explicitly numbered notes; source location is never fabricated."""
    if table.bbox is None:
        return []
    tx0, ty0, tx1, ty1 = table.bbox
    width = tx1 - tx0
    peers = [b for b in graph.blocks if b.page_num == table.page_num and b.kind == "table"]
    nearby = [
        b
        for b in graph.blocks
        if b.page_num == table.page_num
        and b.kind in ("heading", "paragraph")
        and b.winner is not None
        and b.bbox is not None
        and b.quality in ("verified", "unverified")
    ]
    captions = [
        b
        for b in nearby
        if 0 <= ty0 - b.bbox[3] <= width * 0.12
        and tx0 <= b.bbox[0] < tx1
        and len(b.normalized_text) < 160
        and not NOTE.match(b.normalized_text)
        and not b.normalized_text.endswith("다.")
    ]
    result = []
    if captions:
        best = min(captions, key=lambda b: ty0 - b.bbox[3])
        owners = [
            t
            for t in peers
            if t.bbox is not None
            and t.bbox[0] <= best.bbox[0] < t.bbox[2]
            and 0 <= t.bbox[1] - best.bbox[3] <= width * 0.12
        ]
        if len(owners) == 1:
            result.append(dict(role="table_caption", source_ref=_reference(best)))
    markers = set(NOTE.findall(table.normalized_text))
    for b in nearby:
        positions = list(NOTE.finditer(b.normalized_text))
        if not positions or positions[0].start() != 0:
            continue
        for index, match in enumerate(positions):
            end = (
                positions[index + 1].start()
                if index + 1 < len(positions)
                else len(b.normalized_text)
            )
            marker = match[1]
            below = 0 <= b.bbox[1] - ty1 <= width * 0.25 and max(tx0, b.bbox[0]) < min(
                tx1, b.bbox[2]
            )
            owners = [t for t in peers if marker in set(NOTE.findall(t.normalized_text))]
            # A header's unique marker also supports notes placed in the other column.
            explicit = marker in markers and len(owners) == 1
            if below or explicit:
                result.append(
                    dict(
                        role="table_footnote",
                        marker=marker,
                        source_ref=_reference(b, match.start(), end),
                    )
                )
    return result


def candidates_for(table, graph):
    if (
        table.kind != "table"
        or table.winner is None
        or table.bbox is None
        or table.quality not in ("verified", "unverified")
    ):
        return []
    cells = j8_cells.graph_cells(table, graph)
    context = table_context(table, graph)
    rows = inventory(table.normalized_text, cells, context=table.candidates[table.winner].context)
    for row in rows:
        row["table_id"] = table.source_id
        row["source_ref"] = _reference(table, row["start"], row["end"])
        row["context_sources"] = context
        if row["unit"]:
            row["unit"]["source_ref"] = _reference(table, row["unit"]["start"], row["unit"]["end"])
        captions = [
            c
            for c in context
            if c["role"] == "table_caption"
            and CAPTION_YEAR.search(c["source_ref"]["quote"])
            and len(re.findall(r"(?:19|20)\d{2}", c["source_ref"]["quote"])) == 1
        ]
        if len(captions) == 1:
            for value in row["values"]:
                if value["year"] is None:
                    value["year"] = re.search(
                        r"(?:19|20)\d{2}", captions[0]["source_ref"]["quote"]
                    )[0]
                    value["year_source"] = captions[0]
        for cell in row["cells"] + row["headers"] + row["row_headers"] + row["values"]:
            cell["source_ref"] = _reference(table, cell["start"], cell["end"])
        # One explicitly applicable operating-year note can clarify a missing year.
        notes = [
            c
            for c in context
            if c["role"] == "table_footnote"
            and re.search(r"(?:19|20)\d{2}년\s*(?:운영\s*)?실적\s*기준", c["source_ref"]["quote"])
        ]
        if len(notes) == 1:
            note = notes[0]
            for value in row["values"]:
                header_marked = any(
                    note["marker"] in NOTE.findall(h["quote"]) for h in value["column_headers"]
                )
                if header_marked and value["year"] is None:
                    value["year"] = re.search(r"(?:19|20)\d{2}", note["source_ref"]["quote"])[0]
                    value["year_source"] = note
    return rows
