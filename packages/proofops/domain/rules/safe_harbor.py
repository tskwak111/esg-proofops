"""Pure safe-harbor evidence record path (TASK-016 / FR-016).

GAP-001 leaves both grading and reasonable-basis mappings unapproved.  This
module therefore records the pinned checklist and evidence states without
producing an E grade, legal conclusion, or boolean reasonable-basis result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from proofops.domain.errors import DomainValidationError
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import ConfirmedTags, RuleContext, _validate_inputs
from proofops.domain.values import ElementState, SourceRef

MappingStatus = Literal["approved", "unresolved"]


@dataclass(frozen=True, slots=True)
class SafeHarborChecklistItem:
    element_id: str
    state: ElementState
    evidence_refs: tuple[SourceRef, ...]
    normalized_value: str | None
    credited_from: str | None = None
    reason_code: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        refs = []
        for ref in self.evidence_refs:
            value = asdict(ref)
            value["bbox"] = list(ref.bbox) if ref.bbox is not None else None
            refs.append(value)
        return {
            "element_id": self.element_id,
            "state": self.state,
            "evidence_refs": refs,
            "normalized_value": self.normalized_value,
            "credited_from": self.credited_from,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class SafeHarborRecord:
    claim_id: str
    applicable: bool | None
    category: str | None
    checklist: tuple[SafeHarborChecklistItem, ...]
    reasonable_basis_documented: bool | None
    legal_effect: Literal["not_determined"]
    mapping_status: MappingStatus
    gap_ids: tuple[str, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "applicable": self.applicable,
            "category": self.category,
            "checklist": [item.to_api_dict() for item in self.checklist],
            "reasonable_basis_documented": self.reasonable_basis_documented,
            "legal_effect": self.legal_effect,
            "mapping_status": self.mapping_status,
            "gap_ids": list(self.gap_ids),
        }


def record_safe_harbor(
    tags: ConfirmedTags,
    context: RuleContext,
    pack: RulePackSnapshot,
) -> SafeHarborRecord:
    """Record the category checklist without crossing unresolved GAP-001."""
    _validate_inputs(tags, context, pack)
    category = tags.safe_harbor_category
    if category is None:
        return SafeHarborRecord(
            tags.claim_id, False, None, (), None, "not_determined", "unresolved", ()
        )

    try:
        config = pack.file_content("regulatory/safe_harbor.yaml")
        expected = config["category_checklists"][category]
    except (KeyError, TypeError) as exc:
        raise DomainValidationError("safe-harbor category checklist is not pinned") from exc
    if not isinstance(expected, list) or any(
        not isinstance(name, str) or not name for name in expected
    ):
        raise DomainValidationError("safe-harbor category checklist is invalid")

    facts = {fact.name: fact for fact in tags.facts}
    checklist = tuple(
        SafeHarborChecklistItem(
            name,
            facts[name].state if name in facts else "unknown",
            facts[name].evidence_refs if name in facts else (),
            facts[name].normalized_value if name in facts else None,
        )
        for name in expected
    )
    if (
        config.get("grade_mapping") is not None
        or config.get("reasonable_basis_boolean_mapping") is not None
    ):
        raise DomainValidationError("GAP-001 approved mapping contract is not implemented")
    return SafeHarborRecord(
        tags.claim_id,
        True,
        category,
        checklist,
        None,
        "not_determined",
        "unresolved",
        ("GAP-001",),
    )
