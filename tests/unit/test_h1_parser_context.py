"""Wrapped origin grids, bounded local inputs and historical-policy replay."""

from dataclasses import replace

import pytest
from proofops.application.ingest.graph_fusion import CandidateBlock, ParserProfile, fuse_candidates
from proofops.application.tagging.table_sources import table_structural_sources

from tests.acceptance.test_parsing import JAVA, MANIFEST, TENANT, candidate, pdf


def graph(*, new=True, tamper=False):
    text = "온실가스\n배출량\t단위\t2024\nScope 1\ttCO2eq\t15"
    context = ("pb1_table_claims", "pb1-w9-v1") + (("h1-origin-context-v1",) if new else ())
    batch = candidate("upstage", [("table", "table", text, (0, 0, 600, 800), context)])
    table = batch.blocks[0]
    cells = []
    for row, values in enumerate(
        [("온실가스\n배출량", "단위", "2024"), ("Scope 1", "tCO2eq", "15")]
    ):
        for col, value in enumerate(values):
            if tamper and (row, col) == (1, 2):
                value = "16"
            cells.append(
                CandidateBlock(
                    "table_cell",
                    replace(
                        table.source,
                        source_native_id=f"c{row}-{col}",
                        native_bbox=(col * 100, 700 - row * 40, col * 100 + 90, 730 - row * 40),
                        raw_text=value,
                        char_end=len(value),
                    ),
                    table.geometry,
                    context=context,
                    table_native_id="table",
                    row_number=row,
                    column_number=col,
                    row_span=1,
                    column_span=1,
                )
            )
    from proofops.application.ingest.graph_fusion import CandidateEdge

    batch = replace(
        batch,
        blocks=(table, *cells),
        edges=tuple(
            CandidateEdge(c.source.source_native_id, "table", "table_parent") for c in cells
        ),
    )
    return fuse_candidates((batch,), tenant_id=TENANT)


def test_wrapped_grid_uses_its_exact_origin_cells_without_evidence_promotion():
    g = graph()
    table = next(b for b in g.blocks if b.kind == "table")
    start = table.normalized_text.index("Scope 1")
    ref = table.source_ref(
        normalized_char_start=start, normalized_char_end=len(table.normalized_text)
    )
    result = table_structural_sources(g, (ref,), tenant_id=TENANT)
    assert result.resolved
    assert not result.verified and result.context_only
    assert {s.ref.quote for s in result.context_only} == {"Scope 1", "tCO2eq", "2024"}


@pytest.mark.parametrize("new,tamper", [(False, False), (True, True)])
def test_legacy_pin_and_corrupt_origins_still_fail_closed(new, tamper):
    g = graph(new=new, tamper=tamper)
    table = next(b for b in g.blocks if b.kind == "table")
    with pytest.raises(ValueError, match="W9_GRID_TEXT_MISMATCH"):
        table_structural_sources(g, (table.source_ref(),), tenant_id=TENANT)


def test_resource_policy_is_pinned_and_old_parser_config_is_unchanged():
    old = ParserProfile(MANIFEST, java_executable=JAVA)
    assert "local_resource_policy" not in old.config_snapshot()
    new = replace(old, local_resource_policy="selected-pdf-h1-v1")
    assert new.config_hash() != old.config_hash()
    with pytest.raises(ValueError):
        replace(old, local_resource_policy="unknown")


def test_selected_pdf_mapping_preserves_raw_pages_and_artifact_hashes(tmp_path):
    from proofops.adapters.parsing.h1_local_pages import prepare, restore_pages
    from pypdf import PdfReader

    original = pdf(table=True)
    path = tmp_path / "source.pdf"
    path.write_bytes(original)
    selected, page_map = prepare(path, [2], tmp_path)
    assert len(PdfReader(selected).pages) == 1
    assert page_map == [2]
    raw = {
        "number of pages": 1,
        "kids": [{"id": "one", "page number": 1, "kids": [{"id": "nested", "page number": 1}]}],
    }
    mapped = restore_pages(raw, page_map, 2)
    assert mapped["kids"][0]["page number"] == mapped["kids"][0]["kids"][0]["page number"] == 2
    assert raw["kids"][0]["page number"] == 1
    assert mapped["number of pages"] == 2
    with pytest.raises(ValueError):
        restore_pages({"number of pages": 1, "kids": [{"page number": 2}]}, page_map, 2)
    assert path.read_bytes() == original
