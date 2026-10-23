"""Stable extraction source selection; routing never admits evidence."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any, cast

from proofops.application.claims import ClaimScope
from proofops.application.ingest.graph_fusion import CanonicalBlock, CanonicalDocumentGraph
from proofops.application.rb1_input_isolation import InputIsolation

from proofops_worker import extract_runner as runtime


def _is_text_candidate(
    kind: str,
    text: str,
    *,
    extraction_table_rows: bool = False,
    extraction_k3: bool = False,
    extraction_qt1: bool = False,
    graph: CanonicalDocumentGraph | None = None,
    source_id: str | None = None,
    cells: Sequence[dict[str, Any]] | None = None,
    rb1: InputIsolation | None = None,
) -> bool:
    if rb1 is not None and rb1.active:
        try:
            # Validate before I26's legacy routing fallback can consume the error.
            # This replaces, rather than repeats, QT1 selection for the RB1 pin.
            if extraction_qt1 and kind == "table" and graph is not None:
                from proofops.application.ingest.qt1_tables import candidates_for

                table = next((b for b in graph.blocks if b.source_id == source_id), None)
                if table is not None and candidates_for(table, graph):
                    return True
            return runtime._is_text_candidate(
                kind,
                text,
                extraction_table_rows=extraction_table_rows,
                extraction_k3=extraction_k3,
                extraction_qt1=False,
                graph=graph,
                source_id=source_id,
                cells=cells,
            )
        except ValueError as error:
            if not rb1.capture(cast(str, source_id), error):
                raise
            return False
    if extraction_qt1 and kind == "table" and graph is not None:
        from proofops.application.ingest.qt1_tables import candidates_for

        table = next((b for b in graph.blocks if b.source_id == source_id), None)
        if table is not None:
            try:
                if candidates_for(table, graph):
                    return True
            except ValueError as error:
                from proofops.application.input_failures import TABLE_ERRORS

                if str(error) not in TABLE_ERRORS:
                    raise
                # Routing is not source admission. Let the extractor's pinned
                # table-failure policy retain this source as unknown; it still
                # rejects a missing grid before any paid model dispatch.
                return True
    if extraction_k3 and extraction_table_rows and kind == "table" and graph is not None:
        from proofops.application.ingest.w9_tables import cell_entries, graph_cells, observations

        table = next((b for b in graph.blocks if b.source_id == source_id), None)
        if table is not None and table.kind == kind and table.normalized_text == text:
            owned = graph_cells(table, graph) if cells is None else cells
            if observations(text, cells=owned) or cell_entries(
                text, owned, source_id=cast(str, source_id)
            ):
                return True
    # ponytail: length is a routing heuristic, not a claim/absence classifier.
    if extraction_table_rows and kind in ("table", "table_row", "table_cell", "figure"):
        from proofops.application.ingest.table_row_candidates import row_candidates

        return bool(row_candidates(text, kind=kind))
    return kind == "paragraph" or (kind == "heading" and len(text.strip()) >= 60)


def paragraph_priority(
    block: CanonicalBlock,
) -> tuple[bool, bool, int, bool, tuple[float, ...], str]:
    """Stable prose/page ordering for bounded extraction and raster recovery."""
    # ponytail: routing heuristic only; no claim or absence classification.
    return (
        not block.normalized_text.rstrip().endswith((".", "!", "?")),
        len(block.normalized_text.strip()) < 60,
        block.page_num,
        block.bbox is not None,
        tuple(block.bbox or ()),
        block.normalized_text,
    )


def select_batch_paragraph_sources(
    graph: CanonicalDocumentGraph,
    scope: ClaimScope,
    max_calls: int,
    *,
    completed: Collection[str] = frozenset(),
    extraction_table_rows: bool = False,
    extraction_k3: bool = False,
    extraction_qt1: bool = False,
    rb1: InputIsolation | None = None,
) -> set[str]:
    """Next bounded window of eligible prose sources, skipping completed ones.

    The ordering is exactly ``paragraph_priority``; continuation excludes sources
    a previous batch already model-processed. ``completed`` carries
    exact source identifiers, so a source is never processed twice and a source
    that was merely deferred stays eligible.
    """
    if type(max_calls) is not int or not 1 <= max_calls <= runtime.MAX_EXTRACTION_BATCH_CALLS:
        raise ValueError("EXTRACTION_INPUT_INVALID")
    from proofops.application.ingest.source_continuations import continuations

    fragments = {p.source_id for parts in continuations(graph).values() for p in parts}
    eligible = (
        block
        for block in graph.blocks
        if (scope.mode != "declared_subset" or block.page_num in scope.selected_pages)
        and block.quality in ("verified", "unverified")
        and block.winner is not None
        and runtime._is_text_candidate(
            block.kind,
            block.normalized_text,
            extraction_table_rows=extraction_table_rows,
            extraction_k3=extraction_k3,
            extraction_qt1=extraction_qt1,
            graph=graph,
            source_id=block.source_id,
            rb1=rb1,
        )
        and block.normalized_text.strip()
        and block.source_id not in completed
        and block.source_id not in fragments
    )
    ordered = sorted(eligible, key=runtime.paragraph_priority)
    return {block.source_id for block in ordered[:max_calls]}


def select_stable_paragraph_sources(
    graph: CanonicalDocumentGraph,
    scope: ClaimScope,
    max_calls: int,
    *,
    extraction_table_rows: bool = False,
    extraction_k3: bool = False,
    extraction_qt1: bool = False,
    rb1: InputIsolation | None = None,
) -> set[str]:
    """Prioritize prose within a bounded preview; retain short candidates after it."""
    return runtime.select_batch_paragraph_sources(
        graph,
        scope,
        max_calls,
        extraction_table_rows=extraction_table_rows,
        extraction_k3=extraction_k3,
        extraction_qt1=extraction_qt1,
        rb1=rb1,
    )
