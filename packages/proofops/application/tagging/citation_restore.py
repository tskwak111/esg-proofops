"""Versioned whitespace-only selection recovery; never source admission or tagging."""

import re

from proofops.application.ingest.display_text import join_allowed
from proofops.domain.provenance import canonical_hash

POLICY = dict(
    profile="citation-whitespace-partial-v1",
    matching="unique-whitespace-runs-and-protected-hangul-boundaries-v1",
    offsets="original-codepoints",
    failed_element="unknown",
)
POLICY_HASH = canonical_hash(POLICY)


def restore_whitespace(selection, original):
    if not isinstance(selection, str) or not selection.strip():
        raise ValueError("non-empty source quote required")
    raw = original["quote"]
    # Literal whitespace runs first. Boundary insertion/removal is permitted
    # only by the existing Hangul-only number/unit-protected display predicate.
    parts = re.split(r"(\s+)", selection)
    pattern = "".join(r"\s+" if part.isspace() else re.escape(part) for part in parts)
    matches = list(re.finditer(f"(?=({pattern}))", raw))
    if len(matches) > 1:
        raise ValueError("whitespace quote absent or ambiguous")
    if matches:
        start, end = matches[0].span(1)
    else:
        raw_positions = [i for i, c in enumerate(raw) if not c.isspace()]
        selected_positions = [i for i, c in enumerate(selection) if not c.isspace()]
        compact = "".join(selection[i] for i in selected_positions)
        whole = "".join(raw[i] for i in raw_positions)
        offset = whole.find(compact)
        if offset < 0 or whole.find(compact, offset + 1) >= 0:
            raise ValueError("whitespace quote absent or ambiguous")
        positions = raw_positions[offset : offset + len(compact)]
        window = raw[positions[0] : positions[-1] + 1]
        plain_raw, plain_selected = " ".join(window.split()), " ".join(selection.split())
        rmap = [i for i, c in enumerate(plain_raw) if not c.isspace()]
        smap = [i for i, c in enumerate(plain_selected) if not c.isspace()]
        for i in range(1, len(compact)):
            rgap = plain_raw[rmap[i - 1] + 1 : rmap[i]]
            sgap = plain_selected[smap[i - 1] + 1 : smap[i]]
            if rgap != sgap and not (
                join_allowed(plain_raw, rmap[i] - 1)
                if rgap
                else join_allowed(plain_selected, smap[i] - 1)
            ):
                raise ValueError("protected whitespace boundary changed")
        start, end = positions[0], positions[-1] + 1
    return original | dict(
        quote=raw[start:end],
        char_start=original["char_start"] + start,
        char_end=original["char_start"] + end,
    )
