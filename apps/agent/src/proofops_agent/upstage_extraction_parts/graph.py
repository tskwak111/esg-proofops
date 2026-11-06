"""Bind one validated document graph and optional source catalogs to extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from proofops.application.claims import ExtractionProfile

from proofops_agent.extraction_parts.contracts import (
    DisplayCatalog,
    DisplayCatalogOption,
    TitleCatalog,
    TitleCatalogOption,
)

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.application.rb1_input_isolation import InputIsolation

    from proofops_agent.upstage_extraction import UpstageClaimExtractor


class GraphBoundExtractor:
    """Thin ClaimExtractorPort adapter binding one graph to a context extractor.

    Discovery loops (``discover_atomic_claims``) call ``extract(packet)`` with
    no room for per-call context, so the runner wraps its context-mode
    extractor with the run's own graph once. Only a context-mode
    ``UpstageClaimExtractor`` can be wrapped — anything else fails closed at
    construction, never silently at call time. Profile and usage surface are
    the inner extractor's own.
    """

    def __init__(
        self,
        inner: UpstageClaimExtractor,
        graph: CanonicalDocumentGraph,
        source: bytes | None = None,
        *,
        display_prefetch_workers: int = 1,
        rb1: InputIsolation | None = None,
    ) -> None:
        if not (
            getattr(inner, "_context", False) or getattr(inner, "_display_text_profile", None)
        ) or not callable(getattr(inner, "extract", None)):
            raise ValueError("UPSTAGE_CONTEXT_EXTRACTOR_REQUIRED")
        if type(display_prefetch_workers) is not int or not 1 <= display_prefetch_workers <= 4:
            raise ValueError("DISPLAY_PREFETCH_WORKERS_INVALID")
        self._display_prefetch_workers = display_prefetch_workers
        self._rb1 = rb1
        self._inner = inner
        self._graph = graph
        self.native_figure_receipt = None
        if getattr(inner, "_qc_native_figures", False):
            if source is None:
                raise ValueError("QC_NATIVE_FIGURE_SOURCE_REQUIRED")
            from proofops.adapters.local.h1_native_title import native_figure_candidates

            self._graph, self.native_figure_receipt = native_figure_candidates(graph, source)
            graph = self._graph
        self._display_catalog: DisplayCatalog | None = None
        self._h1_title_catalog: TitleCatalog | None = None
        if getattr(inner, "_h1", False) and source is not None:
            from proofops.adapters.local.h1_native_title import NativeTitleCatalog

            self._h1_title_catalog = NativeTitleCatalog(graph, source)
        if getattr(inner, "_display_text_profile", None) and source is not None:
            from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog

            self._display_catalog = GlyphDisplayCatalog(graph, source)

    def prefetch(self, packets: list[dict[str, Any]]) -> None:
        if self._display_catalog is None or self._display_prefetch_workers == 1:
            return
        blocks = {b.source_id: b for b in self._graph.blocks}
        selected: set[str] = set()
        for packet in packets:
            # Keep packet and focal identity checks before the optional CPU work.
            self._inner._packet_text(packet)
            self._inner._validate_context_graph(packet, self._graph)
            sid = packet["untrusted_document_data"]["source_id"]
            if self._rb1 is not None and sid in self._rb1.failures:
                continue
            if self._inner._context:
                try:
                    context, _ = self._inner._context_for(packet, self._graph)
                except ValueError as error:
                    if self._rb1 is None or not self._rb1.capture(sid, error):
                        raise
                    continue
                selected.update(b["source_id"] for b in context)
            selected.add(sid)
        pages = {
            blocks[sid].page_num
            for sid in selected
            if blocks[sid].winner is not None
            and blocks[sid].bbox is not None
            and " " in blocks[sid].raw_text
        }
        self._display_catalog.prefetch_pages(pages, max_workers=self._display_prefetch_workers)

    @property
    def graph(self) -> CanonicalDocumentGraph:
        """Use this derived graph for discovery under the explicit QC profile."""
        return self._graph

    @property
    def profile(self) -> ExtractionProfile:  # ClaimExtractorPort: frozen discovery reads this.
        return self._inner.profile

    def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
        from proofops_agent import upstage_extraction as facade

        if self._rb1 is not None and self._rb1.active:
            sid = packet["untrusted_document_data"]["source_id"]
            if sid in self._rb1.failures:
                self._inner._packet_text(packet)
                self._inner._validate_context_graph(packet, self._graph)
                self._rb1.check(sid)
        if getattr(self._inner, "_display_text_profile", None) and self._display_catalog is None:
            raise facade.ExtractionOutputError("DISPLAY_SOURCE_UNAVAILABLE")
        try:
            return self._inner.extract(
                packet,
                context_graph=self._graph,
                **facade.cast(
                    TitleCatalogOption,
                    (
                        {"h1_title_catalog": self._h1_title_catalog}
                        if self._h1_title_catalog is not None
                        else {}
                    ),
                ),
                **facade.cast(
                    DisplayCatalogOption,
                    (
                        {"display_catalog": self._display_catalog}
                        if self._display_catalog is not None
                        else {}
                    ),
                ),
            )
        except ValueError as error:
            if self._rb1 is not None and self._rb1.capture(
                packet["untrusted_document_data"]["source_id"], error
            ):
                self._rb1.check(packet["untrusted_document_data"]["source_id"])
            if (
                getattr(self._inner, "_i5_tables", False)
                and getattr(self._inner, "_j8", False)
                and packet.get("untrusted_document_data", {}).get("kind") == "table"
                and str(error) in {"J8_GRID_MISSING", "J8_GRID_INVALID", "J8_GRID_OVERLAP"}
            ):
                # ClaimDiscovery records a failed source and an unknown exclusion;
                # no empty/non-claim result or invented cell/evidence is admitted.
                raise facade.ExtractionOutputError("TABLE_GRID_UNREADABLE") from None
            raise
