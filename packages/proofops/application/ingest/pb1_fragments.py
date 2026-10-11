"""Narrow Korean continuation fragments; exclusion keeps the original unknown span."""

import re

START = re.compile(r"^(?:통해|하여|함으로써|으로써|하고\s|하며\s|및\s|또는\s)")
END = re.compile(r"(?:하고|하며|통해|대한|위한|및|또는|의|을|를)\s*$")
FOOTNOTE = re.compile(r"^\s*(?:[※*]|\d+\))\s*(?:산정|산출|기준|포함|제외|주:|참고)")


def incomplete_fragment(quote):
    return bool(START.search(quote.strip()) or END.search(quote.strip()) or FOOTNOTE.search(quote))


TABLE_CONTEXT_LABEL = re.compile(
    r"^\s*[※*]\s*(?:적용\s*기술|기술\s*설명|산정\s*방법|방법론|주석|참고|단위)\s*[:：]"
)
TABLE_CONTEXT_POLICY = dict(
    profile="pb1-table-context-labels-v1",
    pattern=TABLE_CONTEXT_LABEL.pattern,
    action="post-selection-exclusion; retain raw response and uncovered source spans",
)


def table_context_row(quote):
    return bool(TABLE_CONTEXT_LABEL.match(quote))
