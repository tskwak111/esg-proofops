"""Candidate admission is separate from native verification and evidence credit."""

import json
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parents[1] / "fixtures/w9/cr2-tables.json").read_text())


def entries(key):
    from proofops.application.ingest.j8_cells import cell_entries

    c = CASES[key]
    return cell_entries(c["text"], c["cells"], source_id="source")


def test_kpi_cell_actions_recovered_without_duplicate_completion():
    quotes = [e["text"] for e in entries("T12")]
    assert "데이터센터 재생에너지 확보 기반 마련" in quotes
    assert "재활용품 회수 보상 거점 정보 제공 전국 확대" in quotes
    assert any("6MW 태양광 PPA 개시" in q for q in quotes)
    assert any("1MW 태양광 PPA 추가 개시" in q for q in quotes)
    recycling = [q for q in quotes if "네이버 플레이스 연동" in q]
    assert len(recycling) == 1 and recycling[0].endswith("완료")
    assert not any(q in {"경영진 ESG KPI", "달성", "달성 현황"} for q in quotes)


def test_cell_introductions_are_context_but_named_implemented_systems_are_claims():
    quotes = [e["text"] for e in entries("T13")]
    assert "스노우 멜팅 시스템 운영" not in quotes
    assert "NAMU1) 자체 개발 공조 시스템 적용" in quotes
    assert "AMU3) 및 NAMU 개발·적용" in quotes
    assert sum("태양광:" in q for q in quotes) == 5
    assert sum("PUE(" in q for q in quotes) == 2  # different owning cells
    assert any("서버 폐열" in q for q in quotes)


def test_dated_application_headers_are_literal_assertions_only_in_effect_matrix():
    quotes = [e["text"] for e in entries("T01")]
    assert sum("년 적용" in q for q in quotes) == 5
    assert sum("절감" in q or "향상" in q for q in quotes) == 5
    assert not any("기존" == q or "전력 손실 발생" in q for q in quotes)


def test_offsets_parent_context_and_explicit_ownership_are_exact():
    for key in ("T01", "T12", "T13"):
        for e in entries(key):
            assert CASES[key]["text"][e["char_start"] : e["char_end"]] == e["text"]
            assert "\t" not in e["text"]
            owner = next(
                c for c in CASES[key]["cells"] if (c["row"], c["column"]) == (e["row"], e["column"])
            )
            assert e["text"] in owner["text"]
            assert e["cell_source_id"] == owner["source_id"]
            assert e["binding_status"] == "undetermined"
            for p in e["parent_context"]:
                assert CASES[key]["text"][p["char_start"] : p["char_end"]] == p["text"]


def test_year_values_and_footnote_headers_never_become_generic_cell_claims():
    from proofops.application.ingest.j8_cells import cell_entries, observations

    text = "온실가스\t단위\t2022\t2023\t2024\nScope 1¹\ttCO2eq\t10\t12\t15"
    cells = [
        dict(row=r, column=c, text=t, row_span=1, column_span=1)
        for r, line in enumerate(text.split("\n"))
        for c, t in enumerate(line.split("\t"))
    ]
    assert cell_entries(text, cells, source_id="source") == []
    rows = observations(text, cells=cells)
    assert len(rows) == 1 and rows[0]["value"] == "15" and rows[0]["year"] == "2024"
    assert [c["year"] for c in rows[0]["comparisons"]] == ["2022", "2023"]
    assert observations(text.replace("\t15", "\t15¹"), cells=None) == []


@pytest.mark.parametrize("change", ["overlap", "negative", "span", "duplicate", "text"])
def test_invalid_grid_is_rejected_before_candidates(change):
    from proofops.application.ingest.j8_cells import cell_entries

    c = json.loads(json.dumps(CASES["T12"]))
    if change == "overlap":
        c["cells"][0]["column_span"] = 2
    elif change == "negative":
        c["cells"][0]["row"] = -1
    elif change == "span":
        c["cells"][0]["row_span"] = 0
    elif change == "duplicate":
        c["cells"].append(c["cells"][0])
    else:
        c["cells"][0]["text"] = "different"
    with pytest.raises(ValueError, match="GRID"):
        cell_entries(c["text"], c["cells"], source_id="source")


def test_blank_row_labels_are_never_forward_filled():
    from proofops.application.ingest.j8_cells import cell_entries

    text = "환경 사업\t상태\n태양광 설비\t• 설비 운영 완료\n\t• 계획 수립 및 추진"
    cells = [
        dict(row=r, column=c, text=t, row_span=1, column_span=1)
        for r, line in enumerate(text.split("\n"))
        for c, t in enumerate(line.split("\t"))
    ]
    assert not any("계획 수립" in e["text"] for e in cell_entries(text, cells, source_id="s"))


def test_completion_in_another_facility_never_suppresses_a_distinct_claim():
    from proofops.application.ingest.j8_cells import cell_entries

    text = "구분\t사업장 A\t사업장 B\n현황\t태양광 발전 설비 운영\t태양광 발전 설비 운영 완료"
    cells = [
        dict(row=r, column=c, text=t, row_span=1, column_span=1)
        for r, line in enumerate(text.split("\n"))
        for c, t in enumerate(line.split("\t"))
    ]
    assert len(cell_entries(text, cells, source_id="s")) == 2
