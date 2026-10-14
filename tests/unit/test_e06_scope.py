"""E06 bounded discovery, role recovery and evidence caps; no admission."""

from copy import deepcopy

import pytest

from evaluation.report_scope import build_plan, validate_selection
from evaluation.report_sections import build_map


def fixture(count=40):
    study = build_map(
        count,
        [
            dict(page=1, title="Environment", path=["Environment"], method="outline"),
            dict(page=min(15, count), title="Appendix", path=["Appendix"], method="outline"),
        ],
    )
    study.update(
        source_path="original.pdf",
        source_sha256="a" * 64,
        page_count=count,
        method="outline",
        issues=[],
    )
    texts = {
        p: "Climate carbon emissions energy. " * 12 + f"We reduce emissions 40% by 2030. Page {p}"
        for p in range(1, 15)
    }
    headings = {p: ["Climate Action"] for p in texts}
    return study, texts, headings


def test_summary_and_missing_topic_recovered_without_discarding_claims():
    from evaluation.e06_scope import build_scope

    study, texts, headings = fixture()
    # Introduction is a routing hint, not a prohibition on summary claims.
    study["sections"][0]["role"] = "other"
    texts[1] = (
        "2025 Progress\n" + "We recycle waste and implement renewable energy 100% by 2030. " * 8
    )
    headings[1] = ["2025 Progress"]
    for section in study["sections"][1:]:
        section["role"] = "e_narrative"
    plan = build_scope(study, texts, headings=headings)
    assert 1 in plan["selected_claim_pages"]
    assert plan["source_quality"] == "unverified"
    assert plan["declared_subset"] is True
    assert validate_selection(plan, "a" * 64, 40)["claim_pages"] == plan["selected_claim_pages"]


def test_spare_slot_restores_strong_missing_topic_and_numeral_free_governance():
    from evaluation.e06_scope import build_scope

    study, texts, headings = fixture()
    texts[14] = (
        "Waste recycling water. " * 8
        + "Waste recycling reached 40% and will reach 100% by 2030. " * 6
    )
    headings[14] = ["Waste performance"]
    texts[13] = (
        "Climate governance. " * 8
        + "Our carbon committee implements and supervises the climate roadmap. " * 8
    )
    headings[13] = ["Climate governance"]
    plan = build_scope(study, texts, headings=headings)
    assert 14 in plan["selected_claim_pages"]
    assert 13 in plan["selected_claim_pages"]
    assert len(plan["selected_claim_pages"]) <= 10


def test_s18_preserves_claims_and_whole_assurance_bundle_or_restores_cap():
    from evaluation.e06_scope import compact_plan

    study, texts, headings = fixture()
    for p in range(15, 36):
        texts[p] = (
            "Independent Assurance Statement\n" + "carbon emissions environment. " * 10
            if p >= 28
            else "Environmental data\n" + "energy emissions water waste. " * 10
        )
    base = build_plan(study, texts, page_headings=None)
    before = deepcopy(base)
    # Bundle plus direct support cannot fit; never retain a partial bundle.
    small = compact_plan(
        base,
        texts,
        profile="S18",
        required_pages=[15, 16, 17],
        assurance_bundles=[list(range(28, 36))],
    )
    assert base == before
    assert small["selected_claim_pages"] == base["selected_claim_pages"]
    assert small["reduction"]["status"] == "rejected_restored_cap"
    assert set(range(28, 36)) <= set(small["selected_evidence_pages"])
    assert small["assurance_status"] == "undetermined"
    assert small["reduction"]["missing_required_pages"]
    assert validate_selection(small, "a" * 64, 40)["pages"] == small["selected_evidence_pages"]


def test_short_scope_is_unchanged_and_s14_excluded_claims_are_explicit():
    from evaluation.e06_scope import compact_plan

    study, texts, _ = fixture(14)
    base = build_plan(study, texts, max_environment_pages=10)
    short = compact_plan(base, texts, profile="S18")
    assert short["selected_evidence_pages"] == base["selected_evidence_pages"]
    assert short["reduction"]["status"] == "unchanged_short_scope"
    light = compact_plan(base, texts, profile="S14")
    assert len(light["selected_claim_pages"]) <= 8
    assert light["reduction"]["adoption"] == "not_adopted"
    assert light["reduction"]["excluded_baseline_claim_pages"]


