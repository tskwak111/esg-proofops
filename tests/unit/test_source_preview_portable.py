"""Actual isolated preview rendering and bounded, credential-free launch."""

import sys
from io import BytesIO

import pytest
from proofops.adapters.parsing.source_preview import (
    SourcePreviewFailure,
    _preview_environment,
    render_page_preview,
)
from proofops.domain.documents import PageGeometry
from pypdf import PdfWriter


@pytest.mark.parametrize("appearance", [False, True])
def test_actual_isolated_preview(appearance):
    writer = PdfWriter()
    writer.add_blank_page(width=240, height=120)
    source = BytesIO()
    writer.write(source)
    png, width, height = render_page_preview(
        source.getvalue(),
        1,
        PageGeometry(240, 120, 0, (0, 0, 240, 120)),
        include_annotations_and_forms=appearance,
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (width, height) == (240, 120)


def test_environment_and_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "must-not-leak")
    env = _preview_environment(tmp_path)
    assert "UPSTAGE_API_KEY" not in env
    if sys.platform == "win32":
        assert env["SystemRoot"]
        assert env["TMP"] == env["TEMP"] == str(tmp_path)
    else:
        assert env == {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}

    def fail(command, work, env, profile):
        assert command[1] == "-I"
        assert profile.timeout_seconds == 15
        assert profile.memory_bytes == 512 * 1024 * 1024
        assert profile.max_output_bytes == 16 * 1024 * 1024
        raise OSError("private child detail")

    monkeypatch.setattr(
        "proofops.adapters.parsing.source_preview.OpenDataLoaderParser._execute", fail
    )
    with pytest.raises(SourcePreviewFailure, match="^SOURCE_PREVIEW_FAILED$"):
        render_page_preview(b"invalid", 1, PageGeometry(10, 10, 0, (0, 0, 10, 10)))
