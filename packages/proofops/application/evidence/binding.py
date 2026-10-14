"""Source-backed, deterministic claim attribution.

Inputs are internal immutable claim/tag revisions and a tenant-authorized original
snapshot. Relation tags assign semantic roles to literal SourceRefs, never grades.
This pure guard returns a binding state; callers retain the input tag receipt,
model/prompt/rule hashes, replica and graph with that state in a new revision.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from unicodedata import normalize

from proofops.application.claims import Claim
from proofops.application.evidence.report_level import scope_rejection_reason
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.domain.errors import DomainValidationError
from proofops.domain.periods import is_supported_period
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef, _require_uuid

BindingState = Literal["accepted", "undetermined", "rejected"]
_DIMENSIONS = frozenset(
    ("entity", "metric", "reporting_period", "facility", "scope", "product", "material", "boundary")
)


# These cues demand sourced roles; they never establish semantic agreement.
# ponytail: explicit Korean/English cues only; broader paraphrases need semantic tagging.
_AXIS_CUES = {
    "boundary": re.compile(
        r"(?<![가-힣])(?:연결(?=\s*(?:기준|범위|실체|재무|환경|배출|대상|$))"
        r"|별도(?=\s*(?:기준|범위|재무|환경|배출|대상|$)))"
        r"|\b(?:consolidated|standalone|separate)(?=\s+(?:basis|boundary|financial|emissions)|$)",
        re.IGNORECASE,
    ),
    "scope": re.compile(
        r"\bscopes?\s*[123](?:\s*(?:&|,|/|및|and|[-–+·])\s*(?:scope\s*)?[123])*(?!\d)",
        re.IGNORECASE,
    ),
}


def _axis_cues(text: str, axis: str) -> set[str]:
    return {
        "".join(match.group().casefold().split())
        for match in _AXIS_CUES[axis].finditer(normalize("NFC", text))
    }


def _dimensions(values: Mapping[str, SourceRef | None]) -> dict[str, SourceRef | None]:
    if (
        not isinstance(values, Mapping)
        or set(values) - _DIMENSIONS
        or any(value is not None and not isinstance(value, SourceRef) for value in values.values())
    ):
        raise DomainValidationError("dimensions require source refs; grades/labels are forbidden")
    return dict(values)


@dataclass(frozen=True, slots=True)
class ClaimContext:
    """Literal dimension spans within the atomic claim or its explicit table row.

    Entity/metric/period are required for cross-source attribution. The upstream
    semantic tagger supplies every applicable product/material/facility/Scope/
    boundary axis; a supplied null is unresolved, never not_applicable. Missing
    semantic roles cannot be inferred from document-wide word occurrence.
    """

    claim: Claim
    dimensions: Mapping[str, SourceRef | None]

    def __post_init__(self):
        if not isinstance(self.claim, Claim):
            raise DomainValidationError("internal Claim required")
        object.__setattr__(self, "dimensions", MappingProxyType(_dimensions(self.dimensions)))


def local_relation_tags(context: ClaimContext) -> dict[str, dict[str, SourceRef | None]]:
    """Retain validated claim roles only within each original atomic source span."""
    return {
        f"{source.source_id}:{source.char_start}:{source.char_end}": {
            role: ref
            if ref is not None
            and ref.source_id == source.source_id
            and source.char_start <= ref.char_start < ref.char_end <= source.char_end
            else None
            for role, ref in context.dimensions.items()
        }
        for source in context.claim.source_refs
    }


def relation_tags_for(
    ref: SourceRef, relations: Mapping[str, Mapping[str, SourceRef | None]]
) -> Mapping[str, SourceRef | None] | None:
    """Resolve one unambiguous containing scope; retain legacy whole-source maps.

    Scoped entries shadow legacy entries, including unresolved/malformed scopes.
    Source verification and semantic attribution still belong to accept_binding.
    """
    scoped = [
        (key, roles) for key, roles in relations.items() if key.startswith(ref.source_id + ":")
    ]
    if not scoped:
        return relations.get(ref.source_id, {})
    matches = []
    for key, roles in scoped:
        try:
            source_id, begin, end = key.split(":")
            start, stop = int(begin), int(end)
        except ValueError:
            return None
        if start < 0 or stop <= start or key != f"{source_id}:{start}:{stop}":
            return None
        if start <= ref.char_start < ref.char_end <= stop:
            if any(
                role is not None
                and (
                    role.source_id != ref.source_id
                    or not start <= role.char_start < role.char_end <= stop
                )
                for role in roles.values()
            ):
                return None
            matches.append(roles)
    return matches[0] if len(matches) == 1 else None


def accept_binding(
    context: ClaimContext,
    ref: SourceRef,
    relation_tags: Mapping[str, SourceRef | None] | None,
    *,
    original: CanonicalDocumentGraph,
    tenant_id: str,
    rulepack: RulePackSnapshot,
    element_id: str,
    local_value_identity: bool = False,
    local_binding_policy: Mapping | None = None,
    structural_policy: Mapping | None = None,
    allow_edge_whitespace: bool = False,
    diagnostics: list[str] | None = None,
) -> BindingState:
    """Check source identity, literal roles, table coordinates and allowed scope.

    Exact local containment establishes literal attribution, not semantic element
    sufficiency. Cross-source matching requires typed roles. Same-row context may
    supply literal dimensions; a column header needs an explicit table_parent
    edge from the selected cell. Incomplete coordinates and unresolved GAP-004
    links stay undetermined; aliases and cross-page table joins are not inferred.
    This does not infer assurance coverage, award present, or write revisions.
    """
    if not isinstance(context, ClaimContext) or not isinstance(original, CanonicalDocumentGraph):
        raise DomainValidationError("internal claim context and canonical snapshot required")
    if not isinstance(ref, SourceRef) or not isinstance(rulepack, RulePackSnapshot):
        raise DomainValidationError("SourceRef and pinned rulepack required")
    _require_uuid("tenant_id", tenant_id)
    claim = context.claim
    if structural_policy is not None:
        from proofops.application.tagging.q1_contract import validate_policy

        validate_policy(structural_policy)
    if type(allow_edge_whitespace) is not bool:
        raise DomainValidationError("edge-whitespace binding policy must be boolean")

    def diagnose(reason: str):
        from proofops.application.tagging.q1_contract import QUALITY_POLICIES

        if (
            structural_policy in QUALITY_POLICIES
            and diagnostics is not None
            and reason not in diagnostics
        ):
            diagnostics.append(reason)

    _require_uuid("claim_id", claim.claim_id)
    if (claim.tenant_id, original.tenant_id, rulepack.tenant_id) != (tenant_id,) * 3 or (
        claim.document_version_id,
        claim.parse_manifest_id,
        claim.source_sha256,
    ) != (original.document_version_id, original.parse_manifest_id, original.source_sha256):
        raise DomainValidationError("claim/graph/rulepack identity mismatch")
    definitions = rulepack.file_content("rubric/elements.yaml")["elements"]
    definition = next((item for item in definitions if item["id"] == element_id), None)
    if definition is None:
        raise DomainValidationError("unknown element")
    if scope_rejection_reason(element_id, (ref,), rulepack=rulepack, original=original):
        diagnose("source_scope_rejected")
        return "rejected"
    evidence_dimensions = _dimensions(relation_tags) if relation_tags is not None else {}
    blocks = {block.source_id: block for block in original.blocks}
    if len(blocks) != len(original.blocks) or any(
        edge.source_id not in blocks or edge.target_id not in blocks for edge in original.edges
    ):
        raise DomainValidationError("invalid source lineage")

    def checked(source: SourceRef) -> BindingState:
        if (source.document_version_id, source.parse_manifest_id) != (
            original.document_version_id,
            original.parse_manifest_id,
        ) or source.source_id not in blocks:
            diagnose("source_identity_rejected")
            return "rejected"
        block = blocks[source.source_id]
        if block.winner is None:
            diagnose("source_unresolved")
            return "undetermined"  # conflicted/missing winner stays blocked
        result = verify_source_ref(source, original, tenant_id=tenant_id)
        if result.verification_state == "verified":
            # verified block, or an unverified block whose trusted verified span
            # exactly contains this ref (span-aware verifier, no block promotion).
            return "accepted"
        if block.quality != "verified":
            # ordinary unverified/unlocated block without a trusted verified span:
            # unresolved source quality, not a source-identity rejection.
            diagnose("source_unverified")
            return "undetermined"
        diagnose("source_literal_rejected")
        return "rejected"

    if not claim.source_refs or claim.quote != " ".join(s.quote for s in claim.source_refs):
        return "rejected"
    unresolved = claim.source_quality != "verified"
    for source in (*claim.source_refs, ref):
        state = checked(source)
        if state == "rejected":
            return state
        unresolved |= state == "undetermined"
    if local_binding_policy is not None:
        from proofops.application.tagging.k9_contract import (
            BINDING_POLICY,
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
            scope_definition_identity,
        )

        if local_binding_policy not in (
            BINDING_POLICY,
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
        ):
            raise DomainValidationError("K9_BINDING_POLICY_MISMATCH")
        if (
            not unresolved
            and element_id == "G4"
            and scope_definition_identity(context, ref, original, policy=local_binding_policy)
        ):
            for name, value in context.dimensions.items():
                if value is None:
                    continue
                state = checked(value)
                if state != "accepted":
                    return state
                if name == "scope" and _axis_cues(value.quote, "scope") != _axis_cues(
                    ref.quote, "scope"
                ):
                    return "rejected"
                if name != "scope" and not any(
                    value.source_id == s.source_id
                    and s.char_start <= value.char_start < value.char_end <= s.char_end
                    for s in claim.source_refs
                ):
                    return "rejected"
                actual = evidence_dimensions.get(name)
                if actual is not None and (
                    checked(actual) != "accepted" or actual.quote != value.quote
                ):
                    return "rejected"
            return "accepted"
    if unresolved or relation_tags is None:
        diagnose("claim_source_unverified" if unresolved else "relation_tags_unresolved")
        return "undetermined"

    def selected(source: SourceRef):
        block = blocks[source.source_id]
        return block.candidates[block.winner]  # checked above before coordinate access

    def contains(outer: SourceRef, inner: SourceRef) -> bool:
        return outer.source_id == inner.source_id and (
            outer.char_start <= inner.char_start < inner.char_end <= outer.char_end
        )

    def whitespace_encloses(outer: SourceRef, inner: SourceRef) -> bool:
        """Permit an exact claim quote with only source-bound edge whitespace."""
        if outer.source_id != inner.source_id or outer.quote.strip() != inner.quote:
            return False
        leading = len(outer.quote) - len(outer.quote.lstrip())
        trailing = len(outer.quote) - len(outer.quote.rstrip())
        return (
            outer.char_start + leading == inner.char_start
            and outer.char_end - trailing == inner.char_end
        )

    def same_table(left: SourceRef, right: SourceRef) -> bool:
        a, b = selected(left), selected(right)
        return bool(a.table_native_id) and (
            a.source.parser_run_id,
            a.source.physical_page,
            a.table_native_id,
        ) == (b.source.parser_run_id, b.source.physical_page, b.table_native_id)

    def attributed(
        anchor: SourceRef, target: SourceRef, *, atomic: bool, dimension: str
    ) -> BindingState:
        if anchor.source_id == target.source_id:
            return "accepted" if not atomic or contains(target, anchor) else "rejected"
        if not same_table(anchor, target):
            return "rejected"
        a, b = selected(anchor), selected(target)
        if any(
            type(value) is not int or value < 0
            for value in (a.row_number, b.row_number, a.column_number, b.column_number)
        ):
            return "undetermined"
        spans = tuple(
            1 if value is None else value
            for value in (a.row_span, a.column_span, b.row_span, b.column_span)
        )
        if any(type(value) is not int or value < 1 for value in spans):
            return "undetermined"
        ar, ac, br, bc = spans
        row_covers = a.row_number <= b.row_number and b.row_number + br <= a.row_number + ar
        column_covers = (
            a.column_number <= b.column_number and b.column_number + bc <= a.column_number + ac
        )
        if dimension == "reporting_period" and not column_covers:
            return "rejected"
        if row_covers:
            return "accepted"
        if (
            column_covers
            and a.row_number + ar <= b.row_number
            and any(
                edge.source_id == target.source_id
                and edge.target_id == anchor.source_id
                and edge.relation == "table_parent"
                for edge in original.edges
            )
        ):
            return "accepted"
        return "rejected"

    scopes = definition["source_scopes"]
    local = any(
        contains(source, ref) or (allow_edge_whitespace and whitespace_encloses(ref, source))
        for source in claim.source_refs
    )
    direct = local and "local_claim" in scopes
    intrinsic = False
    if local_binding_policy is not None:
        from proofops.application.tagging.k9_contract import (
            BINDING_POLICY,
            local_implementation_identity,
        )

        if local_binding_policy not in (
            BINDING_POLICY,
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
        ):
            raise DomainValidationError("K9_BINDING_POLICY_MISMATCH")
        if direct and element_id in BINDING_POLICY["elements"]:
            intrinsic = local_implementation_identity(
                context, ref, original, policy=local_binding_policy, element_id=element_id
            )
    if local_value_identity and direct:
        from proofops.application.tagging.k2_recovery import local_intrinsic

        intrinsic |= local_intrinsic(claim, ref, element_id)
        # The scalar/year/means belongs to this atomic claim, not a cross-source
        # join. Null axes do not deny that literal identity; asserted roles still
        # undergo the same source, containment, period and contradiction checks.
    if not direct:
        # A numeric subspan may omit its boundary qualifier: inspect its containing
        # canonical block too. Multiple contexts conservatively require review.
        for text, roles in (
            (claim.quote, context.dimensions),
            (blocks[ref.source_id].source_ref().quote, evidence_dimensions),
        ):
            for axis in _AXIS_CUES:
                role = roles.get(axis)
                if not _axis_cues(text, axis) <= _axis_cues(role.quote if role else "", axis):
                    unresolved = True
    names = (
        set(context.dimensions)
        | set(evidence_dimensions)
        | {"entity", "metric", "reporting_period"}
    )
    for name in sorted(names):
        expected, actual = context.dimensions.get(name), evidence_dimensions.get(name)
        explicit_axis_unknown = name not in {"entity", "metric", "reporting_period"} and (
            (name in context.dimensions and expected is None)
            or (name in evidence_dimensions and actual is None)
        )
        if (expected is None or actual is None) and (
            not direct or (explicit_axis_unknown and not intrinsic)
        ):
            diagnose(f"dimension_unresolved:{name}")
            unresolved = True
            continue
        states = [checked(value) for value in (expected, actual) if value is not None]
        if "rejected" in states:
            return "rejected"
        if "undetermined" in states:
            unresolved = True
            continue
        for value, in_claim in ((expected, True), (actual, direct)):
            if value is None:
                continue  # Local identity does not invent the missing semantic role.
            targets = claim.source_refs if in_claim or intrinsic else (ref,)
            role_states = [
                attributed(value, target, atomic=in_claim, dimension=name) for target in targets
            ]
            if all(state == "rejected" for state in role_states):
                diagnose(f"role_attribution_rejected:{name}")
                return "rejected"
            if "accepted" not in role_states:
                unresolved = True
            if name == "reporting_period" and not is_supported_period(value.quote):
                from proofops.application.tagging.q1_contract import observed_period

                if not (
                    structural_policy is not None
                    and direct
                    and intrinsic
                    and observed_period(value.quote, policy=structural_policy)
                ):
                    diagnose("period_syntax_unsupported")
                    unresolved = True
        if (
            expected is not None
            and actual is not None
            and (normalize("NFC", expected.quote).strip() != normalize("NFC", actual.quote).strip())
        ):
            diagnose(f"dimension_mismatch:{name}")
            return "rejected"
    if unresolved:
        return "undetermined"
    if direct:
        return "accepted"
    tables = [source for source in claim.source_refs if same_table(source, ref)]
    if tables and "same_table" in scopes:
        candidate = selected(ref)
        if any(
            type(value) is not int or value < 0
            for value in (candidate.row_number, candidate.column_number)
        ):
            return "undetermined"
        # Do not borrow a different year's column even when row words match.
        if any(selected(source).column_number == candidate.column_number for source in tables):
            return "accepted"
        return "rejected"
    if "global_bound" in scopes:
        return "accepted"
    if "explicit_link" in scopes and element_id != "G3":
        return "undetermined"  # GAP-004 requires an approved source-scope interpretation.
    return "rejected"
