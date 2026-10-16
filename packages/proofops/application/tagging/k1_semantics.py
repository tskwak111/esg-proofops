"""K1 literal admission vetoes; no semantic classification or present generation."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from proofops.application.tagging.dec24 import INTEGRATED_V2_DEFINITIONS
from proofops.application.tagging.semantic_admission import POLICY as W8_POLICY
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import LlmElement

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph

GUIDANCE = " ".join(
    """
K1/v2 §4.2/4.4/4.5: PUE value maintenance is performance, not a named
implementation means. PUE 1.1x is a masked value band: cite the literal 1.1x,
never normalize it to exact 1.1/1.10/1.19, a multiplier, percent or unit.
No approved band-to-P1 mapping: keep P1 unknown for band-only evidence.
Separate identical PUE claims by their source offsets/facilities; never merge.
An actor plus 'RE100 이행을 위해' states subject/purpose, not organizational
coverage; M2 needs explicit organizations/facilities covered by the process.
Do not borrow the adjacent diagram's 전 사업장 into this citation.
Scope3 table exclusions of Scope1/2 describe a Scope3 category, not mixed
Scope1/2 observations. Same-parent numeric items retain estimate holds.
""".split()
)
DEFINITIONS = INTEGRATED_V2_DEFINITIONS + "\n" + GUIDANCE
EXCLUSION = (
    r"(?:scope|스코프)\s*1\s*(?:&|및|and)\s*(?:(?:scope|스코프)\s*)?2" r"\s*에\s*포함되지\s*않은"
)
PUE_ONLY = r"\s*[•·]?\s*PUE(?:\s*\([^)]*\))?(?:\d+\))?(?:\s+\d+\.\d+[xX]\s*유지)?\s*"
BAND = r"(?<![\w.])\d+\.\d+[xX](?!\w)"
ACTOR_PURPOSE = r"^.{1,60}(?:은|는)?\s*RE100\s*이행(?:을)?\s*위해\s*[.!]?\s*$"
BOUNDARY = r"전사|국내|해외|글로벌|전체|모든|사업장|공장|법인|부문|자회사|계열사"
POLICY = W8_POLICY | dict(
    profile="tagging-semantic-admission-k1-v1",
    definitions_sha256=canonical_hash(DEFINITIONS),
    scope12_exclusion_pattern=EXCLUSION,
    pue_only_pattern=PUE_ONLY,
    masked_value_pattern=BAND,
    actor_purpose_pattern=ACTOR_PURPOSE,
    explicit_boundary_pattern=BOUNDARY,
    track_conflict="retag-required-no-numeric-range",
)


def guard(element: LlmElement, *, claim_quote: str = "") -> LlmElement:
    if element.state != "present":
        return element
    quotes = [" ".join(ref.quote.split()) for ref in element.evidence_refs]
    reason = None
    if (
        element.element_id == "M1"
        and quotes
        and all(re.fullmatch(PUE_ONLY, quote, re.I) for quote in quotes)
    ):
        reason = "K1_PUE_METRIC_IS_NOT_IMPLEMENTATION"
    elif (
        element.element_id == "M2"
        and quotes
        and all(
            re.fullmatch(ACTOR_PURPOSE, quote, re.I) and not re.search(BOUNDARY, quote)
            for quote in quotes
        )
    ):
        reason = "K1_M2_ACTOR_PURPOSE_IS_NOT_BOUNDARY"
    elif element.element_id == "P1" and (
        any(re.search(BAND, quote) for quote in quotes)
        or (re.search(r"\bPUE\b", claim_quote, re.I) and re.search(BAND, claim_quote))
    ):
        reason = "K1_MASKED_VALUE_REQUIRES_REVIEW"
    return (
        replace(
            element, state="unknown", normalized_value=None, credited_from=None, reason_code=reason
        )
        if reason
        else element
    )


def track_requires_review(quote: str, track: str) -> bool:
    return track != "performance" and bool(re.fullmatch(PUE_ONLY, quote, re.I))


def masked_pue(quote: str) -> bool:
    return bool(re.search(r"\bPUE\b", quote, re.I) and re.search(BAND, quote))


def estimate_evidence(data: dict, original: CanonicalDocumentGraph | None) -> list[dict]:
    refs = data.get("claim_source_refs", [])
    if data.get("safe_harbor_category") == "emissions_estimate":
        return refs
    if data.get("track") != "performance" or not data.get("table_observation_evidence"):
        return []
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
        if (ref["document_version_id"], ref["parse_manifest_id"]) != (
            original.document_version_id,
            original.parse_manifest_id,
        ) or table.raw_text[ref["char_start"] : ref["char_end"]] != ref["quote"]:
            continue
        # Only mask the literal exclusion label for this test, never source bytes.
        text = re.sub(EXCLUSION, "", table.raw_text, flags=re.I)
        if re.search(r"scope\s*3|스코프\s*3", text, re.I) and not re.search(
            r"scope\s*[12]|스코프\s*[12]", text, re.I
        ):
            return refs
    return []
