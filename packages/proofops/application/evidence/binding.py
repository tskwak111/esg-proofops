"""Source-backed, deterministic claim attribution (FR-013 / TASK-013).

Inputs are internal immutable claim/tag revisions and a tenant-authorized original
snapshot. Relation tags assign semantic roles to literal SourceRefs, never grades.
This pure guard returns a binding state; callers retain the input tag receipt,
model/prompt/rule hashes, replica and graph with that state in a new revision.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from unicodedata import normalize

from proofops.application.claims import Claim
from proofops.application.evidence.citations import verify_source_ref
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.domain.errors import DomainValidationError
from proofops.domain.periods import is_supported_period
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef, _require_uuid

BindingState = Literal["accepted", "undetermined", "rejected"]
_DIMENSIONS = frozenset(
    ("entity", "metric", "reporting_period", "facility", "scope", "product", "material", "boundary")
)


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

    Entity/metric/period are required for automatic attribution. The upstream
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


def accept_binding(
    context: ClaimContext,
    ref: SourceRef,
    relation_tags: Mapping[str, SourceRef | None],
    *,
    original: CanonicalDocumentGraph,
    tenant_id: str,
    rulepack: RulePackSnapshot,
    element_id: str,
) -> BindingState:
    """Check source identity, literal roles, table coordinates and allowed scope.

    A matching quote alone cannot accept attribution. Same-row context may
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
    evidence_dimensions = _dimensions(relation_tags)
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
            return "rejected"
        block = blocks[source.source_id]
        if block.quality != "verified" or block.winner is None:
            return "undetermined"
        result = verify_source_ref(source, original, tenant_id=tenant_id)
        return "accepted" if result.verification_state == "verified" else "rejected"

    if not claim.source_refs or claim.quote != " ".join(s.quote for s in claim.source_refs):
        return "rejected"
    unresolved = claim.source_quality != "verified"
    for source in (*claim.source_refs, ref):
        state = checked(source)
        if state == "rejected":
            return state
        unresolved |= state == "undetermined"
    if unresolved:
        return "undetermined"

    def selected(source: SourceRef):
        block = blocks[source.source_id]
        return block.candidates[block.winner]  # checked above before coordinate access

    def contains(outer: SourceRef, inner: SourceRef) -> bool:
        return outer.source_id == inner.source_id and (
            outer.char_start <= inner.char_start < inner.char_end <= outer.char_end
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

    names = (
        set(context.dimensions)
        | set(evidence_dimensions)
        | {"entity", "metric", "reporting_period"}
    )
    for name in sorted(names):
        expected, actual = context.dimensions.get(name), evidence_dimensions.get(name)
        if expected is None or actual is None:
            unresolved = True
            continue
        states = (checked(expected), checked(actual))
        if "rejected" in states:
            return "rejected"
        if "undetermined" in states:
            unresolved = True
            continue
        claim_states = [
            attributed(expected, s, atomic=True, dimension=name) for s in claim.source_refs
        ]
        evidence_state = attributed(actual, ref, atomic=False, dimension=name)
        if evidence_state == "rejected" or all(s == "rejected" for s in claim_states):
            return "rejected"
        if evidence_state == "undetermined" or "accepted" not in claim_states:
            unresolved = True
        if normalize("NFC", expected.quote).strip() != normalize("NFC", actual.quote).strip():
            return "rejected"
        if name == "reporting_period" and not is_supported_period(expected.quote):
            unresolved = True
    if unresolved:
        return "undetermined"

    scopes = definition["source_scopes"]
    local = any(contains(source, ref) for source in claim.source_refs)
    tables = [source for source in claim.source_refs if same_table(source, ref)]
    if local and "local_claim" in scopes:
        return "accepted"
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
