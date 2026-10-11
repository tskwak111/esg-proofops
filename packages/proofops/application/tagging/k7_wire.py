"""Budget interpretation only; immutable sources and evidence IDs stay server-side."""

import json
from copy import deepcopy

from proofops.domain.provenance import canonical_hash

POLICY_V1 = dict(
    profile="bounded-interpretation-k7-v1",
    priority="parent-sentence-or-origin-cell > column-header > other",
    limit="provider-request-body-16384-bytes-including-JSON-escaping",
    truncation="literal-codepoint-prefix; explicit-omission-record; interpretation-only",
    fallback="atomic-without-context; never-remove-evidence-or-change-source-authority",
    citations="evidence-catalog-ID-enum-only; interpretation-exposes-no-source-IDs",
)
POLICY = POLICY_V1 | dict(
    profile="bounded-interpretation-k7-v2",
    priority_source="checked-focal-block-kind; order-changes-only-when-truncating",
)
INSTRUCTIONS = (
    "\nInterpretation context is not citable evidence. Only IDs in evidence_catalog "
    "and element_evidence_ids are allowed in evidence_refs. Never cite a source UUID "
    "or context. Every present element requires a non-empty evidence_refs array with "
    "an allowed ID and exact catalog substring; otherwise return unknown, [] and null. "
    "interpretation_budget records omitted context: do not infer missing conditions, "
    "scope, numbers or absence from a truncated sentence."
)


def fit_context(system, user, check):
    """Check the exact provider body; deterministically share the projection across replicas."""
    value = deepcopy(user)
    data = value["untrusted_document_data"]
    policy = data.pop("tagging_wire_policy", POLICY)
    context = data.pop("sentence_context", None)
    if not context:
        wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        check(system, wire)
        return wire
    source_kind = context.pop("_source_kind", None)
    refs = context.get("source_refs", [])
    # K5 table contexts put column headers before the focal origin cell.
    if policy == POLICY_V1 and len(refs) > 1 and any(r.get("table_id") is not None for r in refs):
        refs = [refs[-1], *refs[:-1]]
    pieces = [
        (r["quote"], r.get("page_num"), r.get("verification_state", "candidate")) for r in refs
    ]
    if not pieces:
        pieces = [(context["text"], None, context.get("verification_state", "candidate"))]
    total = sum(len(p[0]) for p in pieces)
    budget = dict(
        policy_sha256=canonical_hash(policy),
        original_sha256=canonical_hash(context),
        original_chars=total,
        retained_chars=total,
        truncated=False,
        fallback=None,
    )
    data["interpretation_budget"] = budget

    def render(count):
        remaining, blocks = count, []
        ordered = (
            [pieces[-1], *pieces[:-1]]
            if (policy == POLICY and source_kind == "table" and count < total)
            else pieces
        )
        for text, page, quality in ordered:
            take = min(remaining, len(text))
            if take:
                blocks.append(
                    dict(
                        text=text[:take],
                        page_num=page,
                        quality=quality,
                        rule_credit=False,
                        truncated=take < len(text),
                    )
                )
            remaining -= take
        budget.update(
            retained_chars=count,
            truncated=count < total,
            fallback="atomic_without_context" if not count else None,
        )
        if blocks:
            data["sentence_context"] = dict(blocks=blocks, rule_credit=False)
        else:
            data.pop("sentence_context", None)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def fits(count):
        wire = render(count)
        try:
            check(system, wire)
        except ValueError as error:
            if str(error) != "PROBE_REQUEST_TOO_LARGE":
                raise
            return False
        return True

    if fits(total):
        return render(total)
    if not fits(0):
        # The contextless request must still obey the provider's hard limit.
        check(system, render(0))
    low, high = 0, total
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return render(low)
