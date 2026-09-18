import pytest

from evaluation.report_sections import build_map


def test_section_scopes_keep_full_data_appendix_and_uncertainty():
    anchors = [
        dict(page=2, title="Environment", path=["Environment"]),
        dict(page=5, title="Social", path=["Social"]),
        dict(page=7, title="ESG DATA", path=["ESG DATA"]),
        dict(page=8, title="Social", path=["ESG DATA", "Social"]),
        dict(page=9, title="Appendix", path=["Appendix"]),
    ]
    result = build_map(10, anchors)
    assert result["claim_candidate_pages"] == [2, 3, 4]
    assert result["evidence_candidate_pages"] == [2, 3, 4, 7, 8, 9, 10]
    assert result["unknown_pages"] == [1]
    assert result["other_candidate_pages"] == [5, 6]
    assert result["status"] == "candidate_only"
    assert build_map(3, [])["unknown_pages"] == [1, 2, 3]
    conflict = build_map(
        3,
        [
            dict(page=2, title="Environment", path=["Environment"]),
            dict(page=2, title="Social", path=["Social"]),
        ],
    )
    assert conflict["claim_candidate_pages"] == []
    assert conflict["conflict_pages"] == [2, 3]


def test_alternative_chapter_titles_and_real_pdf_destinations(tmp_path):
    from hashlib import sha256

    from pypdf import PdfWriter

    from evaluation.report_sections import inspect

    pdf = tmp_path / "report.pdf"
    writer = PdfWriter()
    for _ in range(6):
        writer.add_blank_page(600, 800)
    for title, page in [("Planet", 1), ("People", 3), ("Facts & Figures", 4), ("Appendix", 5)]:
        writer.add_named_destination(title, page)
    writer.write(pdf)
    result = inspect(pdf)
    assert result["claim_candidate_pages"] == [2, 3]
    assert result["evidence_candidate_pages"] == [2, 3, 5, 6]
    assert result["source_sha256"] == sha256(pdf.read_bytes()).hexdigest()
    assert result["unknown_pages"] == [1]

    writer.add_named_destination("Unfamiliar chapter", 2)
    writer.write(pdf)
    result = inspect(pdf)
    assert result["claim_candidate_pages"] == [2]
    assert 3 in result["unknown_pages"]


@pytest.mark.parametrize("layout", ["plain", "multicolumn", "rotated_marker"])
def test_small_toc_link_text_resolves_opaque_destinations(tmp_path, layout):
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )

    from evaluation.report_sections import inspect

    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(600, 800)
    page = writer.pages[0]
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
    marker = (
        b"BT /F1 12 Tf 0 1 -1 0 30 750 Tm (CONTENTS) Tj ET"
        if layout == "rotated_marker"
        else b"BT /F1 12 Tf 30 750 Td (CONTENTS) Tj ET"
    )
    if layout == "multicolumn":
        marker = marker.replace(b"12 Tf", b"22 Tf")
        marker += b" BT /F1 12 Tf 250 750 Td (Other column) Tj ET"
    stream.set_data(
        marker + b" BT /F1 12 Tf 30 720 Td (Environment) Tj "
        b"0 -30 Td (Social) Tj 0 -30 Td (Appendix) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    annotations = ArrayObject()
    for index, y in enumerate((720, 690, 660), 1):
        name = f"report.indd:opaque:{index}"
        writer.add_named_destination(name, index)
        annotations.append(
            writer._add_object(
                DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Annot"),
                        NameObject("/Subtype"): NameObject("/Link"),
                        NameObject("/Dest"): TextStringObject(name),
                        NameObject("/Rect"): ArrayObject(
                            [FloatObject(v) for v in (28, y - 2, 130, y + 15)]
                        ),
                    }
                )
            )
        )
    page[NameObject("/Annots")] = writer._add_object(annotations)
    pdf = tmp_path / "small-toc.pdf"
    writer.write(pdf)
    result = inspect(pdf)
    assert result["method"] == "toc_links"
    assert result["claim_candidate_pages"] == [2]
    assert result["evidence_candidate_pages"] == [2, 4]
    anchor = result["sections"][1]["anchors"][0]
    assert anchor["toc_page"] == 1 and anchor["title"] == "Environment"

    annotations[0].get_object()[NameObject("/Dest")] = ArrayObject(
        [writer.pages[1].indirect_reference, NameObject("/Fit")]
    )
    writer.write(pdf)
    assert inspect(pdf)["claim_candidate_pages"] == [2]

    # An evidence-only TOC still contributes; absence of an E entry is not evidence absence.
    page[NameObject("/Annots")] = ArrayObject([annotations[-1]])
    writer.write(pdf)
    evidence_only = inspect(pdf)
    assert evidence_only["evidence_candidate_pages"] == [4]
    assert evidence_only["claim_candidate_pages"] == []
    annotations[-1].get_object()[NameObject("/A")] = DictionaryObject(
        {
            NameObject("/S"): NameObject("/URI"),
            NameObject("/URI"): TextStringObject("https://example.invalid/report.pdf"),
        }
    )
    writer.write(pdf)
    assert inspect(pdf)["evidence_candidate_pages"] == []


