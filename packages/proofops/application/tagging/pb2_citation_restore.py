"""PB2 selection recovery: explicit display separators map only to raw table tabs."""

import re

from proofops.application.tagging.citation_restore import POLICY as LEGACY_POLICY
from proofops.application.tagging.citation_restore import restore_whitespace
from proofops.domain.provenance import canonical_hash

POLICY = LEGACY_POLICY | dict(
    profile="citation-table-separators-pb2-v1",
    table_separators="standalone-pipe-to-existing-tabs-only",
)
POLICY_HASH = canonical_hash(POLICY)


def restore_table(selection, original):
    if not isinstance(selection, str) or not selection.strip():
        raise ValueError("non-empty source quote required")
    if "\t" not in original["quote"] or "|" not in selection:
        return restore_whitespace(selection, original)
    parts = re.split(r"\s+\|\s+", selection)
    if len(parts) < 2 or any(not p.strip() for p in parts):
        raise ValueError("table separator selection invalid")
    pattern = r"\t+".join(r"\s+".join(re.escape(p) for p in part.strip().split()) for part in parts)
    matches = list(re.finditer(f"(?=({pattern}))", original["quote"]))
    if len(matches) != 1:
        raise ValueError("table quote absent or ambiguous")
    start, end = matches[0].span(1)
    return original | dict(
        quote=original["quote"][start:end],
        char_start=original["char_start"] + start,
        char_end=original["char_start"] + end,
    )
