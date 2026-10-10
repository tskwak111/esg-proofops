"""Offline scope proposals: bounded cost, explicit uncertainty, no evidence admission."""

from copy import deepcopy

import pytest

from evaluation.report_scope import build_plan, validate_selection
from evaluation.report_sections import build_map

ENV = "Climate action. Carbon emissions and renewable energy. Water recycling. "


def study(count=60):
    value = build_map(
        count,
        [
            dict(page=3, path=["CEO Message"], title="CEO Message", method="outline"),
            dict(page=5, path=["Environment"], title="Environment", method="outline"),
            dict(page=30, path=["Social"], title="Social", method="outline"),
            dict(page=35, path=["ESG DATA"], title="ESG DATA", method="outline"),
            dict(page=45, path=["Appendix"], title="Appendix", method="outline"),
        ],
    )
    value.update(
        source_sha256="a" * 64,
        source_path="/report.pdf",
        page_count=count,
        map_sha256="b" * 64,
        issues=[],
        method="pdf_navigation",
    )
    return value


def texts():
    values = {p: "Our company profile and business. " * 20 for p in range(1, 61)}
    values[3] = "CEO Message\n" + ENV * 5
    values.update({p: ENV * (p % 5 + 4) for p in range(5, 30)})
    values[29] = "General social and governance overview. " * 15
    values[40] = "Environmental data\n" + ENV * 7
    values[50] = "GRI Content Index\n" + ENV * 8
    values[55] = "Independent Assurance Statement\n" + ENV * 8
    return values


def test_caps_density_rank_and_evidence_containers():
    source = study()
    frozen = deepcopy(source)
    plan = build_plan(source, texts(), max_environment_pages=8, max_evidence_pages=30)
    assert source == frozen
    assert plan["status"] == "candidate_only"
    assert plan["ceo_candidate_pages"] == [3]
    assert len(plan["selected_claim_pages"]) == 9  # 8 environmental + one CEO
    assert len(plan["selected_evidence_pages"]) == 30
    assert set(plan["selected_claim_pages"]) <= set(plan["selected_evidence_pages"])
    assert {40, 50, 55} <= set(plan["evidence_only_pages"])
    assert not set(range(35, 61)) & set(plan["selected_claim_pages"])
    assert 29 not in plan["selected_claim_pages"]  # overextended low-density interval
    assert plan["excluded_claim_candidate_pages"]
    assert plan["unknown_pages"] == frozen["unknown_pages"]
    assert all(p["snippet"] in texts()[p["page"]] for p in plan["pages"] if p["snippet"])
    assert plan["declared_subset"] is True


def test_ten_claim_hard_cap_even_when_environment_limit_is_ten():
    values = texts()
    values[4] = "대표이사 인사말\n" + ENV * 5
    plan = build_plan(study(), values, max_environment_pages=10)
    assert plan["ceo_candidate_pages"] == [3, 4]
    assert len(plan["selected_claim_pages"]) == 10
    assert {3, 4} <= set(plan["selected_claim_pages"])


def test_conflict_unreadable_and_toc_are_never_automatic_claims():
    source = study()
    source["conflict_pages"] = [8]
    source["claim_candidate_pages"].remove(8)
    values = texts()
    values[2] = "Contents\nCEO Message 3\nEnvironment 5\n" + ENV * 10
    values[7] = ""
    plan = build_plan(source, values)
    assert not {2, 7, 8} & set(plan["selected_claim_pages"])
    assert 7 in plan["unreadable_pages"]
    assert plan["conflict_pages"] == [8]


def test_no_readable_scope_fails_without_whole_report_fallback():
    source = study()
    plan = build_plan(source, {p: "" for p in range(1, 61)})
    assert plan["status"] == "failed"
    assert "NO_READABLE_ENVIRONMENTAL_NARRATIVE" in plan["failure_reasons"]
    assert plan["selected_claim_pages"] == plan["selected_evidence_pages"] == []
    assert plan["suggested_front_pages"] == [1, 2, 3]


def test_heading_density_fallback_keeps_original_unknowns_and_front_ceo_bound():
    source = study()
    source.update(
        claim_candidate_pages=[],
        evidence_candidate_pages=[],
        sections=[],
        unknown_pages=list(range(1, 61)),
    )
    values = {p: "Company governance and employees. " * 15 for p in range(1, 61)}
    values[12] = "Climate strategy\n" + ENV * 10
    values[22] = "CEO Message\n" + ENV * 10
    plan = build_plan(source, values)
    assert plan["selected_claim_pages"] == [12]
    assert plan["ceo_candidate_pages"] == []
    assert plan["unknown_pages"] == list(range(1, 61))
    assert plan["pages"][11]["classification_method"] == "native_density_fallback"


def test_repeated_ceo_navigation_is_not_a_message():
    source = study()
    source["sections"] = []
    values = texts()
    for p in range(1, 21):
        values[p] = "CEO Message\n" + values[p]
    plan = build_plan(source, values)
    assert plan["ceo_candidate_pages"] == []


def test_prominent_physical_ceo_title_survives_toc_and_navigation_repetition():
    source = study()
    source["sections"] = []
    values = texts()
    values[2] = "CONTENTS\nCEO Message\n" + ENV * 5
    values[3] = ENV * 30 + "\nCEO Message"
    values[4] = "CEO Message\n" + ENV * 5
    headings = {2: ["CONTENTS"], 3: ["CEO Message"], 4: []}
    plan = build_plan(source, values, page_headings=headings)
    assert plan["ceo_candidate_pages"] == [3]
    assert "CEO Message" in plan["pages"][2]["snippet"]


