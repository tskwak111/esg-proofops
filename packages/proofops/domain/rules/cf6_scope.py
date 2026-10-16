"""DEC-127 scoped non-observation; historical DEC-85 rules stay immutable."""

from dataclasses import asdict, replace

from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.analysis_scope import ScopeDecision
from proofops.domain.rules.engine import ConfirmedFact, _evaluate

POLICY_V1 = dict(
    profile="cf6_dec127_scope_rules_v1",
    absence="unknown_after_three_completed_tagging_replicas_is_absent_in_selected_scope",
    coverage="system_non_observation_not_exhaustive_document_search",
    conflict="held",
    rule_gap="held",
)
POLICY = POLICY_V1 | dict(
    profile="cf6_dec127_scope_rules_v2",
    management_floor="M1_absent_E0_original_4.3_4.4_no_fabricated_willingness",
    source_exceptions="scoped_absence_consumed_by_original_4.4_branches",
    auxiliary_facts="exception_operands_only_non_observed_after_three_completed_replicas",
    additional_elements="pinned_pack_report_only_conditional_triggers_not_invented",
)


def resolve_exception_facts(tags, *, claim_source_refs):
    """After three completed replicas: retain positives/conflicts, close only operands.

    The caller verifies claim refs against the original graph. A superlative
    header needs its literal source, while unobserved comparison/product facts
    receive scoped absence. Applicability triggers are deliberately unchanged.
    """
    facts = {f.name: f for f in tags.facts}
    operands = set()
    if tags.superlative_quote:
        refs = tuple(
            r
            for r in claim_source_refs
            if (
                r.verification_state == "verified"
                and r.document_version_id == tags.document_version_id
                and tags.superlative_quote.strip()
                and tags.superlative_quote in r.quote
            )
        )
        if "has_superlative" not in facts and refs:
            facts["has_superlative"] = ConfirmedFact(
                "has_superlative", "present", refs, tags.tenant_id, True, True
            )
        operands.update(("comparison_basis", "external_verification"))
    if tags.product_variant:
        operands.add("direct_product_material_ratio_or_target")
    if "categorical_ordinal" in facts:
        operands.update(("categorical_ordinal", "certification_provider"))
    for name in sorted(operands):
        if name not in facts or facts[name].state == "unknown":
            facts[name] = ConfirmedFact(name, "absent_in_scope")
    return replace(tags, facts=tuple(facts.values()))


def gap_details(tags, pack, decision):
    """Exact unsupported branch plus operands; no invented fallback grade."""
    if decision.decision_status != "blocked_rule_gap":
        return []
    descriptions = {
        "GAP-001": "original §4.6 safe-harbor category has no E0–E3 mapping",
        "GAP-003": "pinned pack lacks additional_element_policy=report_without_grade_effect",
        "GAP-006": "superlative plus safe-harbor precedence has no grade mapping",
        "GAP-007": (
            "product ratio/target present: generic management boundary interaction undefined"
            if tags.product_variant and tags.track == "management"
            else "product variant outside management is undefined"
            if tags.product_variant
            else f"no {tags.track} ladder branch matches resolved primitive facts"
        ),
    }
    return [
        dict(
            gap_id=gap,
            branch=descriptions.get(gap, "pinned rule gap"),
            track=tags.track,
            safe_harbor_category=tags.safe_harbor_category,
            facts={f.name: f.state for f in tags.facts},
            rubric_branches=pack.file_content(f"rubric/{tags.track}.yaml")["branches"],
        )
        for gap in decision.gap_ids
    ]


def evaluate_scope(tags, context, pack, *, scope, policy_sha256, receipt_sha256):
    selected = next(
        (p for p in (POLICY_V1, POLICY) if canonical_hash(p) == scope.get("rule_policy_sha256")),
        None,
    )
    if (
        scope.get("tenant_id") != tags.tenant_id
        or scope.get("document_version_id") != tags.document_version_id
        or not scope.get("run_id")
        or not scope.get("selected_pages")
        or selected is None
        or any(f.state == "conflict" for f in tags.facts)
    ):
        raise DomainValidationError("CF6_SCOPE_NOT_CONFIRMABLE")
    decision = _evaluate(tags, context, pack, analysis_scope=True, dec127=selected == POLICY)
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
        result, semantic_hash=canonical_hash(dict(policy=selected, decision=asdict(result)))
    )
