"""J3 literal candidate boundaries; selection, attribution and grades remain separate."""

import re

from proofops.application.ingest.w9_tables import grid

PROFILE = "j3-explicit-boundaries-v1"
BULLET = r"(?<!\S)•(?=\s)"
ACTION = (
    r"위임|감독|수립|운영|승인|모니터링|반영|총괄|관리|실시|진행|보고|확산|개발|적용|획득|"
    r"확보|마련|추진|완료|개시|냉각|냉방|제설|저장|흡수|절감|향상|공급|구축|연동|유지"
)
POLICY = dict(
    profile=PROFILE,
    bullet=BULLET,
    action=ACTION,
    selected="only-refine-selected-parent; exact-disjoint-subspans; no-unselected-join",
    table="refine-only-selected-generic-row-at-complete-explicit-origin-cells",
    headers="no-number/year-credit; existing-candidate-planner-and-model-wire-unchanged",
    fallback="keep-parent-if-any-bullet-is-fragment-or-any-child-fails-source-validation",
    evidence="binding-undetermined; native-source-and-LLM-tag-guards-unchanged",
    max_candidates=64,
)


def _trim(text, a, b):
    value = text[a:b]
    return a + len(value) - len(value.lstrip()), b - len(value) + len(value.rstrip())


def bullet_bounds(text, start, end):
    """Split explicit list items, never punctuation, wraps or connective words."""
    value = text[start:end]
    bullets = [start + m.start() for m in re.finditer(BULLET, value)]
    if len(bullets) < 2 or value[: bullets[0] - start].strip():
        return [(start, end)]
    parts = [_trim(text, a, b) for a, b in zip(bullets, [*bullets[1:], end])]
    # A broken item may depend on its neighbours; preserve that entire parent.
    if any(
        len(text[a:b].strip("• \t\n")) < 8
        or not re.search(ACTION, text[a:b])
        or re.search(r"(?:위한|대한|및|또는|하고|하며|의|을|를)\s*$", text[a:b])
        for a, b in parts
    ):
        return [(start, end)]
    return parts


def refine_selected(spans, text, *, kind, cells=None):
    """Keep only the text already selected; return the original parent on ambiguity."""
    output, changes = [], []
    rows = grid(text, cells) if kind == "table" and cells is not None else None
    for span in spans:
        a, b = span["char_start"], span["char_end"]
        bounds = [(a, b)]
        if kind == "paragraph":
            bounds = bullet_bounds(text, a, b)
        elif rows is not None and "\t" in text[a:b]:
            # Only complete selected origin cells may become independent spans.
            entries = [
                e
                for row in rows
                for e in row["entries"]
                if e["cell"]
                and a <= e["start"] < e["end"] <= b
                and re.search(ACTION, e["text"])
                and len(e["text"].strip()) >= 8
            ]
            if len(entries) > 1:
                bounds = [_trim(text, e["start"], e["end"]) for e in entries]
        children = [dict(span, char_start=x, char_end=y, quote=text[x:y]) for x, y in bounds]
        output.extend(children)
        if bounds != [(a, b)]:
            changes.append(
                dict(
                    parent_start=a,
                    parent_end=b,
                    children=[dict(char_start=x, char_end=y) for x, y in bounds],
                )
            )
    if len(output) > POLICY["max_candidates"] and len(output) > len(spans):
        return spans, []  # keep every original selection; never truncate to fit
    return output, changes
