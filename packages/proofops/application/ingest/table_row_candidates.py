"""Opt-in literal table/chart rows; axes are interpretation only, never evidence."""

import re
from dataclasses import dataclass

from proofops.application.ingest.atomic_candidates import (
    ASSERTION,
    ENVIRONMENT,
    UNIT,
    YEAR,
    _eligible,
    _has,
)
from proofops.application.ingest.atomic_candidates import (
    POLICY as ATOMIC_POLICY,
)

PROFILE = "extraction-table-rows-v1"
HEADER = r"구분|단위|지표|위원회|전략|부문|항목|indicator|metric|unit|category"
POLICY = {
    "profile": PROFILE,
    "lexical_policy": ATOMIC_POLICY,
    "header": {"labels": HEADER, "exclude": "non-year-digits-or-eligible-disclosure"},
    "boundary": "literal-lines-for-table-row-figure; cells-stay-whole",
    "parent": "same-source-first-delimited-header-or-resolved-same-table-axes-only",
    "quote": "original-contiguous-row-or-cell-no-concatenation",
    "binding": "unchanged-undetermined-until-existing-validation",
    "max_candidates": 64,
}


@dataclass(frozen=True)
class RowCandidate:
    start: int
    end: int
    header_start: int | None = None
    header_end: int | None = None


def row_candidates(text, *, kind, table_context=()):
    """Never combine disconnected chart labels/values or borrow another data row."""
    if kind not in ("table", "table_row", "table_cell", "figure"):
        return ()
    lines = (
        [(0, len(text))]
        if kind == "table_cell"
        else [(m.start(), m.end()) for m in re.finditer(r"[^\r\n]+", text)]
    )
    header = None
    if kind == "table" and lines:
        a, b = lines[0]
        first = text[a:b]
        # A leading data row is never allowed to donate its year/quantity to
        # later rows. Require explicit structural labels and no non-year digits.
        if (
            ("\t" in first or "|" in first)
            and _has(HEADER, first)
            and not re.search(r"\d", re.sub(YEAR, "", first))
            and not _eligible(first, kind, ())
        ):
            header = (a, b)
    axes = (*table_context, text[header[0] : header[1]]) if header else table_context
    results = []
    for a, b in lines:
        fragment = text[a:b]
        start = a + len(fragment) - len(fragment.lstrip())
        end = b - len(fragment) + len(fragment.rstrip())
        value = text[start:end]
        if not value or (header and (a, b) == header):
            continue
        eligible = _eligible(value, kind, axes)
        # A literal delimited metric row carries its own values. Year/unit may
        # be in this table's header, but are not appended to the row quote.
        if not eligible and kind in ("table", "table_row") and ("\t" in value or "|" in value):
            eligible = _has(ENVIRONMENT, value) and (
                bool(re.search(r"\d", value))
                and _has(UNIT, value + " " + " ".join(axes))
                and _has(YEAR, value + " " + " ".join(axes))
                or _has(ASSERTION, value)
                and bool(re.search(r"\d|승인|검토|수립|구축|추진|운영", value))
            )
        if eligible:
            results.append(RowCandidate(start, end, *(header or (None, None))))
    return tuple(results)
