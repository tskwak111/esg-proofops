"""W8 negative admission checks over selected citations; never mint present/absent.

These narrow literal checks complement model tagging, not a replacement semantic
classifier. Raw votes/citations stay intact. Unknown expressions require review.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from proofops.domain.provenance import canonical_hash
from proofops.domain.values import LlmElement

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.application.tagging.service import TagRun

DEFINITIONS = """
W8 guidance, original v2 §4.4/4.5 and DEC-24; no new ladder thresholds.
M1 requires a named means/standard or concrete implementation state. Policy
intent such as 적극 지원, 노력, 추진할 것 alone is not implementation.
An operating system, installed equipment, monitoring procedure or ISO standard
can qualify when explicitly cited. Do not withdraw concrete means merely because
the same sentence also contains intent. Unsupported M1 stays unknown for review;
do not infer willingness_only or absence from missing evidence.
G6 requires a transition plan or a means of achieving the target. A declaration
of 100% renewable conversion is only a target, not a means. A cited PPA, own
generation or specific implementation roadmap can qualify. Do not borrow the
next paragraph's plan to justify the current declaration citation. G2 conflict
stays conflict even if a target number can be seen; it requires new tagging.
M2 must identify which organizations/facilities the activity covers. 사업장별
영향 alone does not say which facilities are included. Explicit 전사, domestic
production sites, a named site or a specified group may qualify. Same-paragraph
subject continuity must be explicit; another paragraph/page is not authority.
DEC-24.2: emissions_estimate, including numeric Scope 3 table observations and
their items, remain held for calculation-basis review. Category is independent
of P1; do not turn a verified numerical cell into absence or a decided grade.
Examples are guidance only, never original evidence. Grades are Python-only.
""".strip()

_INTENT = r"적극\s*지원|노력|추진할\s*(?:것|예정)|선언"
_MEANS = (
    r"ISO\s*\d+|PPA\b|전력\s*구매\s*계약|자체\s*발전|설비|시스템|"
    r"관리[·\s]*운영\s*체계|모니터링|정기\s*점검|이행\s*로드맵|실행\s*계획|설치"
)
_BOUNDARY = r"전사|국내|해외|글로벌|전체|모든|전\s*사업장|\d+\s*개\s*사업장"
_SCOPE3 = r"scope\s*3|스코프\s*3"
POLICY = dict(
    profile="tagging-semantic-admission-w8-v1",
    source_sections=["4.4", "4.5", "DEC-24.2", "DEC-24.6"],
    definitions_sha256=canonical_hash(DEFINITIONS),
    intent_pattern=_INTENT,
    means_pattern=_MEANS,
    boundary_pattern=_BOUNDARY,
    scope3_pattern=_SCOPE3,
    rejection_state="unknown",
    estimates="hold-no-numeric-range",
)
POLICY_HASH = canonical_hash(POLICY)


def validate_policy(policy: dict) -> None:
    from proofops.application.tagging.k1_semantics import POLICY as K1_POLICY
    from proofops.application.tagging.k4_contract import SEMANTIC_POLICY
    from proofops.application.tagging.k10_contract import SEMANTIC_POLICY as K10_POLICY
    from proofops.application.tagging.k10_contract import SEMANTIC_V2_POLICY as K10_V2_POLICY
    from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_POLICY

    if policy not in (POLICY, K1_POLICY, SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY):
        raise ValueError("SEMANTIC_ADMISSION_POLICY_UNKNOWN")


def guard_element(element: LlmElement, *, policy=None, claim_quote="") -> LlmElement:
    if policy is not None and policy != POLICY:
        validate_policy(policy)
        from proofops.application.tagging.k1_semantics import guard

        admitted = guard(guard_element(element), claim_quote=claim_quote)
        from proofops.application.tagging.k10_contract import SEMANTIC_POLICY as K10_POLICY
        from proofops.application.tagging.k10_contract import SEMANTIC_V2_POLICY as K10_V2_POLICY
        from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_POLICY

        if policy in (Q1_POLICY, K10_POLICY, K10_V2_POLICY):
            from proofops.application.tagging.q1_contract import guard as q1_guard

            admitted = q1_guard(admitted)
        if policy in (K10_POLICY, K10_V2_POLICY):
            from proofops.application.tagging.k10_contract import guard as k10_guard

            admitted = k10_guard(admitted, policy=policy)
        return admitted
    if element.state != "present":
        return element
    quotes = [" ".join(ref.quote.split()) for ref in element.evidence_refs]
    means = any(re.search(_MEANS, q, re.I) for q in quotes)
    reason = None
    if element.element_id == "M1" and not means and any(re.search(_INTENT, q) for q in quotes):
        reason = "W8_M1_INTENT_REQUIRES_REVIEW"
    elif element.element_id == "G6" and not means and any("선언" in q for q in quotes):
        reason = "W8_G6_DECLARATION_REQUIRES_PLAN"
    elif element.element_id == "M2" and all(
        re.match(r"^(?:사업장별|각\s*사업장)", q) and not re.search(_BOUNDARY, q) for q in quotes
    ):
        reason = "W8_M2_BOUNDARY_UNSPECIFIED"
    return (
        replace(
            element, state="unknown", normalized_value=None, credited_from=None, reason_code=reason
        )
        if reason
        else element
    )


def guard_runs(runs: tuple[TagRun, ...], *, policy=None, claim_quote="") -> tuple[TagRun, ...]:
    """Reprocess saved guarded votes into new candidates, preserving raw receipts."""
    results = []
    for run in runs:
        if run.guarded is None:
            results.append(run)
            continue
        elements = tuple(
            guard_element(e, policy=policy, claim_quote=claim_quote) for e in run.guarded.elements
        )
        changed = [e for e, old in zip(elements, run.guarded.elements, strict=True) if e != old]
        if not changed:
            results.append(run)
            continue
        errors = tuple(
            dict.fromkeys((*run.errors, *(f"UNRESOLVED:{e.element_id}" for e in changed)))
        )
        results.append(
            replace(
                run,
                guarded=replace(run.guarded, elements=elements),
                status="needs_review",
                errors=errors,
            )
        )
    return tuple(results)


def estimate_refs(
    data: dict, original: CanonicalDocumentGraph | None = None, *, policy=None
) -> list[dict]:
    """DEC-24 hold eligibility; only local numeric rows or their exact parent table.

    No nearby table, other page, document-wide Scope3 mention or model paraphrase
    establishes table membership. Existing category votes retain their own path.
    """
    if policy is not None and policy != POLICY:
        validate_policy(policy)
        from proofops.application.tagging.k4_contract import SEMANTIC_POLICY
        from proofops.application.tagging.k10_contract import SEMANTIC_POLICY as K10_POLICY
        from proofops.application.tagging.k10_contract import SEMANTIC_V2_POLICY as K10_V2_POLICY
        from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_POLICY

        if policy in (SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY):
            from proofops.application.tagging.k4_contract import estimate_evidence

            return estimate_evidence(data, original)
        from proofops.application.tagging.k1_semantics import estimate_evidence

        return estimate_evidence(data, original)
    refs = data.get("claim_source_refs", [])
    if data.get("safe_harbor_category") == "emissions_estimate":
        return refs
    if data.get("track") != "performance" or not data.get("table_observation_evidence"):
        return []
    if any(re.search(_SCOPE3, ref["quote"], re.I) for ref in refs):
        return refs
    if original is None or (original.tenant_id, original.document_version_id) != (
        data["tenant_id"],
        data["document_version_id"],
    ):
        return []
    blocks = {b.source_id: b for b in original.blocks}
    for ref in refs:
        table = blocks.get(ref["source_id"])
        if table is None or table.kind != "table" or table.winner is None:
            continue
        text = table.raw_text
        if re.search(_SCOPE3, text, re.I) and not re.search(
            r"scope\s*[12]|스코프\s*[12]", text, re.I
        ):
            return refs
    return []
