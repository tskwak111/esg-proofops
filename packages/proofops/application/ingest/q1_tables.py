"""Literal activity/effect matrix recovery; no evidence or semantic tag credit."""

import re

from proofops.application.ingest import j8_cells

MEANS_HEADER = r"환경영향\s*완화\s*요소"
EFFECT_HEADER = r"환경영향\s*완화\s*효과(?:\d+\))?"
ACTIVITY = r"운영|운전|설비|적용|시스템|패널|전지|기기|유리|단열재|테라스|인프라|설계"
EFFECT_ACTION = r"온도\s*상향|팬\s*풍량\s*최적화"
POLICY = dict(
    profile="q1-activity-effect-cells-v1",
    base=j8_cells.POLICY,
    headers="explicit-environment-mitigation-means-and-effects-in-same-origin-grid",
    selection="retain-literal-named-activity-cells; effect-cells-still-model-selected",
    means_header=MEANS_HEADER,
    effect_header=EFFECT_HEADER,
    activity_pattern=ACTIVITY,
    effect_action=EFFECT_ACTION,
    evidence="original-offsets; existing-native-source-and-tag-guards-required",
)


def _matrix(text, cells):
    rows = j8_cells.checked_grid(text, cells)
    if not rows:
        return rows, set(), set()
    means = {
        e["column"] for e in rows[0]["entries"] if re.fullmatch(MEANS_HEADER, e["text"].strip())
    }
    effects = {
        e["column"] for e in rows[0]["entries"] if re.fullmatch(EFFECT_HEADER, e["text"].strip())
    }
    return rows, means, effects


def activity_spans(text, cells):
    rows, means, effects = _matrix(text, cells)
    if not means or not effects:
        return []
    results = []
    # A merged means header covers its explicitly spanned columns only.
    columns = {
        c
        for e in rows[0]["entries"]
        if e["column"] in means and e["cell"]
        for c in range(e["column"], e["column"] + e["cell"]["column_span"])
    }
    # Some parsers emit a blank second header instead of a merged header.
    # The contiguous blank origin header before the effect column is explicit.
    for e in rows[0]["entries"]:
        if e["cell"] and not e["text"].strip() and min(means) < e["column"] < min(effects):
            columns.add(e["column"])
    for row in rows[1:]:
        for e in row["entries"]:
            if not e["cell"] or e["column"] not in columns:
                continue
            value = e["text"].strip()
            if not re.match(r"^[①-⑳]\s*\S", value) or not re.search(ACTIVITY, value):
                continue
            start = e["start"] + len(e["text"]) - len(e["text"].lstrip())
            end = e["end"] - len(e["text"]) + len(e["text"].rstrip())
            results.append(
                dict(
                    char_start=start,
                    char_end=end,
                    quote=text[start:end],
                    kind="claim",
                    topic_ids=["environment"],
                    reason=None,
                )
            )
    return results


def cell_entries(text, cells, *, source_id):
    old = j8_cells.cell_entries(text, cells, source_id=source_id)
    rows, means, effects = _matrix(text, cells)
    if not means or not effects:
        return old
    keys = {(e["char_start"], e["char_end"]) for e in old}
    for row in rows[1:]:
        for e in row["entries"]:
            if (
                e["cell"]
                and e["column"] in effects
                and re.search(EFFECT_ACTION, e["text"])
                and (e["start"], e["end"]) not in keys
            ):
                old.append(
                    dict(
                        sentence_id=f"{source_id}:{POLICY['profile']}:{e['start']}:{e['end']}",
                        text=e["text"],
                        char_start=e["start"],
                        char_end=e["end"],
                        row=row["row"],
                        column=e["column"],
                        cell_source_id=e["cell"].get("source_id"),
                        candidate_role="cell_item",
                        parent_context=[],
                        binding_status="undetermined",
                    )
                )
    return sorted(old, key=lambda e: e["char_start"])


def retain_activities(spans, text, cells):
    added = [
        s
        for s in activity_spans(text, cells)
        if not any(
            x["char_start"] <= s["char_start"] and s["char_end"] <= x["char_end"] for x in spans
        )
        and not any(
            x["char_start"] < s["char_end"] and s["char_start"] < x["char_end"] for x in spans
        )
    ]
    return sorted([*spans, *added], key=lambda s: s["char_start"]), added