def test_discovery_is_bounded_incomplete_source_bound_and_never_verified():
    from evaluation.scope_discovery_ocr import discover

    calls = []

    def reader(page):
        calls.append(page)
        return {
            "status": "read",
            "text": "Environment\n" + "carbon climate energy renewable. " * 10,
            "physical_page": page,
            "source_sha256": "a" * 64,
            "image_sha256": "b" * 64,
            "reader_policy": {"engine": "test"},
        }

    result = discover(240, [], reader, source_sha256="a" * 64, max_pages=12)
    assert calls == list(range(1, 7)) + list(range(235, 241))
    assert result["scope_incomplete"] is True
    assert len(result["unsearched_pages"]) == 228
    assert all(r["source_verified"] is False for r in result["records"])
    assert all(r["purpose"] == "discovery_only" for r in result["records"])


def test_native_report_never_calls_ocr_and_foreign_receipt_is_unresolved():
    from evaluation.scope_discovery_ocr import discover

    def invalid(page):
        return {
            "status": "read",
            "text": "environment. " * 50,
            "physical_page": page,
            "source_sha256": "c" * 64,
        }

    result = discover(2, [1, 2], lambda p: pytest.fail("extra OCR"), source_sha256="a" * 64)
    assert result["attempted_pages"] == []
    bad = discover(2, [], invalid, source_sha256="a" * 64)
    assert bad["texts"] == {}
    assert bad["unresolved_pages"] == [1, 2]


def test_new_policy_tamper_and_discovery_unknowns_are_rejected():
    from evaluation.e06_scope import build_scope

    study, texts, headings = fixture()
    plan = build_scope(study, texts, headings=headings)
    plan["pages"][0]["snippet"] = "fabricated"
    with pytest.raises(ValueError, match="immutable"):
        validate_selection(plan, "a" * 64, 40)


def test_hosted_ocr_routes_without_upgrading_period_or_native_quality(tmp_path):
    import json
    from hashlib import sha256

    from pypdf import PdfWriter

    from evaluation.hosted_scope_plan import inspect_streaming

    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(600, 800)
    pdf = tmp_path / "scan.pdf"
    writer.write(pdf)
    digest = sha256(pdf.read_bytes()).hexdigest()

    def read(page):
        return dict(
            status="read",
            text="Climate Environment\n"
            + "We reduce carbon emissions 40% by 2030 and implement renewable energy. " * 8,
            physical_page=page,
            source_sha256=digest,
            image_sha256="b" * 64,
            reader_policy={"engine": "test"},
        )

    plan = inspect_streaming(pdf, scope_profile="E06", discovery_reader=read)
    assert plan["selected_claim_pages"] == [1, 2]
    assert plan["native_unreadable_pages"] == [1, 2]
    assert plan["source_quality"] == "unverified"
    assert plan["reporting_period_detection"]["candidates"] == []
    assert validate_selection(plan, digest, 2)["pages"] == [1, 2]
    old = inspect_streaming(pdf)
    assert old["status"] == "failed"
    assert old["version"] == "W4-v2"
    assert "discovery" not in old
    # New plan alteration is rejected by the existing frozen hash gate.
    changed = json.loads(json.dumps(plan))
    changed["discovery"]["cost_usd"] = "1"
    with pytest.raises(ValueError, match="immutable"):
        validate_selection(changed, digest, 2)


def test_front_back_middle_and_source_mutation_remain_bounded(tmp_path):
    from hashlib import sha256

    from pypdf import PdfWriter

    from evaluation.hosted_scope_plan import inspect_streaming
    from evaluation.scope_discovery_ocr import discover

    calls = []

    def read(page):
        calls.append(page)
        return dict(
            status="read",
            text="Climate environment " * 20,
            physical_page=page,
            source_sha256="a" * 64,
            image_sha256="b" * 64,
            reader_policy={"engine": "test"},
        )

    result = discover(20, [], read, source_sha256="a" * 64, max_pages=14)
    assert calls == list(range(1, 7)) + list(range(15, 21)) + [7, 8]
    assert result["unsearched_pages"] == [9, 10, 11, 12, 13, 14]
    writer = PdfWriter()
    writer.add_blank_page(600, 800)
    pdf = tmp_path / "scan.pdf"
    writer.write(pdf)
    digest = sha256(pdf.read_bytes()).hexdigest()

    def mutate(page):
        pdf.write_bytes(pdf.read_bytes() + b"\n")
        return dict(
            status="read",
            text="Climate environment " * 20,
            physical_page=page,
            source_sha256=digest,
            image_sha256="b" * 64,
            reader_policy={"engine": "test"},
        )

    with pytest.raises(ValueError, match="source changed"):
        inspect_streaming(pdf, scope_profile="E06", discovery_reader=mutate)


