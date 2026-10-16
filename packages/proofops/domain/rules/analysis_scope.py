"""DEC-85 opt-in rule profile. Legacy evaluator and revision hashes stay unchanged."""

from dataclasses import asdict, dataclass, replace

from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import Decision, _evaluate

PROFILE = "analysis-scope-rules-sc1-v1"
POLICY = {
    "profile": PROFILE,
    "absence": "absent_in_scope_only_with_complete_same_run_search_receipt",
    "conflict": "never_confirm",
    "required_positive_facts": "pinned_agreement_threshold_independent_verified_bound_votes",
    "unknown": "remains_unknown_without_new_search_evidence",
}
POLICY_HASH = canonical_hash(POLICY)
DISPLAY = "분석 범위 기준 확정"


@dataclass(frozen=True, slots=True)
class ScopeDecision(Decision):
    confirmation_basis: str = "analysis_scope"
    confirmation_display: str = DISPLAY
    confirmation_scope: dict | None = None
    confirmation_policy_sha256: str = POLICY_HASH

    def to_api_dict(self):
        return super(ScopeDecision, self).to_api_dict() | {
            key: getattr(self, key)
            for key in (
                "confirmation_basis",
                "confirmation_display",
                "confirmation_scope",
                "confirmation_policy_sha256",
            )
        }


def evaluate_scope(tags, context, pack, *, scope, absent_facts, receipt_sha256):
    """Trusted application boundary, analogous to ConfirmedTags citation attestations.

    The application must replay the complete search receipt before calling this.
    A scoped state is never submitted to the historical full-evidence evaluator.
    """
    required = {
        "tenant_id": tags.tenant_id,
        "document_version_id": tags.document_version_id,
    }
    if (
        any(scope.get(key) != value for key, value in required.items())
        or not scope.get("run_id")
        or not scope.get("selected_pages")
        or scope.get("uninspected_pages")
        or scope.get("inspected_pages") != scope["selected_pages"]
        or scope.get("rule_policy_sha256") != POLICY_HASH
        or set(absent_facts) != {f.name for f in tags.facts if f.state == "absent_in_scope"}
        or not absent_facts
        or any(f.state == "conflict" for f in tags.facts)
    ):
        raise DomainValidationError("SC1_SCOPE_NOT_CONFIRMABLE")
    decision = _evaluate(tags, context, pack, analysis_scope=True)
    if decision.decision_status != "decided":
        return decision
    result = ScopeDecision(
        **asdict(decision),
        confirmation_scope=scope | {"search_receipt_sha256": receipt_sha256},
        confirmation_policy_sha256=scope["confirmation_policy_sha256"],
    )
    return replace(
        result,
        semantic_hash=canonical_hash(
            {
                "policy": POLICY,
                "scope": scope,
                "receipt_sha256": receipt_sha256,
                "decision": asdict(result),
            }
        ),
    )
