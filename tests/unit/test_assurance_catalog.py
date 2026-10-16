"""E02 shadow catalog: source and scope authority remain separate."""

from dataclasses import replace

import pytest
from proofops.application.assurance import ClaimContext
from proofops.application.evidence.assurance_catalog import (
    build_catalog,
    discover_bundles,
    match_m3_candidate,
)
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_assurance import CLAIM, TENANT, VERSION, extract, inputs


def catalog_case(**changes):
    graph, refs, fields = inputs(**({"covered_metrics": "environmental policy"} | changes))
    count = max(ref.page_num for ref in refs)
    texts = {p: "Preserved opinion continuation" for p in range(1, count + 1)}
    texts[1] = "Independent Assurance Statement\nScope\nISAE 3000"
    texts[count] = "Signed on 2026-06-01"
    discovery = discover_bundles(texts, page_count=count, source_sha256=graph.source_sha256)
    catalog = build_catalog(graph, discovery, tenant_id=TENANT)
    statement = extract(graph, refs, fields)
    claim = ClaimContext(
        TENANT, VERSION, CLAIM, "environmental policy", "2024", ("예시 법인",), ("서울 사업장",)
    )
    return graph, catalog, statement, claim


def test_verified_catalog_and_exact_covered_match_remain_approval_pending():
    graph, catalog, statement, claim = catalog_case()
    result = match_m3_candidate(catalog, graph=graph, claim=claim, statement=statement)
    assert result["scope_match"]["status"] == "covered"
    assert result["state"] == "unknown"
    assert result["candidate_state"] == "present"
    assert result["review_status"] == "needs_review"
    assert result["public_auto_confirmed"] is False
    assert "ASSEMBLY_POLICY_APPROVAL_REQUIRED" in result["reasons"]
    assert result["synthetic"] is True
    assert catalog["verified_span_count"] == len(graph.blocks)
    assert result["receipt_sha256"] == canonical_hash(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"reporting_period": "2023"},
        {"facilities": ("다른 시설",)},
        {"metric": "another activity"},
        {"reporting_period": None},
        {"facilities": ()},
    ],
)
def test_other_period_facility_activity_and_unknown_dimensions_do_not_become_m3(changes):
    graph, catalog, statement, claim = catalog_case()
    result = match_m3_candidate(
        catalog, graph=graph, claim=replace(claim, **changes), statement=statement
    )
    assert result["candidate_state"] == "unknown"
    assert result["state"] == "unknown"
    assert result["public_auto_confirmed"] is False


def test_tenant_document_graph_and_catalog_tampering_are_rejected():
    graph, catalog, statement, claim = catalog_case()
    for changed in [
        replace(graph, source_sha256="0" * 64),
        replace(graph, tenant_id="77777777-7777-4777-8777-777777777777"),
    ]:
        with pytest.raises(ValueError, match="IDENTITY"):
            match_m3_candidate(catalog, graph=changed, claim=claim, statement=statement)
    with pytest.raises(ValueError, match="CATALOG_HASH"):
        match_m3_candidate(
            catalog | {"verified_span_count": 99}, graph=graph, claim=claim, statement=statement
        )
    with pytest.raises(ValueError, match="IDENTITY"):
        match_m3_candidate(
            catalog,
            graph=graph,
            claim=replace(claim, document_version_id=CLAIM),
            statement=statement,
        )


def test_unverified_page_or_missing_exclusion_page_never_gives_present():
    graph, catalog, statement, claim = catalog_case()
    graph = replace(graph, blocks=tuple(replace(b, quality="unverified") for b in graph.blocks))
    count = max(b.page_num for b in graph.blocks)
    texts = {p: "Opinion continuation" for p in range(1, count + 1)}
    texts[1] = "Independent Assurance Statement\nScope\nISAE 3000"
    texts[count] = "Signed on 2026-06-01"
    discovery = discover_bundles(texts, page_count=count, source_sha256=graph.source_sha256)
    catalog = build_catalog(graph, discovery, tenant_id=TENANT)
    statement = extract(graph, statement.source_refs, dict(statement.tagged_fields))
    result = match_m3_candidate(catalog, graph=graph, claim=claim, statement=statement)
    assert catalog["verified_span_count"] == 0
    assert result["candidate_state"] == "unknown"
    assert "CATALOG_SOURCE_UNRESOLVED" in result["reasons"]


def test_provider_or_standard_only_and_explicit_exclusion_do_not_supply_m3():
    for changes in [{"covered_metrics": None}, {"excluded_facilities": "서울 사업장"}]:
        graph, catalog, statement, claim = catalog_case(**changes)
        result = match_m3_candidate(catalog, graph=graph, claim=claim, statement=statement)
        assert result["candidate_state"] == "unknown"
        assert result["state"] == "unknown"  # not_covered is not global absence


def test_editing_values_without_corresponding_extraction_receipt_is_rejected():
    graph, catalog, statement, claim = catalog_case()
    for changed in [
        replace(statement, covered_metrics=()),
        replace(statement, excluded_facilities=claim.facilities),
    ]:
        with pytest.raises(ValueError, match="STATEMENT_REPLAY_MISMATCH"):
            match_m3_candidate(catalog, graph=graph, claim=claim, statement=changed)


def test_missing_final_opinion_page_blocks_the_catalog():
    graph, _, _, _ = catalog_case()
    count = max(b.page_num for b in graph.blocks)
    texts = {p: "Opinion continuation" for p in range(1, count + 1)}
    texts[1] = "Independent Assurance Statement\nScope\nISAE 3000"
    texts[count] = "Signed on 2026-06-01"
    discovery = discover_bundles(texts, page_count=count, source_sha256=graph.source_sha256)
    missing = replace(graph, blocks=tuple(b for b in graph.blocks if b.page_num != count))
    catalog = build_catalog(missing, discovery, tenant_id=TENANT)
    assert catalog["bundles"][0]["status"] == "unresolved"
    assert f"parsed_page_missing:{count}" in catalog["bundles"][0]["unresolved"]


def test_shadow_policy_cannot_be_used_as_a_production_fact_assembly_profile(tmp_path):
    from proofops.application.evidence.assurance_catalog import VERSION
    from proofops.application.tagging.consensus import form_consensus
    from proofops.domain.errors import DomainValidationError

    from tests.acceptance.test_tagging import execute, setup

    case = setup(tmp_path)
    with pytest.raises(DomainValidationError, match="unknown fact assembly profile"):
        form_consensus(
            execute(case),
            packet=case["packet"],
            rulepack=case["rulepack"],
            tenant_id=TENANT,
            tag_revision=1,
            profile=VERSION,
        )
