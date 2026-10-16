"""Original-v2 branches on resolved scoped facts, including historical replay."""

from dataclasses import replace
from itertools import product

import pytest
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.cf6_scope import (
    POLICY,
    POLICY_V1,
    evaluate_scope,
    gap_details,
    resolve_exception_facts,
)
from proofops.domain.rules.engine import MAPPINGS

from tests.acceptance.test_rules import SOURCE, fact, inputs, pack


def run(tags, context, *, selected=POLICY, rulepack=None):
    return evaluate_scope(
        tags,
        context,
        rulepack or pack(),
        scope=dict(
            tenant_id=tags.tenant_id,
            document_version_id=tags.document_version_id,
            run_id="test",
            selected_pages=[1],
            rule_policy_sha256=canonical_hash(selected),
        ),
        policy_sha256=canonical_hash(selected),
        receipt_sha256="a" * 64,
    )


@pytest.mark.parametrize(
    "track,bits",
    [
        (track, bits)
        for track, count in [("management", 3), ("performance", 4), ("goal", 6)]
        for bits in product((False, True), repeat=count)
    ],
)
def test_resolved_ladders_match_original_domain(track, bits):
    tags, context = inputs(track)
    resolved = {
        name: fact(name, "present" if bits[i] else "absent_in_scope")
        for i, names in enumerate(list(MAPPINGS[track].values())[: len(bits)])
        for name in names
    }
    tags = replace(tags, facts=tuple(resolved.get(f.name, f) for f in tags.facts))
    if track == "management":
        # A quote establishing willingness is unnecessary for the scoped E0 floor.
        tags = replace(
            tags,
            facts=tuple(
                replace(f, state="unknown") if f.name == "willingness_only" else f
                for f in tags.facts
            ),
        )
        expected = "E0" if not bits[0] else "E1" if not bits[1] else "E3" if bits[2] else "E2"
    elif track == "performance":
        expected = "E0" if not bits[0] else "E1" if not all(bits[:3]) else "E3" if bits[3] else "E2"
    else:
        year, metric, baseline, boundary, progress, plan = bits
        expected = (
            ("E1" if metric and plan else "E0")
            if not year
            else (
                None
                if not metric
                else "E1"
                if not (baseline and boundary)
                else "E3"
                if progress and plan
                else "E2"
            )
        )
    decision = run(tags, context)
    assert decision.evidence_grade == expected
    assert decision.decision_status == ("decided" if expected else "blocked_rule_gap")
    if not expected:
        detail = gap_details(tags, pack(), decision)[0]
        assert detail["gap_id"] == "GAP-007"
        assert detail["facts"]["target_year"] == "present"
        assert detail["facts"]["target_metric"] == "absent_in_scope"


def test_v1_management_replay_retains_original_block_and_hash():
    from proofops.application.analysis_profile import (
        CF6_POLICY,
        policy_for,
        publication_policy_for,
    )

    tags, context = inputs(
        "management",
        named_means_or_concrete_state="absent_in_scope",
        org_boundary="absent_in_scope",
        external_verification="absent_in_scope",
        willingness_only="unknown",
    )
    old = run(tags, context, selected=POLICY_V1)
    assert old.decision_status == "blocked_evidence"
    assert run(tags, context).evidence_grade == "E0"
    old_hash = "3aae437cb6468b3822f90efc19307abb487d114af46c515f1f4a78efb744314b"
    assert canonical_hash(CF6_POLICY) == old_hash
    for select in (policy_for, publication_policy_for):
        assert select("finals-unattended-v2", pinned_hash=old_hash) == CF6_POLICY


def test_unit_missing_is_actual_performance_gap_not_lowest_grade():
    tags, context = inputs(unit_or_qualified_ordinal="absent_in_scope")
    result = run(tags, context)
    assert result.decision_status == "blocked_rule_gap"
    assert result.evidence_grade is None and result.gap_ids == ("GAP-007",)


def test_additional_scoped_absence_is_report_only_but_legacy_gap_003_is_preserved():
    tags, context = inputs(
        "management", concrete_implementation_detail="absent_in_scope", governance_claim="unknown"
    )
    result = run(tags, context)
    assert result.evidence_grade == "E3"
    assert "M4" in result.missing_elements and "M5" in result.unresolved_elements
    assert "M5" not in result.excluded_elements  # no fabricated non-applicability
    legacy = run(tags, context, rulepack=pack(legacy_gap_003=True))
    assert "GAP-003" in legacy.gap_ids and legacy.evidence_grade is None


@pytest.mark.parametrize("kind", ["superlative", "product", "ordinal"])
def test_scoped_absence_reaches_source_exceptions(kind):
    tags, context = inputs("performance" if kind == "ordinal" else "management")
    if kind == "superlative":
        tags = replace(
            tags,
            superlative_quote=SOURCE.quote,
            facts=tuple(f for f in tags.facts if f.name != "external_verification"),
        )
        expected = "E0"
    elif kind == "product":
        tags = replace(tags, product_variant=True)
        expected = "E1"
    else:
        tags = replace(
            tags,
            facts=(
                *tags.facts,
                fact("categorical_ordinal", "unknown"),
                fact("certification_provider", "unknown"),
            ),
        )
        expected = "E0"
    scoped = resolve_exception_facts(tags, claim_source_refs=(SOURCE,))
    assert run(scoped, context).evidence_grade == expected
    assert run(scoped, context, selected=POLICY_V1).decision_status == "blocked_evidence"


def test_superlative_requires_verified_literal_and_preserves_conflict():
    tags, context = inputs("management", external_verification="absent_in_scope")
    tags = replace(tags, superlative_quote="not in the source")
    scoped = resolve_exception_facts(tags, claim_source_refs=(SOURCE,))
    assert run(scoped, context).decision_status == "blocked_evidence"
    tags = replace(tags, facts=(*tags.facts, fact("comparison_basis", "conflict")))
    scoped = resolve_exception_facts(tags, claim_source_refs=(SOURCE,))
    assert next(f for f in scoped.facts if f.name == "comparison_basis").state == "conflict"
    with pytest.raises(ValueError, match="CF6_SCOPE_NOT_CONFIRMABLE"):
        run(scoped, context)


def test_product_present_ratio_and_safe_harbor_keep_exact_gaps():
    tags, context = inputs("management")
    tags = replace(
        tags,
        product_variant=True,
        facts=(*tags.facts, fact("direct_product_material_ratio_or_target")),
    )
    scoped = resolve_exception_facts(tags, claim_source_refs=(SOURCE,))
    decision = run(scoped, context)
    assert "GAP-007" in decision.gap_ids
    assert "boundary interaction" in gap_details(scoped, pack(), decision)[0]["branch"]
    tags = replace(tags, safe_harbor_category="forward_looking")
    decision = run(tags, context)
    assert "GAP-001" in decision.gap_ids
