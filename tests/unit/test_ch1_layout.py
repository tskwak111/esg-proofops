from copy import deepcopy

import pytest
from proofops.application.ingest.ch1_layout import propose


def word(i, text, x, y, width=40):
    return dict(id=i, text=text, bbox=[x, y, x + width, y + 12], confidence=0.99)


def layout(kind="bar"):
    return dict(
        id="chart",
        page=1,
        kind=kind,
        alignment="columns",
        bbox=None,
        anchors=[dict(quote="Energy"), dict(quote="GWh"), dict(quote="2024")],
        series=[dict(format="number", label=dict(quote="Energy"), unit=dict(quote="GWh"))],
    )


def words():
    return [
        word(0, "Energy", 10, 10),
        word(1, "GWh", 180, 10),
        word(2, "123", 50, 50),
        word(3, "456", 150, 80),
        word(4, "2023", 50, 120),
        word(5, "2024", 150, 120),
    ]


@pytest.mark.parametrize("kind", ["bar", "line", "image_table"])
def test_coordinate_free_printed_columns_extract_numbers_from_words(kind):
    result = propose(layout(kind), words(), [250, 200])
    assert result["coordinate_origin"] == "OCR-anchor-union"
    assert [(p["value"]["quote"], p["year"]["quote"]) for p in result["observations"]] == [
        ("123", "2023"),
        ("456", "2024"),
    ]
    changed = words()
    changed[2]["text"] = "789"
    assert propose(layout(kind), changed, [250, 200])["observations"][0]["value"]["quote"] == "789"


def test_ambiguous_year_series_and_missing_labels_are_not_inferred():
    data = words() + [word(6, "2022", 50, 100)]
    hint = layout()
    hint["series"].append(dict(format="number", label=dict(quote="Other")))
    result = propose(hint, data, [250, 200])
    assert result["observations"][0]["year"] is None
    assert all(p["series"] is None and p["unit"] is None for p in result["observations"])
    assert (
        len(propose(layout(), [w for w in words() if w["id"] != 2], [250, 200])["observations"])
        == 1
    )
    assert (
        propose(layout(), words() + [word(9, "Energy", 10, 160)], [250, 200])["observations"] == []
    )


def test_ticks_years_series_codes_and_prose_are_not_measurements():
    data = words() + [
        word(6, "0", 25, 90),
        word(7, "ISO14001", 80, 100),
        word(8, "reduced 95%", 80, 30),
    ]
    hint = layout() | dict(axis_word_ids=[6])
    assert len(propose(hint, data, [250, 200])["observations"]) == 2


def test_single_percentage_preserves_inline_unit_and_explicit_year_caption():
    data = [word(0, "ISO", 10, 10), word(1, "2024년", 70, 10), word(2, "73%", 80, 70)]
    hint = dict(
        id="pie",
        page=1,
        kind="pie",
        alignment="single",
        bbox=[0, 0, 200, 150],
        year=dict(quote="2024년"),
        series=[dict(format="percent", label=dict(quote="ISO"))],
    )
    point = propose(hint, data, [200, 150])["observations"][0]
    assert point["value"]["quote"] == "73%"
    assert point["unit"] == dict(quote="73%", word_ids=[2], span=[2, 3])
    assert point["year"]["quote"] == "2024년"


def test_image_table_unique_row_headers_and_page_bounds():
    data = words() + [word(6, "Power", 5, 50), word(7, "Fuel", 5, 80)]
    hint = layout("image_table") | dict(
        bbox=[0, 0, 250, 200], row_labels=[dict(quote="Power"), dict(quote="Fuel")]
    )
    result = propose(hint, data, [250, 200])
    assert [p["series"]["quote"] for p in result["observations"]] == ["Power", "Fuel"]
    for box in [[0, 0, float("nan"), 200], [-1, 0, 250, 200], [0, 0, 251, 200]]:
        bad = deepcopy(hint) | dict(bbox=box)
        with pytest.raises(ValueError, match="CH1_REGION_GEOMETRY_INVALID"):
            propose(bad, data, [250, 200])
