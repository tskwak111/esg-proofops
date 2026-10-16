"""Literal target atoms inside an already selected compound maintenance goal."""

import re

from proofops.application.ingest.atomic_candidates import POLICY_V3, atomic_candidates

MAINTENANCE = r"(?:19|20)\d{2}년\s*수준(?:으로)?\s*(?:유지|관리)"
POLICY = dict(
    profile="qt1_v25_maintenance_goal_atoms_v1",
    base=POLICY_V3,
    gate=MAINTENANCE,
    scope="selected-prose-only; literal-disjoint-subspans; no-extra-extraction-pass",
    authority="candidates-only; reverify-and-retag-each-atom; no-inherited-year-or-votes",
)


def refine_selected(spans, text, *, kind):
    output, changes = [], []
    for span in spans:
        quote = text[span["char_start"] : span["char_end"]]
        if kind != "paragraph" or span["kind"] != "claim" or not re.search(MAINTENANCE, quote):
            output.append(span)
            continue
        atoms = atomic_candidates(quote, policy_version=3)
        gaps = zip([0, *(a.end for a in atoms)], [*(a.start for a in atoms), len(quote)])
        if len(atoms) < 2 or any(quote[a:b].strip() for a, b in gaps):
            output.append(span)
            continue
        children = [
            dict(
                span,
                char_start=span["char_start"] + a.start,
                char_end=span["char_start"] + a.end,
                quote=quote[a.start : a.end],
            )
            for a in atoms
        ]
        output.extend(children)
        changes.append(
            dict(
                parent_start=span["char_start"],
                parent_end=span["char_end"],
                child_spans=[(s["char_start"], s["char_end"]) for s in children],
                policy=POLICY["profile"],
            )
        )
    return output, changes