def test_native_scope_with_blank_cover_skips_ocr(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    from evaluation.hosted_scope_plan import inspect_streaming

    writer = PdfWriter()
    writer.add_blank_page(600, 800)
    page = writer.add_blank_page(600, 800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        (
            "BT /F1 24 Tf 30 750 Td (Climate Environment) Tj /F1 10 Tf 0 -30 Td ("
            + "carbon climate emissions energy renewable. " * 12
            + ") Tj ET"
        ).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_outline_item("Environment", 1)
    pdf = tmp_path / "native.pdf"
    writer.write(pdf)
    calls = []

    def ocr(page):
        calls.append(page)
        raise AssertionError("extra OCR")

    plan = inspect_streaming(pdf, scope_profile="E06", discovery_reader=ocr)
    assert plan["selected_claim_pages"] == [2]
    assert plan["native_unreadable_pages"] == [1]
    assert calls == []
    assert "discovery" not in plan


def test_discovery_assurance_is_evidence_only(tmp_path):
    from hashlib import sha256

    from pypdf import PdfWriter

    from evaluation.hosted_scope_plan import inspect_streaming

    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(600, 800)
    pdf = tmp_path / "scan.pdf"
    writer.write(pdf)
    digest = sha256(pdf.read_bytes()).hexdigest()

    def read(page):
        title = "Climate Environment" if page == 1 else "Independent Assurance Statement"
        return dict(
            status="read",
            text=title
            + "\n"
            + ("We reduce carbon emissions and implement renewable energy 40% by 2030. " * 8),
            physical_page=page,
            source_sha256=digest,
            image_sha256="b" * 64,
            reader_policy={"engine": "test"},
        )

    plan = inspect_streaming(pdf, scope_profile="E06", discovery_reader=read)
    assert plan["selected_claim_pages"] == [1]
    assert plan["selected_evidence_pages"] == [1, 2]
    assert plan["pages"][1]["category"] == "assurance"
    assert plan["assurance_status"] == "undetermined"


def test_s14_edit_cannot_exceed_claim_cap_and_bundle_edits_remain_incomplete():
    from evaluation.e06_scope import compact_plan

    study, texts, _ = fixture()
    for page in (30, 31):
        texts[page] = "Independent Assurance Statement\n" + "carbon emissions environment. " * 20
    base = build_plan(study, texts, max_environment_pages=10)
    small = compact_plan(base, texts, profile="S14", assurance_bundles=[[30, 31]])
    small["selected_claim_pages"] = base["selected_claim_pages"][:9]
    small["selected_evidence_pages"] = sorted(
        set(small["selected_evidence_pages"]) | set(small["selected_claim_pages"])
    )
    with pytest.raises(ValueError, match="cap"):
        validate_selection(small, "a" * 64, 40)
    safe = compact_plan(base, texts, profile="S18", assurance_bundles=[[30, 31]])
    safe["selected_evidence_pages"] = [p for p in safe["selected_evidence_pages"] if p != 31]
    selected = validate_selection(safe, "a" * 64, 40)
    assert selected["evidence_bundle_incomplete"] is True
    assert selected["missing_bundle_pages"] == [31]
    assert selected["assurance_status"] == "undetermined"


def test_w5_ranking_survives_e06_recovery_with_a_distinct_replay_policy():
    from evaluation.e06_scope import (
        POLICY_SHA256,
        W5_SCOPE_POLICY_SHA256,
        W5_SCOPE_VERSION,
        build_scope,
    )
    from evaluation.report_scope import SUPPORT_VERSION

    study, texts, headings = fixture()
    texts[14] = (
        "Climate emissions energy performance. " * 8
        + "Environmental emissions decreased 4,753 tCO2eq. Limited Assurance was completed."
    )
    base = build_plan(study, texts, page_headings=headings, ranking_policy=SUPPORT_VERSION)
    combined = build_scope(study, texts, headings=headings, ranking_policy=SUPPORT_VERSION)
    old = build_scope(study, texts, headings=headings)
    assert set(base["selected_claim_pages"]) <= set(combined["selected_claim_pages"])
    assert combined["pages"][13]["claim_signals"]["same_page_quantified_assurance"] == 1
    assert combined["version"] == W5_SCOPE_VERSION
    assert combined["policy_sha256"] == W5_SCOPE_POLICY_SHA256 != POLICY_SHA256
    assert old["policy_sha256"] == POLICY_SHA256
    assert (
        validate_selection(combined, "a" * 64, 40)["claim_pages"]
        == combined["selected_claim_pages"]
    )
    assert len(combined["selected_claim_pages"]) <= 10
    assert len(combined["selected_evidence_pages"]) <= 30
    assert combined["source_quality"] == "unverified"
