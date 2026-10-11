"""Split a trailing label between repeated numeric bullet observations.

This trims literal offsets only. It never attaches the label to either value,
copies a facility heading into evidence, or grants source verification.
"""

import re

from proofops.domain.provenance import canonical_hash

OBSERVATION = (
    r"(?m)(?:^|(?<=\t))[ ]*•\s*(?P<metric>[^\n\t:：]+[:：][^\n\t\d]*"
    r"(?:20\d{2}년[^\n\t\d]*)?)"
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>MWh|kWh|GJ|TJ)"
    r"[ \t]+(?P<label>[가-힣A-Za-z][가-힣A-Za-z0-9 ]{1,23})[ \t]*(?=\n)"
)
POLICY = dict(
    profile="table-trailing-label-k1-v1",
    pattern=OBSERVATION,
    next="same-cell-next-bullet-same-literal-metric-and-unit",
    action="trim-label-into-review-context; no-facility-assignment; fresh-attestation-required",
)
POLICY_HASH = canonical_hash(POLICY)


def trim_table_labels(spans: list[dict], text: str, *, kind: str) -> tuple[list[dict], list[dict]]:
    if kind not in {"table", "table_cell", "table_row"}:
        return spans, []
    changes = {}
    for match in re.finditer(OBSERVATION, text):
        # Continuation predicates are not titles. Restrict to a bare noun label.
        label = match["label"].strip()
        if re.search(r"(?:유지|절감|생산|발전|사용|규모|달성|확대|감축|입니다|한다)$", label):
            continue
        following = re.match(
            r"\n[ ]*•\s*"
            + re.escape(match["metric"])
            + r"\d[\d,]*(?:\.\d+)?\s*"
            + re.escape(match["unit"])
            + r"(?=\s|$)",
            text[match.end() :],
        )
        if following:
            changes[match.start("label")] = (match.end("unit"), label)
    result, records = [], []
    for span in spans:
        selected = [
            (start, end, label)
            for start, (end, label) in changes.items()
            if span["char_start"] <= end < start < span["char_end"]
            and not text[start : span["char_end"]].strip().removesuffix(label).strip()
        ]
        if len(selected) != 1:
            result.append(span)
            continue
        start, end, label = selected[0]
        records.append(
            dict(
                old_start=span["char_start"],
                old_end=span["char_end"],
                new_end=end,
                excluded_start=start,
                excluded_end=start + len(label),
                excluded_quote=label,
                policy_sha256=POLICY_HASH,
                reason="trailing_label_requires_separate_facility_review",
            )
        )
        result.append(span | dict(char_end=end, quote=text[span["char_start"] : end]))
    return result, records
