"""Only complete raw OCR reads for the same source/runtime/scope can be reused."""

from types import SimpleNamespace

from proofops.adapters.local.local_raster_reader import LocalRasterReader


def test_same_read_once_scope_and_runtime_misses(monkeypatch):
    from proofops.adapters.local import pa7_raster_cache as cache

    cache.clear()
    calls = []
    monkeypatch.setattr(
        LocalRasterReader,
        "__init__",
        lambda self, source: (
            setattr(self, "source", source),
            setattr(self, "policy", dict(status="ready", runtime="one")),
        )[-1],
    )

    def read(self, page, box, *, padding_px=0):
        calls.append(1)
        return dict(
            status="read",
            text="15 tCO2eq",
            reader_policy=self.policy,
            box=list(box),
            padding_px=padding_px,
        )

    monkeypatch.setattr(LocalRasterReader, "read", read)
    page = SimpleNamespace(page_number=1, width=600, height=400)
    with cache.scope("tenant", "run", {"profile": "v9"}):
        first = cache.ScopedRasterReader(b"original").read(page, (10, 20, 30, 40))
        first["text"] = "mutated"
        second = cache.ScopedRasterReader(b"original").read(page, (10, 20, 30, 40))
        assert second["text"] == "15 tCO2eq"
        assert calls == [1]
        cache.ScopedRasterReader(b"other").read(page, (10, 20, 30, 40))
        cache.ScopedRasterReader(b"original").read(page, (10, 20, 30, 40), padding_px=6)
        reader = cache.ScopedRasterReader(b"original")
        reader.policy["runtime"] = "changed"
        reader.read(page, (10, 20, 30, 40))
    with cache.scope("other-tenant", "run", {"profile": "v9"}):
        cache.ScopedRasterReader(b"original").read(page, (10, 20, 30, 40))
    assert calls == [1] * 5
    cache.clear()


def test_unavailable_reads_not_cached_and_byte_entry_budget(monkeypatch):
    from proofops.adapters.local import pa7_raster_cache as cache

    cache.clear()
    calls = []
    monkeypatch.setattr(
        LocalRasterReader,
        "__init__",
        lambda self, source: (
            setattr(self, "source", source),
            setattr(self, "policy", dict(status="ready")),
        )[-1],
    )

    def fail(*args, **kwargs):
        calls.append(1)
        return dict(status="unresolved", reason="rendered_reader_unavailable")

    monkeypatch.setattr(LocalRasterReader, "read", fail)
    page = SimpleNamespace(page_number=1, width=600, height=400)
    with cache.scope("tenant", "run", {}):
        for _ in range(2):
            cache.ScopedRasterReader(b"original").read(page, (10, 20, 30, 40))
    assert calls == [1, 1]
    assert not cache._reads


def test_successful_read_entry_budget_and_no_cross_run_reuse(monkeypatch):
    from proofops.adapters.local import pa7_raster_cache as cache

    cache.clear()
    monkeypatch.setattr(cache, "_MAX_ENTRIES", 2)
    monkeypatch.setattr(cache, "_MAX_BYTES", 4096)
    monkeypatch.setattr(
        LocalRasterReader,
        "__init__",
        lambda self, source: (
            setattr(self, "source", source),
            setattr(self, "policy", dict(status="ready")),
        )[-1],
    )
    calls = []
    monkeypatch.setattr(
        LocalRasterReader, "read", lambda *a, **k: calls.append(1) or dict(status="read", text="15")
    )
    page = SimpleNamespace(page_number=1, width=600, height=400)
    with cache.scope("tenant", "run", {}):
        for i in range(3):
            cache.ScopedRasterReader(bytes([i])).read(page, (10, 20, 30, 40))
    assert len(cache._reads) == 2
    assert sum(len(v) + 1024 for v in cache._reads.values()) <= 4096
    with cache.scope("tenant", "new-run", {}):
        cache.ScopedRasterReader(bytes([2])).read(page, (10, 20, 30, 40))
    assert calls == [1] * 4
    cache.clear()
