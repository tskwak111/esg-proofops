"""Scheduling only: claim volume sizes calls; the existing USD broker owns money."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict, cast

from proofops.application.analysis_profile import S2_POLICY

if TYPE_CHECKING:
    from proofops.application.claims import Claim


class _CallBudget(TypedDict):
    profile: str
    max_calls: int
    calls_per_claim: int
    priority: str
    money_authority: str
    run_usd: str


POLICY = cast(_CallBudget, S2_POLICY["tagging_budget"])


def call_allowance(claim_count: int) -> int:
    if type(claim_count) is not int or claim_count < 0:
        raise ValueError("S2_CLAIM_COUNT_INVALID")
    # Three preliminary, relation and element replicas; up to three bounded
    # format attempts each. An unresolved claim still retains its three votes.
    return min(POLICY["max_calls"], claim_count * POLICY["calls_per_claim"])


def priority(claim: Claim) -> tuple[bool, bool, int, str, int, str]:
    # This dispatch order neither classifies tracks nor changes evidence admission.
    important = bool(re.search(r"\d|목표|감축|탄소중립|최초|최고", claim.quote))
    ref = claim.source_refs[0]
    return (
        claim.source_quality != "verified",
        not important,
        ref.page_num,
        ref.source_id,
        ref.char_start,
        claim.claim_id,
    )
