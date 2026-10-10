"""FX2 local raster reads require a pinned CPU OCR runtime and original pixels."""

import pytest


def test_missing_cpu_reader_is_unresolved_without_launch(monkeypatch):
    from proofops.adapters.local import local_raster_reader as reader

    monkeypatch.setattr(reader.shutil, "which", lambda *a: None)
    monkeypatch.setattr(reader.subprocess, "run", lambda *a, **k: pytest.fail("unavailable"))
    assert reader.runtime_policy()["status"] == "unavailable"
    assert reader.LocalRasterReader(b"unused").read(None, None)["status"] == "unresolved"


def test_changed_language_bytes_are_not_an_approved_runtime(tmp_path, monkeypatch):
    from proofops.adapters.local import local_raster_reader as reader

    executable = tmp_path / "tesseract"
    executable.write_bytes(b"test")
    monkeypatch.setattr(reader.shutil, "which", lambda *a: str(executable))
    monkeypatch.setattr(reader, "TESSDATA", tmp_path)
    (tmp_path / "kor.traineddata").write_bytes(b"changed")
    (tmp_path / "eng.traineddata").write_bytes(b"changed")
    assert reader.runtime_policy()["status"] == "unavailable"


def test_invalid_original_and_region_cannot_launch_ocr(monkeypatch):
    from proofops.adapters.local import local_raster_reader as reader

    monkeypatch.setattr(reader, "runtime_policy", lambda: {"status": "ready"})
    monkeypatch.setattr(reader.subprocess, "run", lambda *a, **k: pytest.fail("invalid source"))
    for box in [(0, 0, float("nan"), 30), (0, 0, 30, 30)]:
        result = reader.LocalRasterReader(b"invalid PDF").read(
            type("Page", (), {"page_number": 1})(), box
        )
        assert result["status"] == "unresolved"
