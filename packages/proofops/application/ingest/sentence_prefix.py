"""Recover an unselected sentence prefix inside one literal prose source only.

This changes extraction offsets, never source approval. The caller must validate
the result and obtain a fresh character/geometry attestation before tagging.
"""

import re

PROFILE = "same-paragraph-sentence-prefix-w7-v1"
TERMINAL = r"[.!?。！？;:](?=\s|$)"
PARAGRAPH = r"\r?\n[ \t\r]*\n"
BULLET = r"(?m)(?:^[ \t]*(?:[•·▪▶※*–—-]|\d+[.)）])|(?<!\S)[•▪▶※])\s*"
INDEPENDENT = (
    r"(?:했으며|하였으며|하였고|했고|했으나|하였으나|하고\s*있으며|하고\s*있고|"
    r"합니다|했습니다|하였습니다|됩니다|있습니다|하였다|했다|한다|하며|(?<!불구)하고)(?=\s|[,;]|$)|"
    r"\b(?:and|but|while)\s*$"
)
# Short noun-only lines in a paragraph may be embedded titles. Do not infer
# their role from environmental vocabulary; require explicit continuation form.
CONTINUATION = r"(?:[을를의에]|에는|에서|으로|위해|하여|통해|하며|영향|체계를|[,，])\s*$"
POLICY = dict(
    profile=PROFILE,
    scope="one-paragraph-source; no context/continuation-block/row concatenation",
    origin="validated-context-graph; ordinary-paragraph; derived-from blocks are not eligible",
    terminal=TERMINAL,
    paragraph=PARAGRAPH,
    bullet=BULLET,
    independent=INDEPENDENT,
    heading=dict(max_chars=24, continuation=CONTINUATION),
    overlap="retain separate selected claims; never absorb another selection",
    validation="literal offsets + existing quotation/token checks + fresh source attestation",
)


def expand_sentence_prefixes(spans: list[dict], text: str, *, kind: str) -> tuple[list, list]:
    """Extend only backwards; preserve the selected predicate/end and source order."""
    if kind != "paragraph" or "\t" in text or "|" in text:
        return spans, []
    ordered = sorted(spans, key=lambda s: s["char_start"])
    result, records = [], []
    for span in ordered:
        start, end = span["char_start"], span["char_end"]
        left = 0
        for pattern in (TERMINAL, PARAGRAPH):
            for match in re.finditer(pattern, text[:start]):
                left = max(left, match.end())
        # Keep the current bullet marker, but never cross into a previous item.
        for match in re.finditer(BULLET, text[: start + 1]):
            left = max(left, match.start())
        while left < start and text[left].isspace():
            left += 1
        prefix = text[left:start]
        reason = None
        if left >= start:
            continue
        # Embedded titles end a segment. An actual continuation after that
        # title can still be recovered, without attaching the title to it.
        cursor = left
        heading_boundary = False
        for line in prefix.splitlines(keepends=True):
            value = re.sub(BULLET, "", line).strip()
            cursor += len(line)
            if value and len(value) <= 24 and not re.search(CONTINUATION, value):
                left = cursor
                heading_boundary = True
        while left < start and text[left].isspace():
            left += 1
        prefix = text[left:start]
        if heading_boundary and left >= start:
            reason = "possible_embedded_heading"
        elif re.search(INDEPENDENT, prefix, re.I):
            reason = "independent_preceding_claim"
        elif any(s["char_start"] < start and s["char_end"] > left for s in ordered):
            reason = "another_selected_claim"
        records.append(
            dict(
                selected_start=start,
                selected_end=end,
                proposed_start=left,
                status="retained" if reason else "expanded",
                reason=reason,
            )
        )
        result.append(span if reason else {**span, "char_start": left, "quote": text[left:end]})
    # Include selections already at a sentence boundary, in source order.
    by_start = {r["selected_start"] for r in records}
    result.extend(s for s in ordered if s["char_start"] not in by_start)
    return sorted(result, key=lambda s: s["char_start"]), records
