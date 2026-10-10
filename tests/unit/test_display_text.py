import pytest
from proofops.application.ingest.display_text import display_alignment, locate_display


def test_map_round_trip_and_exact_unique_selection():
    mapping = display_alignment("환 경 전담 부서", [1])
    assert mapping.text == "환경 전담 부서"
    assert locate_display("환경", mapping) == (0, 3, "환 경")
    assert mapping.selected_span(0, 3) == (0, 2)
    for bad in ["環境", "환경を", "사업장"]:
        with pytest.raises(ValueError):
            locate_display(bad, mapping)
    with pytest.raises(ValueError):
        locate_display("환경", display_alignment("환 경 환경", [1]))


@pytest.mark.parametrize(
    "raw",
    [
        "20 30년",
        "2025 년",
        "10 t CO2e",
        "k Wh",
        "- 10",
        "환\n경",
        "제곱 미터",
        "리 터",
        "킬로 와트",
        "킬 로 그 램",
        "밀 리 리 터",
        "메 가 와 트 시",
        "헥 타 르",
        "환 - 경",
    ],
)
def test_protected_boundaries(raw):
    for i, char in enumerate(raw):
        if char.isspace():
            with pytest.raises(ValueError):
                display_alignment(raw, [i])


def test_no_unproven_space_removed():
    assert display_alignment("네 이버 환 경", []).text == "네 이버 환 경"


def test_each_retained_character_maps_both_directions():
    mapping = display_alignment("네 이버 환 경", [1, 6])
    for i, char in enumerate(mapping.text):
        start, end = mapping.raw_span(i, i + 1)
        assert mapping.raw[start:end] == char
        assert mapping.selected_span(start, end) == (i, i + 1)
    assert locate_display("경", mapping) == (7, 8, "경")
