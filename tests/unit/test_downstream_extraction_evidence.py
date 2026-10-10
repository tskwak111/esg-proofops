"""NAVER-shaped source regressions; no transport or report-wide year inference."""

import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor


def test_original_offsets_preserve_distinct_denominators_without_adding_year():
    text = "2024 solar output: 171,873kWh. Renewable share 78% (including night power 65%)."
    quote = "Renewable share 78% (including night power 65%)."
    span = UpstageClaimExtractor._locate(quote, text)
    assert text[span["char_start"] : span["char_end"]] == quote
    assert span["char_start"] == text.index("Renewable")
    assert "2024" not in span["quote"]


@pytest.mark.parametrize(
    "invented",
    [
        "2024 Renewable share 78%.",
        "Renewable share 79%.",
        "Investment KRW 3,400.",
        "Reduced emissions 3,400tCO2e.",
    ],
)
def test_numbers_years_units_and_goal_predicates_must_be_literal(invented):
    text = "Renewable share 78%. Expected emissions reduction 3,400tCO2e."
    with pytest.raises(ValueError, match="absent or ambiguous"):
        UpstageClaimExtractor._locate(invented, text)


def test_context_header_cannot_be_spliced_into_focal_claim():
    focal = "Renewable energy use 20GWh achieved."
    with pytest.raises(ValueError, match="absent or ambiguous"):
        UpstageClaimExtractor._locate("2024 " + focal, focal)
    assert UpstageClaimExtractor._locate(focal, focal)["char_start"] == 0


def test_repeated_value_requires_disambiguating_literal_scope():
    text = "Office 20%. Fleet 20%."
    with pytest.raises(ValueError, match="absent or ambiguous"):
        UpstageClaimExtractor._locate("20%", text)
    assert UpstageClaimExtractor._locate("Fleet 20%.", text)["char_start"] == 12
