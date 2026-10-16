"""Create a smaller declared subset from a fresh proposal's actual claim ranking.

Evaluation drivers should use this instead of reposting an earlier run's page
numbers after inspection. Explicit human manual selections remain supported.
"""

from copy import deepcopy

from evaluation.report_scope import validate_selection


def ranked_subset(plan, *, claim_limit):
    if type(claim_limit) is not int or not 1 <= claim_limit <= 10:
        raise ValueError("claim limit must be an integer in 1..10")
    source, count = plan["source_sha256"], plan["page_count"]
    validate_selection(plan, source, count)
    rows = {r["page"]: r for r in plan["pages"]}

    def priority(page):
        row = rows[page]
        rank = row.get("claim_selection_decision", {}).get("candidate_rank")
        return (
            row["category"] != "ceo_message",
            rank if type(rank) is int else count + 1,
            -row.get("claim_signal_score", 0),
            page,
        )

    chosen = sorted(sorted(plan["selected_claim_pages"], key=priority)[:claim_limit])
    edited = deepcopy(plan)
    edited["selected_claim_pages"] = chosen
    # Keep the original evidence union and proposal hash, including the omitted
    # claim page as evidence. Do not fabricate new evidence or a new ranking.
    return validate_selection(edited, source, count)
