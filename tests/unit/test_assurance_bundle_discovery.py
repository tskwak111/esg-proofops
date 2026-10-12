"""E02: native discovery routes complete opinions; it never verifies evidence."""

from copy import deepcopy

import pytest
from proofops.application.evidence.assurance_catalog import discover_bundles, select_bundles


def pages():
    return {
        1: "Contents\nIndependent Assurance Statement 4\nGRI Index 3",
        2: "Environment\nA company operates an environmental policy.",
        3: "GRI Index\n3-3 Material topics 2",
        4: "Independent Assurance Statement\nScope\nISAE 3000\n2025 activities of A company",
        5: "Limitations\nThe overseas facility is excluded.",
        6: "Opinion\nSigned on 2026-06-01\nFor and on behalf of independent assurer",
        7: "Independent Assurance Statement\nScope\nISO 14064-3\n2025 GHG inventory",
        8: "Unrelated appendix",
    }


def test_discovers_continuation_and_does_not_admit_navigation_or_unfinished_opinion():
    source = pages()
    frozen = deepcopy(source)
    result = discover_bundles(source, page_count=8, source_sha256="a" * 64)
    assert source == frozen
    assert result["discovery_only"] is True
    assert [b["pages"] for b in result["bundles"]] == [[4, 5, 6], [7, 8]]
    assert result["bundles"][0]["boundary_state"] == "candidate_complete"
    assert result["bundles"][1]["boundary_state"] == "incomplete"
    assert result["bundles"][1]["reasons"] == ["opinion_end_unresolved"]
    assert all(b["source_quality"] == "unverified" for b in result["bundles"])


def test_cap_never_selects_a_partial_bundle_and_claim_pages_stay_fixed():
    discovery = discover_bundles(pages(), page_count=8, source_sha256="a" * 64)
    selected = select_bundles(discovery, claim_pages=[2], union_cap=2)
    assert selected["claim_pages"] == [2]
    assert selected["evidence_only_pages"] == []
    assert selected["missing_bundle_pages"] == [4, 5, 6, 7, 8]
    assert selected["status"] == "evidence_bundle_incomplete"
    smaller = select_bundles(discovery, claim_pages=[2], union_cap=3)
    assert smaller["evidence_only_pages"] == [7, 8]  # entire second bundle, no partial first
    assert smaller["missing_bundle_pages"] == [4, 5, 6]
    selected = select_bundles(discovery, claim_pages=[2], union_cap=6)
    assert selected["evidence_only_pages"] == [4, 5, 6, 7, 8]
    assert selected["status"] == "evidence_bundle_incomplete"  # opinion 2 has no end


def test_unreadable_continuation_is_not_absence_or_complete():
    source = pages() | {5: ""}
    result = discover_bundles(source, page_count=8, source_sha256="a" * 64)
    assert result["bundles"][0]["boundary_state"] == "incomplete"
    assert "native_page_unreadable:5" in result["bundles"][0]["reasons"]


def test_signature_on_first_page_does_not_drop_following_exclusions_or_table():
    source = pages() | {
        4: pages()[4] + "\nSigned on 2026-06-01",
        6: "Exclusions\nAnother facility is not covered.",
    }
    result = discover_bundles(source, page_count=8, source_sha256="a" * 64)
    assert result["bundles"][0]["pages"] == [4, 5, 6]
    source[5] = ""
    result = discover_bundles(source, page_count=8, source_sha256="a" * 64)
    assert result["bundles"][0]["boundary_state"] == "incomplete"


def test_two_opinions_on_one_page_are_separate_and_ambiguous_for_fact_assembly():
    source = pages() | {
        5: "Signed on 2026-06-01\nIndependent Assurance Statement\n"
        "Scope\nISO 14064-3\n2025 GHG inventory",
        6: "Opinion\nSigned on 2026-06-02",
        7: "GRI Content Index",
    }
    result = discover_bundles(source, page_count=8, source_sha256="a" * 64)
    assert [b["pages"] for b in result["bundles"]] == [[4, 5], [5, 6]]
    assert all("shared_boundary_page:5" in b["reasons"] for b in result["bundles"])
    selection = select_bundles(result, claim_pages=[2], union_cap=3)
    assert selection["evidence_only_pages"] == []  # shared physical page is indivisible
    assert selection["missing_bundle_pages"] == [4, 5, 6]


def test_discovery_hash_is_rechecked_before_selection():
    result = discover_bundles(pages(), page_count=8, source_sha256="a" * 64)
    result["bundles"][0]["pages"] = [4]
    with pytest.raises(ValueError, match="DISCOVERY_HASH"):
        select_bundles(result, claim_pages=[2], union_cap=8)


@pytest.mark.parametrize("claim_pages,cap", [([True], 8), ([2, 2], 8), ([9], 8), ([2], True)])
def test_invalid_selection_is_rejected(claim_pages, cap):
    result = discover_bundles(pages(), page_count=8, source_sha256="a" * 64)
    with pytest.raises(ValueError):
        select_bundles(result, claim_pages=claim_pages, union_cap=cap)
