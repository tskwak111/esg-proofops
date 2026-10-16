import json
from pathlib import Path

import pytest
from proofops.application.ingest.pb1_tables import observations

CASES = json.loads((Path(__file__).parents[1] / "fixtures/w9/cr2-tables.json").read_text())


def test_cr2_recovers_all_31_rows_without_changing_legacy_replay():
    from proofops.application.ingest.w9_tables import observations as w9

    before = after = 0
    for case in CASES.values():
        legacy = observations(case["text"], context=" ".join(case["context"]))
        assert len(legacy) == case["baseline_rows"]
        if case["expected_rows"] is not None:
            rows = w9(case["text"], cells=case["cells"])
            assert len(rows) == case["expected_rows"]
            assert all(case["text"][r["start"] : r["end"]] == r["quote"] for r in rows)
            before += len(legacy)
            after += len(rows)
    assert (before, after) == (52, 83)


def test_financial_table_does_not_borrow_environment_context():
    from proofops.application.ingest.w9_tables import observations as w9

    assert w9(CASES["T15"]["text"], cells=CASES["T15"]["cells"], context="온실가스") == []
    assert w9("지표명\t단위\t2024\n매출액\t원\t15", context="탄소") == []


@pytest.mark.parametrize("unit", ["kg / 백만 원", "대", "톤/년", "tCO2eq/대"])
def test_explicit_whole_cell_units_preserve_denominator(unit):
    from proofops.application.ingest.w9_tables import observations as w9

    text = f"친환경차 배출량\t단위\t2024\n총 합계\t{unit}\t15"
    assert w9(text)[0]["unit"] == unit


def test_metric_paths_preserve_explicit_span_and_limited_subgroup():
    from proofops.application.ingest.w9_tables import observations as w9

    def paths(key):
        c = CASES[key]
        return {r["row"]: r["metric_path"] for r in w9(c["text"], cells=c["cells"])}

    assert "Scope 1" in " / ".join(paths("T02")[3]) and paths("T02")[3][-1] == "국내"
    assert "Scope 2" in " / ".join(paths("T02")[6]) and paths("T02")[6][-1] == "국내"
    assert "Dust" in " / ".join(paths("T07")[2])
    assert "COD" in " / ".join(paths("T08")[2])
    assert "일반 폐기물" in " / ".join(paths("T09")[4])
    assert "지정 폐기물" in " / ".join(paths("T09")[10])
    # An unrelated blank label is never filled from the preceding row.
    rows = w9("온실가스\t구분\t단위\t2024\nScope 1\t국내\ttCO2eq\t15\n\t합계\ttCO2eq\t10")
    assert "Scope 1" not in rows[1]["metric_path"]


@pytest.mark.parametrize("key", ["T12", "T13"])
def test_cell_newlines_never_join_another_column(key):
    from proofops.application.ingest.w9_tables import cell_entries

    c = CASES[key]
    entries = cell_entries(c["text"], c["cells"], source_id="source")
    assert entries
    for entry in entries:
        owners = [
            cell
            for cell in c["cells"]
            if cell["row"] == entry["row"] and cell["column"] == entry["column"]
        ]
        assert len(owners) == 1 and entry["text"] in owners[0]["text"]
        assert "\t" not in entry["text"]
        assert c["text"][entry["char_start"] : entry["char_end"]] == entry["text"]
    if key == "T13":
        selected = next(e for e in entries if "12,932" in e["text"])
        assert "16,673" not in selected["text"]
        assert selected["parent_context"][0]["text"] == "데이터센터 각 춘천"
        assert all(
            p["role"] in {"same_source_column_header", "same_source_cell_label"}
            for p in selected["parent_context"]
        )


def test_chart_generated_numbers_are_never_generic_claims(tmp_path):
    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    class Probe:
        model = "solar-pro3"

        def complete(self, *a, **kw):
            raise AssertionError("paid call forbidden")

    extractor = UpstageClaimExtractor(
        Probe(),
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
    )
    for key in ["T18", "C02"]:
        packet = dict(
            untrusted_document_data=dict(kind="figure", source_id="source", text=CASES[key]["text"])
        )
        assert extractor._row_entries(packet, CASES[key]["text"], []) == []