def test_policy_book_and_data_subheadings_remain_evidence_only():
    source = study()
    values = texts()
    values[46] = "Policy Book"
    values[47] = "Environmental Policy\n" + ENV * 10
    # A text heading under a known appendix must never create a claim interval.
    source["sections"] = source["sections"][:-1]
    source["unknown_pages"] += list(range(45, 61))
    plan = build_plan(
        source, values, page_headings={46: ["Policy Book"], 47: ["Environmental Policy"]}
    )
    assert 47 in plan["evidence_only_pages"]
    assert 47 not in plan["selected_claim_pages"]


def test_front_intro_ceo_hierarchy_is_resolved_for_scope_without_erasing_conflict():
    source = study()
    source["conflict_pages"] = [3]
    source["sections"][1]["role"] = "conflict"
    source["sections"][1]["anchors"].append(
        dict(page=3, title="Introduction", path=["Introduction"], method="toc_links")
    )
    plan = build_plan(source, texts(), page_headings={3: ["CEO Message"]})
    assert 3 in plan["selected_claim_pages"]
    assert plan["conflict_pages"] == [3]
    assert plan["scope_boundary_resolved_pages"] == [3]


def test_density_fallback_requires_main_environmental_heading_not_body_subheading():
    source = study()
    source["sections"] = []
    values = texts()
    plan = build_plan(
        source,
        values,
        page_headings={6: ["Company History", "Climate actions"]},
        page_primary_headings={6: ["Company History"]},
    )
    assert 6 not in plan["claim_candidate_pages"]


def test_two_page_ceo_continuation_uses_physical_title_and_same_boundary_anchors():
    source = study()
    source["conflict_pages"] = [3, 4]
    section = source["sections"][1]
    section["role"] = "conflict"
    section["anchors"].append(dict(page=3, title="Introduction", path=["Introduction"]))
    values = texts()
    values[4] = "CEO Message\n" + ENV * 10
    plan = build_plan(source, values, page_headings={3: ["CEO Message"], 4: ["CEO Message"]})
    assert plan["ceo_candidate_pages"] == [3, 4]
    assert plan["conflict_pages"] == [3, 4]


@pytest.mark.parametrize("k,m", [(0, 30), (11, 30), (True, 30), (8, 9), (8, 501)])
def test_invalid_limits_refused(k, m):
    with pytest.raises(ValueError):
        build_plan(study(), texts(), max_environment_pages=k, max_evidence_pages=m)


def test_manual_selection_is_source_bound_and_cannot_extract_appendix_claims():
    plan = build_plan(study(), texts())
    edited = deepcopy(plan)
    edited["selected_claim_pages"] = [3, 6]
    edited["selected_evidence_pages"] = [3, 6, 40, 55]
    applied = validate_selection(edited, "a" * 64, 60)
    assert applied["pages"] == [3, 6, 40, 55]
    assert applied["claim_pages"] == [3, 6]
    assert applied["selection_sha256"] != plan["plan_sha256"]
    with pytest.raises(ValueError, match="source"):
        validate_selection(edited, "c" * 64, 60)
    edited["selected_claim_pages"] = [40]
    with pytest.raises(ValueError, match="evidence-only"):
        validate_selection(edited, "a" * 64, 60)


def test_manual_selection_cannot_exceed_two_ceo_pages():
    values = texts()
    values[4] = "CEO Message\n" + ENV * 10
    values[5] = "CEO Message\n" + ENV * 10
    plan = build_plan(
        study(), values, page_headings={3: ["CEO Message"], 4: ["CEO Message"], 5: ["CEO Message"]}
    )
    plan["selected_claim_pages"] = [3, 4, 5, 6]
    plan["selected_evidence_pages"] = [3, 4, 5, 6, 55]
    with pytest.raises(ValueError, match="CEO"):
        validate_selection(plan, "a" * 64, 60)


def test_manual_selection_cap_page_range_and_uncertainty_guard():
    plan = build_plan(study(), texts())
    for claim_pages, evidence_pages in [
        ([3] * 2, [3]),
        ([61], [61]),
        ([3], [6]),
        (list(range(5, 16)), list(range(5, 16))),
        ([1], [1]),
    ]:
        edited = deepcopy(plan)
        edited.update(selected_claim_pages=claim_pages, selected_evidence_pages=evidence_pages)
        with pytest.raises(ValueError):
            validate_selection(edited, "a" * 64, 60)


def test_inspect_native_titles_end_to_end_and_legacy_policy_hash(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    from evaluation.report_scope import inspect
    from evaluation.report_sections import POLICY_HASH

    assert POLICY_HASH == "d757a32350d49e0bf3edd88184a0d66431aa3cdd6b887c2e709c1c92e94f405e"
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for number in range(1, 13):
        page = writer.add_blank_page(600, 800)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        heading = (
            "CEO Message" if number == 2 else ("Appendix" if number == 12 else "Climate Action")
        )
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 24 Tf 30 750 Td ({heading}) Tj /F1 10 Tf 0 -30 Td ({ENV*10}) Tj ET".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_outline_item("CEO Message", 1)
    writer.add_outline_item("Environment", 2)
    writer.add_outline_item("Appendix", 11)
    pdf = tmp_path / "native.pdf"
    writer.write(pdf)
    plan = inspect(pdf)
    assert plan["ceo_candidate_pages"] == [2]
    assert len(plan["selected_claim_pages"]) == 9
    assert 12 in plan["evidence_only_pages"]
    assert plan["parser_versions"]["pypdf"]
    assert plan["live_model"] == "not_run"
