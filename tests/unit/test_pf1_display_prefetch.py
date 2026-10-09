"""Opt-in CPU prefetch must preserve catalog reads and fail closed."""

from concurrent.futures import ThreadPoolExecutor
from threading import RLock

import pytest
from proofops.adapters.local import glyph_display_text as display


def catalog():
    result = object.__new__(display.GlyphDisplayCatalog)
    result.source = b"pdf"
    result._pages = {2: ([], {}, set(), None)}
    result._lock = RLock()
    return result


def test_prefetch_is_opt_in_and_deduplicates(monkeypatch):
    result = catalog()
    called = []
    monkeypatch.setattr(
        display, "_read_display_page", lambda source, page: called.append(page) or page
    )
    result.prefetch_pages([2, 3, 3, 4])
    assert called == [] and set(result._pages) == {2}
    monkeypatch.setattr(display, "ProcessPoolExecutor", lambda **kwargs: ThreadPoolExecutor(2))
    result.prefetch_pages([2, 3, 3, 4], max_workers=2)
    assert sorted(called) == [3, 4]
    assert result._pages == {2: ([], {}, set(), None), 3: 3, 4: 4}


@pytest.mark.parametrize("workers", [0, 5, True, "2"])
def test_invalid_workers_rejected(workers):
    with pytest.raises(ValueError, match="DISPLAY_PREFETCH_WORKERS_INVALID"):
        catalog().prefetch_pages([3], max_workers=workers)


def test_failed_prefetch_never_invents_a_page(monkeypatch):
    result = catalog()
    monkeypatch.setattr(display, "ProcessPoolExecutor", lambda **kwargs: ThreadPoolExecutor(2))

    def fail(source, page):
        raise ValueError("unreadable")

    monkeypatch.setattr(display, "_read_display_page", fail)
    with pytest.raises(ValueError, match="unreadable"):
        result.prefetch_pages([3], max_workers=2)
    assert set(result._pages) == {2}


def test_bound_extractor_opt_in_validates_packets_before_prefetch(tmp_path, monkeypatch):
    from dataclasses import asdict

    from proofops_agent.upstage_extraction import GraphBoundExtractor, UpstageClaimExtractor

    from tests.integration.test_upstage_extraction import (
        FakeProbe,
        _extraction_context_graph,
        packet,
    )

    graph, sid = _extraction_context_graph(text="환경 관리를 시행한다.", with_neighbors=True)
    extractor = UpstageClaimExtractor(FakeProbe(), tmp_path, extraction_context=True)
    bound = GraphBoundExtractor(extractor, graph, display_prefetch_workers=4)
    pages = []
    bound._display_catalog = type(
        "Catalog", (), {"prefetch_pages": lambda self, p, **k: pages.extend(p)}
    )()
    data = packet("환경 관리를 시행한다.")
    data.update(source_sha256=graph.source_sha256, extraction_profile=asdict(extractor.profile))
    data["untrusted_document_data"]["source_id"] = sid
    bound.prefetch([data])
    assert pages == [graph.blocks[0].page_num]
    pages.clear()
    data["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="EXTRACTION_CONTEXT_IDENTITY_INVALID"):
        bound.prefetch([data])
    assert pages == []


def test_worker_flag_is_default_off_and_bounded(tmp_path, monkeypatch):
    from proofops_agent.upstage_extraction import UpstageClaimExtractor
    from proofops_worker.extract_runner import _live_extractor

    from tests.integration.test_upstage_extraction import FakeProbe, _extraction_context_graph

    graph, _ = _extraction_context_graph()
    extractor = UpstageClaimExtractor(FakeProbe(), tmp_path, extraction_context=True)
    monkeypatch.delenv("PROOFOPS_DISPLAY_PREFETCH_WORKERS", raising=False)
    assert _live_extractor(extractor, graph)._display_prefetch_workers == 1
    monkeypatch.setenv("PROOFOPS_DISPLAY_PREFETCH_WORKERS", "4")
    assert _live_extractor(extractor, graph)._display_prefetch_workers == 4
    monkeypatch.setenv("PROOFOPS_DISPLAY_PREFETCH_WORKERS", "8")
    with pytest.raises(ValueError, match="DISPLAY_PREFETCH_WORKERS_INVALID"):
        _live_extractor(extractor, graph)