def test_new_policy_is_pinned_and_old_policy_remains_readable():
    from proofops.application.analysis_profile import V2_POLICY, V2_PRE_W9_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash
    from proofops_agent.upstage_extraction import _profile_with_options

    assert V2_POLICY["table_claims"] == "pb1-w9-v1"
    assert canonical_hash(V2_POLICY) != canonical_hash(V2_PRE_W9_POLICY)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(V2_PRE_W9_POLICY))
        == V2_PRE_W9_POLICY
    )
    assert (
        _profile_with_options(extraction_pb1=True).rule_sha256
        != _profile_with_options(extraction_pb1=True, extraction_w9=True).rule_sha256
    )


def test_explicit_column_span_is_preserved_as_display_context():
    from proofops.application.ingest.w9_tables import observations as w9

    text = "지표명\t단위\t국내\t\n\t\t2023\t2024\nScope 1\ttCO2eq\t10\t15"
    cells = [
        dict(row=r, column=c, text=t, row_span=rs, column_span=cs)
        for r, c, t, rs, cs in [
            (0, 0, "지표명", 2, 1),
            (0, 1, "단위", 2, 1),
            (0, 2, "국내", 1, 2),
            (1, 2, "2023", 1, 1),
            (1, 3, "2024", 1, 1),
            (2, 0, "Scope 1", 1, 1),
            (2, 1, "tCO2eq", 1, 1),
            (2, 2, "10", 1, 1),
            (2, 3, "15", 1, 1),
        ]
    ]
    row = w9(text, cells=cells)[0]
    assert row["column_path"] == ["국내"]
    assert row["metric_path"] == ["Scope 1", "국내"]
    assert row["metric_path_usage"] == "display_only_not_evidence"


@pytest.mark.parametrize("change", ["unit", "value", "year", "header_order"])
def test_w9_native_admission_still_rejects_tampered_units_values_years(change):
    from proofops.adapters.local import upstage_ocr_profile_v10 as native

    from tests.unit.test_pa9_source import FIXTURE, fixture

    batches = json.loads((FIXTURE / "kia.json").read_text())
    quote = "\t국내\t천tCO2eq\t266.0\t244.6\t238.6"
    before, after = {
        "unit": ("천tCO2eq", "kg"),
        "value": ("266.0", "266.9"),
        "year": ("2024", "2025"),
        "header_order": ("2022", "2024"),
    }[change]
    for batch in batches:
        for block in batch["blocks"]:
            block["context"].append("pb1-w9-v1")
            if block["source"]["physical_page"] != 2:
                continue
            text = block["source"]["raw_text"]
            if change == "header_order":
                text = text.replace("2022", "SWAP").replace("2024", "2022").replace("SWAP", "2024")
            else:
                text = text.replace(before, after)
            block["source"].update(raw_text=text, char_end=len(text))
    if change in ("unit", "value"):
        quote = quote.replace(before, after)
    graph, source = fixture("kia", batches)
    table = next(b for b in graph.blocks if b.kind == "table" and quote in b.raw_text)
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    assert (
        native.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )


def test_wrapped_bullet_stays_contiguous_and_context_offsets_are_literal():
    from proofops.application.ingest.w9_tables import cell_entries

    text = (
        "사업장\n재생에너지 사용\n• 2025년 태양광 발전으로\n"
        "232.2 MWh의 전력 공급\n• 2025년 192.7 MWh 발전"
    )
    cells = [
        dict(row=0, column=0, row_span=1, column_span=1, text="사업장"),
        dict(row=1, column=0, row_span=1, column_span=1, text=text.split("\n", 1)[1]),
    ]
    entries = cell_entries(text, cells, source_id="source")
    assert len(entries) == 2
    assert "발전으로\n232.2" in entries[0]["text"]
    for e in entries:
        assert text[e["char_start"] : e["char_end"]] == e["text"]
        for p in e["parent_context"]:
            assert text[p["char_start"] : p["char_end"]] == p["text"]


def test_non_year_native_reader_probe_does_not_reconstruct_wrapped_cells_as_rows():
    from proofops.application.ingest.w9_tables import PROFILE

    for key in ("T12", "T13"):
        assert observations(CASES[key]["text"], context=PROFILE) == []


def test_same_row_label_keeps_kpi_action_without_donating_other_cell_numbers():
    from proofops.application.ingest.w9_tables import cell_entries

    case = CASES["T12"]
    entries = cell_entries(case["text"], case["cells"], source_id="source")
    assert any("PPA, 발전소 투자" in e["text"] for e in entries)
    case = CASES["T13"]
    for e in cell_entries(case["text"], case["cells"], source_id="source"):
        assert not any(p["role"] == "same_source_row_label" for p in e["parent_context"])