def test_english_topic_and_glossary_routing():
    from evaluation.report_sections import role

    assert role(["Climate Action"]) == "e_narrative"
    assert role(["Glossary"]) == "appendix"


def test_data_sheet_titles_are_evidence_containers():
    from evaluation.report_sections import role

    assert role(["ESG Fact Sheet"]) == "esg_data"
    assert role(["지속가능경영 Data"]) == "esg_data"


@pytest.mark.parametrize("early_data", [False, True])
def test_ghg_energy_topic_routing_and_scope(tmp_path, early_data):
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )

    from evaluation.report_sections import inspect, role

    assert role(["온실가스 및 에너지 관리"]) == "e_narrative"
    assert role(["ESG DATA", "환경"]) == "esg_data"
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(600, 800)
    writer.add_named_destination("Environment", 4)
    writer.add_named_destination("Appendix", 6)
    if early_data:
        writer.add_named_destination("ESG DATA", 1)
        writer.add_named_destination("Overview", 2)
    page = writer.pages[0]
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
        b"BT /F1 12 Tf 30 750 Td (CONTENTS) Tj ET "
        b"BT /F1 12 Tf 30 720 Td (Topic 3. GHG) Tj "
        b"0 -30 Td (ESG DATA) Tj 0 -30 Td (Environment) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    annotations = ArrayObject()
    # GHG narrative p4 is after the early data interval p2 and before E chapter p5.
    ghg_page = 4 if early_data else 2
    for number, target_page in enumerate((ghg_page, 9, 10)):
        name = f"report.indd:section:{number}"
        writer.add_named_destination(name, target_page - 1)
        annotations.append(
            writer._add_object(
                DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Annot"),
                        NameObject("/Subtype"): NameObject("/Link"),
                        NameObject("/Dest"): TextStringObject(name),
                        NameObject("/Rect"): ArrayObject(
                            [
                                FloatObject(v)
                                for v in (28, 718 - number * 30, 130, 735 - number * 30)
                            ]
                        ),
                    }
                )
            )
        )
    page[NameObject("/Annots")] = writer._add_object(annotations)
    pdf = tmp_path / "scattered.pdf"
    writer.write(pdf)
    result = inspect(pdf)
    assert result["method"] == "toc_links"
    assert ghg_page in result["claim_candidate_pages"] and 5 in result["claim_candidate_pages"]
    assert 10 not in result["claim_candidate_pages"]
    assert {7, 9, 10} <= set(result["evidence_candidate_pages"])
    if early_data:
        assert 2 not in result["claim_candidate_pages"] and 2 in result["evidence_candidate_pages"]


@pytest.mark.parametrize("title", ["자원순환36", "폐기물 관리", "Circular economy", "Recycling"])
def test_circularity_boundary_stays_environmental_but_data_child_stays_evidence(title):
    anchors = [
        dict(page=1, path=["Environment"]),
        dict(page=2, path=[title]),
        dict(page=4, path=["Social"]),
        dict(page=5, path=["ESG DATA", title]),
    ]
    result = build_map(6, anchors)
    assert result["claim_candidate_pages"] == [1, 2, 3]
    assert result["evidence_candidate_pages"] == [1, 2, 3, 5, 6]
    assert build_map(2, [dict(page=1, path=["Sustainable growth"])])["unknown_pages"] == [1, 2]


def test_unclassified_large_heading_does_not_override_explicit_toc_role():
    anchors = [
        dict(
            page=2,
            title="Green in Action",
            path=["Green in Action"],
            method="large_heading_fallback",
        ),
        dict(page=2, title="탄소중립", path=["탄소중립"], method="toc_links"),
    ]
    mapped = build_map(4, anchors)
    assert mapped["claim_candidate_pages"] == [2, 3, 4]
    assert mapped["sections"][1]["anchors"] == anchors
    # Explicit opposed meanings remain a conflict; fallback-only unknown stays unknown.
    anchors[0]["path"] = ["Social"]
    assert build_map(4, anchors)["conflict_pages"] == [2, 3, 4]
    anchors[0]["path"] = ["Environmental Social"]
    assert build_map(4, anchors)["conflict_pages"] == [2, 3, 4]
    anchors[0]["path"] = ["Green in Action"]
    assert build_map(4, anchors[:1])["unknown_pages"] == [1, 2, 3, 4]
