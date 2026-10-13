"""Explicit observed headers and literal target rescue; no source/grade credit."""

import json
import re

from proofops.application.ingest import w9_tables as w9
from proofops.application.ingest.j8_cells import graph_cells
from proofops.domain.provenance import canonical_hash

YEAR = re.compile(r"(?:19|20)\d{2}(?:\s*년)?(?:\s+(?:실적|성과|actuals?))?", re.I)
UNIT = re.compile(w9.UNIT.pattern.replace("(?:eq|e)?", "(?:-?(?:eq|e))?"), re.I)
TARGET = r"목표로\s*(?:설정|수립|정했)|목표를\s*(?:설정|수립)|목표로\s*하고"
ENV = r"온실가스|재생에너지|탄소중립|넷\s*제로|net\s*zero|RE100|배출량"
POLICY = dict(
    profile="literal-coverage-k6-v1",
    observed_year=YEAR.pattern,
    unit=UNIT.pattern,
    target=TARGET,
    environment=ENV,
    selection="explicit-environment-target-predicate-and-year-or-percent; literal-own-block",
    exclusions="footnotes-recommendations-quotations-and-general-forecasts",
    evidence="same-checked-parser-grid; no-source-or-tag-credit; reverify-new-spans",
    old_policy="default-w9-parameters-and-I4-selections-unchanged",
)

# Separate opt-in contract: the historical K6 policy and its hash stay frozen.
FIGURE_V1_MARKER = "qc-native-figure-bullets-v1"
FIGURE_BULLET = r"(?m)^[ \t]*[•▪●\-][ \t]+"
FIGURE_END = (
    r"(?:운영|이행|수행|추진|수립|관리|지원|설치|감축|전환|실시|취소|제외|보류)"
    r"(?:합니다|했습니다|하고 있습니다|한다|함)?[.!。]?\s*$"
)
FIGURE_V1_POLICY = dict(
    profile=FIGURE_V1_MARKER,
    text="contiguous-original-PDFium-codepoints; located-glyphs-in-own-figure-region",
    bullets=FIGURE_BULLET,
    complete_ending=FIGURE_END,
    english="complete-sentence-with-explicit-action-predicate",
    layout="no-upward-native-order-jump-over-4pt; no-line-gap-over-24pt",
    selection="whole-literal-bullet; model-selects-source-ID; no-caption-text",
    authority="candidate-only; fresh-source-verification-and-three-independent-tags-required",
    max_chars=2000,
    max_bullets=24,
)
FIGURE_MARKER = "qc-native-figure-bullets-v2"
FIGURE_CONTEXT_MARKER = "qc-native-figure-context-v2"
FIGURE_POLICY = FIGURE_V1_POLICY | dict(
    profile=FIGURE_MARKER,
    context="all-native-groups-in-own-figure; source-bound-interpretation-only; no-truncation",
    ambiguity="clipped-glyph-or-unbounded-context-defers-whole-figure",
    max_context_groups=24,
)


def native_figure_context_blocks(block, graph):
    """Resolve mandatory native context only for the new opt-in candidate graph."""
    if block.winner is None:
        return ()
    context = block.candidates[block.winner].context
    if FIGURE_MARKER not in context:
        return ()  # historical candidate graphs keep their original interpretation
    pins = [
        c.removeprefix("qc_native_context_ids=")
        for c in context
        if c.startswith("qc_native_context_ids=")
    ]
    origins = [c for c in context if c.startswith("qc_native_origin=")]
    policy = "qc_native_policy=" + canonical_hash(FIGURE_POLICY)
    if len(pins) != 1 or len(origins) != 1 or policy not in context:
        raise ValueError("QC_NATIVE_FIGURE_CONTEXT_INVALID")
    ids = json.loads(pins[0])
    if (
        not isinstance(ids, list)
        or not ids
        or not all(isinstance(s, str) for s in ids)
        or len(set(ids)) != len(ids)
        or len(ids) > FIGURE_POLICY["max_context_groups"]
    ):
        raise ValueError("QC_NATIVE_FIGURE_CONTEXT_INVALID")
    blocks = {b.source_id: b for b in graph.blocks}
    result = tuple(blocks.get(s) for s in ids)
    origin = origins[0].split("=", 1)[1]
    for item in result:
        if (
            item is None
            or item.winner is None
            or item.page_num != block.page_num
            or item.kind != "figure"
            or item.bbox is None
            or item.quality not in ("verified", "unverified")
            or not {FIGURE_CONTEXT_MARKER, policy, origins[0]}.issubset(
                item.candidates[item.winner].context
            )
            or not any(
                e.source_id == item.source_id
                and e.target_id == origin
                and e.relation == "derived_from"
                for e in graph.edges
            )
        ):
            raise ValueError("QC_NATIVE_FIGURE_CONTEXT_INVALID")
    if sum(len(b.raw_text) + 1 for b in result) > FIGURE_POLICY["max_chars"]:
        raise ValueError("QC_NATIVE_FIGURE_CONTEXT_TOO_LARGE")
    return result


