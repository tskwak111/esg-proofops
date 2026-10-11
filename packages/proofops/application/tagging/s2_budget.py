"""Scheduling only: claim volume sizes calls; the existing USD broker owns money."""

import re

from proofops.application.analysis_profile import S2_POLICY

POLICY = S2_POLICY["tagging_budget"]


def call_allowance(claim_count):
    if type(claim_count) is not int or claim_count < 0:
        raise ValueError("S2_CLAIM_COUNT_INVALID")
    # Three preliminary, relation and element replicas; up to three bounded
    # format attempts each. An unresolved claim still retains its three votes.
    return min(POLICY["max_calls"], claim_count * POLICY["calls_per_claim"])


def priority(claim):
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
