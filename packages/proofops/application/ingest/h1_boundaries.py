"""Literal holdout fixes; notes remain context and original selection is retained."""

import re

POLICY = dict(
    profile="h1-selected-boundaries-v1",
    headings="selected-heading-spans-use-existing-linewrap-and-prefix-guards",
    scope_note=r"^\s*[*※]\s*\d{4}년\s*목표에는\s+.+사업장.+배출량\s*포함\s*$",
    excluded="explicit-target-boundary-note-only; retain-raw-selection-and-source",
    no_join="no-cross-source-or-unselected-text-joining",
    strategy_title=r"(?:그룹\s+|전사\s+)?탈탄소\s+전략\s+및\s+로드맵\s+수립",
    title_guard="full-block-native-glyph-literal-and-font-over-body-median-1.1; no-year-or-value",
)


def scope_note(quote):
    return bool(re.fullmatch(POLICY["scope_note"], quote))


def strategy_title(quote):
    return bool(re.fullmatch(POLICY["strategy_title"], quote.strip()))