def native_figure_bullets(text):
    """Offer complete literal bullets, retaining trailing conditions and exclusions."""
    starts = [m.start() for m in re.finditer(FIGURE_BULLET, text)]
    if not starts:
        return []
    result = []
    for start, end in zip(starts, [*starts[1:], len(text)], strict=True):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        quote = text[start:end]
        english = re.search(
            r"\b(?:operate|implemented|installed|manage|support|reduced|perform)\b.+[.!]\s*$",
            quote,
            re.I,
        )
        if 12 <= len(quote) <= FIGURE_POLICY["max_chars"] and (
            re.search(FIGURE_END, quote) or english
        ):
            result.append((start, end, quote))
    return result[: FIGURE_POLICY["max_bullets"]]


def observations(text, *, cells=None, context="", limit=24):
    # Preserve historical W9 code bytes and outputs. Only newly supported
    # observed-header layouts enter this fallback; no parser text is rewritten.
    old = w9.observations(text, cells=cells, context=context, limit=limit)
    if old:
        return old
    rows = w9.grid(text, cells)
    years = {}
    for row in rows[:4]:
        for e in row["entries"]:
            if YEAR.fullmatch(e["text"].strip()):
                year = re.search(r"\d{4}", e["text"])[0]
                col = e["column"]
                if col in years and years[col]["year"] != year:
                    return []
                years[col] = dict(year=year, row=row["row"], column=col, quote=e["text"])
    if not years or len({h["year"] for h in years.values()}) != len(years):
        return []
    current, first = max(years, key=lambda c: years[c]["year"]), min(years)
    header_end = max(h["row"] for h in years.values())
    labels = " ".join(e["text"] for row in rows for e in row["entries"][:first])
    if w9.FINANCIAL.search(labels) or not w9.ENV.search(labels):
        return []
    result = []
    for row in rows[header_end + 1 :]:
        es = row["entries"]
        units = [e for e in es[:first] if UNIT.fullmatch("".join(e["text"].split()))]
        local = [e for e in es[:first] if e["text"].strip() and e not in units]
        value = es[current]["text"].strip()
        if (
            len(units) != 1
            or not local
            or w9.legacy.FOOTNOTE.match(local[0]["text"])
            or w9.legacy.HEADER.fullmatch(local[0]["text"].strip())
            or not w9.legacy.NUMERIC.fullmatch(value)
            or w9.legacy.YEAR.fullmatch(value)
        ):
            continue
        parents = [
            e
            for e in w9._parents(rows, row["row"], first)
            if not UNIT.fullmatch("".join(e["text"].split()))
        ]
        column_parents = [
            e
            for head in rows[: header_end + 1]
            for e in head["entries"]
            if (c := e["cell"])
            and c["text"]
            and c["column"] <= current < c["column"] + c["column_span"]
            and not YEAR.fullmatch(c["text"].strip())
            and not w9.legacy.HEADER.fullmatch(c["text"].strip())
            and not UNIT.fullmatch("".join(c["text"].split()))
        ]
        parents += column_parents
        path = list(dict.fromkeys(e["text"] for e in parents))
        result.append(
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
    return result[: min(limit, w9.POLICY["max_rows_per_table"])]


def observations_for(table, graph):
    return observations(table.normalized_text, cells=graph_cells(table, graph))


def target_spans(text, *, kind):
    if (
        kind != "paragraph"
        or len(text) > 2000
        or not re.search(TARGET, text)
        or not re.search(ENV, text, re.I)
        or not re.search(r"(?:19|20)\d{2}\s*년\s*까지|\d+(?:\.\d+)?\s*%", text)
        or re.search(r"^\s*[*※]|권고|정의|예를\s*들어|[\"“”]", text)
    ):
        return []
    start, end = len(text) - len(text.lstrip()), len(text.rstrip())
    return [
        dict(
            char_start=start,
            char_end=end,
            quote=text[start:end],
            kind="claim",
            reason=None,
            topic_ids=["environment"],
        )
    ]


def rescue_targets(spans, text, *, kind):
    targets = target_spans(text, kind=kind)
    if not targets or any(
        s["char_start"] <= targets[0]["char_start"] and s["char_end"] >= targets[0]["char_end"]
        for s in spans
    ):
        return spans, []
    # Keep an already selected partial target rather than adding an overlapping duplicate.
    target = targets[0]
    if any(
        s["char_start"] < target["char_end"] and target["char_start"] < s["char_end"] for s in spans
    ):
        return spans, []
    return sorted([*spans, target], key=lambda s: s["char_start"]), targets
