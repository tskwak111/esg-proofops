"""Narrow M1 source admission for the DEC-92 preceding named review means.

The catalog only proposes sources. Model selection, source verification,
relation binding and three independent replicas still precede publication.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.qt2_context import _contains, context_refs
from proofops.application.tagging.v3_dec92 import EXISTING, NAMED_REVIEW, POLICY

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from proofops.application.claims import Claim
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.domain.values import SourceRef


def preceding_means(
    claim: Claim, graph: CanonicalDocumentGraph, *, tenant_id: str
) -> tuple[SourceRef, ...]:
    if len(claim.source_refs) != 1:
        return ()
    focal = claim.source_refs[0]
    preceding = [
        r for r in context_refs(claim, graph, tenant_id=tenant_id) if r.char_end <= focal.char_start
    ]
    if not preceding:
        return ()
    ref = max(preceding, key=lambda r: r.char_end)
    block = next(b for b in graph.blocks if b.source_id == focal.source_id)
    if block.raw_text[ref.char_end : focal.char_start].strip():
        return ()  # A skipped long/unverified sentence is still a boundary.
    # No look-through of a different sentence, bullet or paragraph. QT2 bounds
    # and verifies the exact paragraph before this narrower M1 filter.
    if re.search(NAMED_REVIEW, ref.quote) and re.search(EXISTING, ref.quote):
        return (ref,)
    return ()


def augment_packet(
    data: dict[str, Any], claim: Claim, graph: CanonicalDocumentGraph, *, tenant_id: str
) -> dict[str, Any]:
    data["v3_dec92_policy"] = POLICY
    if "M1" not in data["allowed_elements"]:
        return data  # Never add M1 or change a future promise's goal track.
    for ref in preceding_means(claim, graph, tenant_id=tenant_id):
        candidate = next(
            (c for c in data["evidence_candidates"] if c["source_id"] == ref.source_id), None
        )
        if candidate is None:
            candidate = dict(
                source_id=ref.source_id,
                source_scope="local_claim",
                allowed_elements=["M1"],
                source_refs=[],
            )
            data["evidence_candidates"].append(candidate)
        if "M1" not in candidate["allowed_elements"]:
            candidate["allowed_elements"].append("M1")
        if asdict(ref) not in candidate["source_refs"]:
            candidate["source_refs"].append(asdict(ref))
    return data


def accepts_context(
    context: ClaimContext,
    ref: SourceRef,
    graph: CanonicalDocumentGraph,
    *,
    tenant_id: str,
    element_id: str,
    relation_tags: Mapping[str, SourceRef | None] | None = None,
) -> bool:
    if element_id != "M1":
        return False
    claim = context.claim
    candidates = preceding_means(claim, graph, tenant_id=tenant_id)
    # Full sentence required: cannot hide a foreign actor, future or negation
    # by selecting just the name of a procedure.
    if not any(
        _contains(r, ref) and _contains(ref, r) and r.quote == ref.quote for r in candidates
    ):
        return False
    if verify_source_ref(ref, graph, tenant_id=tenant_id).verification_state != "verified":
        return False
    focal = claim.source_refs[0]
    entity, activity = (context.dimensions.get(k) for k in ("entity", "metric"))
    if entity is None or activity is None or len(activity.quote.strip()) < 3:
        return False
    # Exact continuing subject; a substring in another company's name is not
    # continuity. Both atomic claim and means must actually name this actor.
    actor = r"^(?:또한[, ]*|그리고[, ]*)?" + re.escape(entity.quote) + r"(?:은|는|의|에서|이|가)\s"
    if not all(re.search(actor, text.strip()) for text in (claim.quote, ref.quote)):
        return False
    if activity.quote not in ref.quote:
        return False
    if re.search(r"않|아니|없|중단|폐지|예정|계획|방침", ref.quote):
        return False
    years = r"(?<!\d)(?:19|20)\d{2}\s*년"
    if set(re.findall(years, claim.quote)) != set(re.findall(years, ref.quote)):
        return False
    for name, expected in context.dimensions.items():
        if expected is None and name in ("facility", "scope", "product", "material", "boundary"):
            return False
        actual = (relation_tags or {}).get(name)
        if actual is not None and (expected is None or actual.quote != expected.quote):
            return False
        for value in (expected, actual):
            if value is not None and (
                verify_source_ref(value, graph, tenant_id=tenant_id).verification_state
                != "verified"
                or not (_contains(focal, value) or _contains(ref, value))
            ):
                return False
        if expected is not None and (
            not _contains(focal, expected) or expected.quote not in ref.quote
        ):
            return False
    return not any(
        v is not None and k not in context.dimensions for k, v in (relation_tags or {}).items()
    )
