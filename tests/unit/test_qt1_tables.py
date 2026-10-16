import json
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parents[1] / "fixtures/qt1/r17-tables.json").read_text())


def rows(key):
    from proofops.application.ingest.qt1_tables import inventory

    c = CASES[key]
    return inventory(c["text"], c["cells"], context=c["context"])


def test_merged_units_and_footnote_year_headers_recover_exact_energy_and_region_rows():
    energy = rows("7e673343-fb53-5928-8a55-bdf58e52a2a7")
    assert len(energy) == 17
    biomass = next(r for r in energy if "바이오매스" in r["quote"])
    assert [v["quote"] for v in biomass["values"]] == ["-", "1", "-"]
    assert [v["year"] for v in biomass["values"]] == ["2022", "2023", "2024"]
    assert biomass["unit"]["quote"] == "TJ"
    assert energy[-1]["unit"]["quote"] == "TJ/천억 원"
    regions = rows("b218787d-cdbe-5f52-91f1-93f825f7ef37")
    assert len(regions) == 7
    assert all(r["unit"]["quote"] == "톤" for r in regions)
    assert all(r["values"][1]["year_source"]["quote"] == "2023년7)" for r in regions)


def test_target_actual_axes_never_swap_and_contributions_do_not_invent_years():
    target = rows("329e3926-72d9-5f66-8274-1f75f2251b0a")
    assert len(target) == 5
    assert [
        (v["quote"], v["year"], v["column_headers"][-1]["quote"]) for v in target[0]["values"]
    ] == [("10.0%", "2025", "목표1)"), ("11.5%", "2025", "성과")]
    contributions = rows("468098f5-1dd5-5e48-9672-c38667557f84")
    assert [r["values"][0]["quote"] for r in contributions] == ["3%", "25%", "72%"]
    assert all(v["year"] is None for r in contributions for v in r["values"])


def test_risk_rows_keep_both_scenarios_and_both_years():
    risk = rows("de20bbd7-eb74-5ed4-bd29-ec6bf1b6b358")
    assert len(risk) == 4
    assert [v["year"] for v in risk[0]["values"]] == ["2030", "2030", "2050", "2050"]
    assert [v["column_headers"][-1]["quote"] for v in risk[0]["values"]] == [
        "SSP1-2.6",
        "SSP5-8.5",
        "SSP1-2.6",
        "SSP5-8.5",
    ]


def test_timeline_cells_and_original_source_offsets_are_preserved():
    timeline = rows("979e59fd-01eb-5f30-9768-9541f6160519")
    assert len(timeline) == 3
    assert [r["values"][0]["year"] for r in timeline] == ["2022", "2023", "2024"]
    for key, c in CASES.items():
        for r in rows(key):
            assert c["text"][r["start"] : r["end"]] == r["quote"]
            for cell in r["cells"] + r["headers"] + r["row_headers"]:
                assert c["text"][cell["start"] : cell["end"]] == cell["quote"]
            assert r["binding_status"] == "undetermined"
            assert r["eligible_for_scoring"] is False


def test_reconcile_checks_each_cell_and_does_not_duplicate_partial_rows():
    from proofops.application.ingest.qt1_tables import reconcile

    c = CASES["468098f5-1dd5-5e48-9672-c38667557f84"]
    start = c["text"].index("고효율 설비")
    end = c["text"].index("\t3%", start)
    old = [
        dict(
            char_start=start,
            char_end=end,
            quote=c["text"][start:end],
            kind="claim",
            reason=None,
            topic_ids=["environment"],
        )
    ]
    new, coverage = reconcile(c["text"], rows("468098f5-1dd5-5e48-9672-c38667557f84"), old)
    assert old[0] in new
    assert any(s["quote"] == "3%" for s in new)
    assert all(a["char_end"] <= b["char_start"] for a, b in zip(new, new[1:]))
    again, _ = reconcile(c["text"], rows("468098f5-1dd5-5e48-9672-c38667557f84"), new)
    assert again == new
    assert coverage[0]["status"] == "partial"


def test_no_unit_forward_fill_no_global_year_and_financial_or_navigation_excluded():
    from proofops.application.ingest.qt1_tables import inventory

    def grid(text):
        return [
            dict(row=r, column=c, row_span=1, column_span=1, text=t)
            for r, line in enumerate(text.split("\n"))
            for c, t in enumerate(line.split("\t"))
        ]

    text = "온실가스\t단위\t2024년\nScope 1\ttCO2eq\t100\nScope 2\t\t200"
    result = inventory(text, grid(text), context=["section=2030년 환경 목표"])
    assert result[1]["unit"] is None
    assert result[1]["values"][0]["year"] == "2024"
    for text in [
        "구분\t단위\t2024\n매출액\t원\t100",
        "Material Issue\n기후변화 대응\nGeneral Issue",
    ]:
        assert inventory(text, grid(text), context=["section=환경"]) == []
    c = CASES["7e673343-fb53-5928-8a55-bdf58e52a2a7"]
    with pytest.raises(ValueError, match="GRID"):
        inventory(c["text"], [*c["cells"], c["cells"][0]])


def test_narrative_gaps_remain_candidates_without_automatic_duplicate_claims():
    from proofops.application.ingest.qt1_tables import reconcile

    key = "979e59fd-01eb-5f30-9768-9541f6160519"
    candidates = rows(key)
    result, coverage = reconcile(CASES[key]["text"], candidates, [])
    assert len(candidates) == 3 and result == []
    assert all(c["status"] == "missing" for c in coverage)
    assert all(not c["recovery_eligible"] for c in candidates)
