"""Add the model's literal value subspan inside its already selected context.

This is selection restoration only. Source, table ownership, binding, replica
and rule guards still run afterwards. No value is inferred or rewritten.
"""

from proofops.application.tagging.pb2_citation_restore import POLICY as TABLE_POLICY
from proofops.domain.provenance import canonical_hash

POLICY = TABLE_POLICY | dict(
    profile="citation-selected-value-pb6-v1",
    selected_value="one-exact-subspan-in-selected-context-with-numeric-boundaries",
)
POLICY_HASH = canonical_hash(POLICY)


def refine_selected_value(element):
    if element.get("state") != "present" or element.get("element_id") not in (
        "G2",
        "G3",
        "G5",
        "P1",
        "P2",
    ):
        return
    value = element.get("normalized_value")
    refs = element.get("evidence_refs")
    if not isinstance(value, str) or not value.strip() or not isinstance(refs, list):
        return
    if any(ref.get("quote") == value for ref in refs):
        return
    candidates = []
    for ref in refs:
        raw = ref["quote"]
        start = raw.find(value)
        if start < 0:
            continue
        if raw.find(value, start + 1) >= 0:
            return
        end = start + len(value)
        if (value[0].isdigit() and start and raw[start - 1] in "0123456789.,+−-") or (
            value[-1].isdigit() and end < len(raw) and raw[end] in "0123456789.,%"
        ):
            continue
        candidate = ref | dict(
            quote=value, char_start=ref["char_start"] + start, char_end=ref["char_start"] + end
        )
        if candidate not in candidates:
            candidates.append(candidate)
    if len(candidates) == 1:
        refs.append(candidates[0])
