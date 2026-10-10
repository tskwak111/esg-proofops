"""Strict new wire boundary, returning proposals only, never verified roles.

Catalog and expected identity/role are trusted server-side inputs. This does
not authenticate a caller or replace source visibility, citation, semantic
binding, or role validation. A digest alone is not a verification receipt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from proofops.application.ingest.span_alignment import (
    SourceIdentity,
    SpanCandidate,
    validate_candidate,
)
from proofops.domain.errors import DomainValidationError

_ROLES = frozenset(
    {
        "entity",
        "metric",
        "reporting_period",
        "facility",
        "scope",
        "product",
        "material",
        "boundary",
        "value",
        "unit",
        "row_header",
        "column_header",
        "footnote",
        "subject",
        "predicate",
        "qualifier",
    }
)


@dataclass(frozen=True)
class OccurrenceSelection:
    role: str
    span: SpanCandidate | None

    @property
    def verification_state(self) -> str:
        return "candidate"

    @property
    def role_state(self) -> str:
        return "unresolved"


def select_occurrence(
    identity: SourceIdentity,
    catalog: Sequence[SpanCandidate],
    wire: Mapping[str, object],
    *,
    expected_identity: SourceIdentity,
    expected_role: str,
) -> OccurrenceSelection:
    """Select one issued ID or null. No offset, quote or approval fields allowed.

    A matching role name only checks the requested slot. Correct position never
    establishes correct meaning (e.g. a target year is not a reporting period).
    Even a known wrong semantic role remains unresolved, with no approval API.
    """
    if identity != expected_identity:
        raise DomainValidationError("SPAN_IDENTITY_MISMATCH")
    if not isinstance(wire, Mapping) or set(wire) != {"schema", "source_id", "role", "span_id"}:
        raise DomainValidationError("SPAN_SELECTION_SHAPE")
    if wire["schema"] != "occurrence-selection-v1":
        raise DomainValidationError("SPAN_SELECTION_VERSION")
    if wire["source_id"] != identity.source_id:
        raise DomainValidationError("SPAN_IDENTITY_MISMATCH")
    if expected_role not in _ROLES or wire["role"] != expected_role:
        raise DomainValidationError("SPAN_ROLE_MISMATCH")
    by_id = {}
    for candidate in catalog:
        validate_candidate(candidate, identity)
        if candidate.span_id in by_id:
            raise DomainValidationError("SPAN_DUPLICATE_ID")
        by_id[candidate.span_id] = candidate
    span_id = wire["span_id"]
    if span_id is None:
        return OccurrenceSelection(expected_role, None)
    if not isinstance(span_id, str) or span_id not in by_id:
        raise DomainValidationError("SPAN_UNKNOWN_ID")
    return OccurrenceSelection(expected_role, by_id[span_id])
