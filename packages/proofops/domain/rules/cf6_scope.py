"""DEC-127 scoped non-observation; historical DEC-85 rules stay immutable."""

from dataclasses import asdict, replace

from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.analysis_scope import ScopeDecision
from proofops.domain.rules.engine import _evaluate

POLICY = dict(
    profile="cf6_dec127_scope_rules_v1",
    absence="unknown_after_three_completed_tagging_replicas_is_absent_in_selected_scope",
    coverage="system_non_observation_not_exhaustive_document_search",
    conflict="held",
    rule_gap="held",
)


def evaluate_scope(tags, context, pack, *, scope, policy_sha256, receipt_sha256):
    if (
        scope.get("tenant_id") != tags.tenant_id
        or scope.get("document_version_id") != tags.document_version_id
        or not scope.get("run_id")
        or not scope.get("selected_pages")
        or scope.get("rule_policy_sha256") != canonical_hash(POLICY)
        or any(f.state == "conflict" for f in tags.facts)
    ):
        raise DomainValidationError("CF6_SCOPE_NOT_CONFIRMABLE")
    decision = _evaluate(tags, context, pack, analysis_scope=True)
    if decision.decision_status != "decided":
        return decision
    result = ScopeDecision(
        **asdict(decision),
        confirmation_basis="cf6_dec127_system_scope",
        confirmation_display="확정",
        confirmation_scope=scope | dict(tagging_receipt_sha256=receipt_sha256),
        confirmation_policy_sha256=policy_sha256,
    )
    return replace(
        result, semantic_hash=canonical_hash(dict(policy=POLICY, decision=asdict(result)))
    )
