"""PB1 literal row observations. Comparisons stay source context, not extra claims.

Selection is Python only; the LLM still classifies/tags and never assigns grades.
No text is synthesized: quotes are complete contiguous rows of the parser grid.
"""

import re

from proofops.domain.provenance import canonical_hash

PROFILE = "pb1-v1"
POLICY = dict(
    profile=PROFILE,
    year="latest-explicit-observed-year-column; no deadline columns",
    quote="literal-whole-row; primary=current-year; older-values=comparison-context",
    numeric="whole-cell; reject footnote suffix, missing values and header years",
    headers="same-grid-spans; no neighbouring-row borrowing",
    max_rows_per_table=24,
    priority="source-row-order",
    classification="LLM-only",
)
NUMERIC = re.compile(r"[+−-]?\d+(?:[,.]\d+)*%?")
YEAR = re.compile(r"(?:19|20)\d{2}(?:\s*년)?")
UNIT = re.compile(r"tCO[₂2](?:eq|e)?|MWh|GJ|TJ|kWh|톤|천\s*t|m[³3]|㎥|%|MW|tCO₂")
ENV = re.compile(
    r"온실가스|배출|에너지|전력|재생|폐기물|용수|취수|수자원|친환경|재활용|탄소|Scope|CO[₂2]|HEV|PHEV|EV|태양광",
    re.I,
)
HEADER = re.compile(r"^(?:지표명|구분|단위|항목|연도|지표)$")
FOOTNOTE = re.compile(r"^\s*(?:\d+[.)]|[※*])")


def observations(text, *, context="", limit=24):
    """Read explicit column years, one observation per data row; never infer years."""
    if "pb1-w9-v1" in context.split():
        from proofops.application.ingest.w9_tables import observations as w9

        return w9(text, limit=limit)
    lines = text.split("\n")
    years = {}
    header_end = -1
    for r, line in enumerate(lines[:4]):
        for col, cell in enumerate(line.split("\t")):
            value = cell.strip()
            if YEAR.fullmatch(value):
                year = re.search(r"\d{4}", value)[0]
                if col in years and years[col]["year"] != year:
                    return []  # ambiguous multi-level year columns
                years[col] = dict(year=year, row=r, column=col, quote=cell)
                header_end = max(header_end, r)
    if not years or len({v["year"] for v in years.values()}) != len(years):
        return []
    current = max(years, key=lambda c: years[c]["year"])
    results, offset = [], 0
    for row, line in enumerate(lines):
        cells = line.split("\t")
        if row > header_end and len(cells) > current:
            value = cells[current].strip()
            labels = [c for i, c in enumerate(cells[: min(years)]) if c.strip()]
            metric = labels[0] if labels else ""
            units = [c for c in labels if UNIT.search(c)]
            environmental = ENV.search(" ".join(labels)) or (ENV.search(context) and units)
            if (
                metric
                and units
                and environmental
                and not FOOTNOTE.match(metric)
                and not HEADER.fullmatch(metric.strip())
                and NUMERIC.fullmatch(value)
                and not YEAR.fullmatch(value)
            ):
                comparisons = [
                    dict(year=h["year"], value=cells[c], column=c)
                    for c, h in sorted(years.items())
                    if c != current and c < len(cells)
                ]
                results.append(
                    dict(
                        start=offset,
                        end=offset + len(line),
                        quote=line,
                        row=row,
                        value_column=current,
                        value=value,
                        unit=units[-1],
                        metric=metric,
                        year=years[current]["year"],
                        year_header=years[current],
                        comparisons=comparisons,
                        policy_sha256=canonical_hash(POLICY),
                    )
                )
        offset += len(line) + 1
    return results[: min(limit, POLICY["max_rows_per_table"])]


def occurrence_groups(claims):
    """Display grouping only; each original occurrence/receipt remains immutable."""
    groups = {}
    for claim in claims:
        groups.setdefault(canonical_hash(" ".join(claim.quote.split())), []).append(claim.claim_id)
    return {key: ids for key, ids in groups.items() if len(ids) > 1}
