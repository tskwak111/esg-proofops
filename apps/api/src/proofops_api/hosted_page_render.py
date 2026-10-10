"""Fixed-DPI PDFium previews in the existing bounded process sandbox."""

from __future__ import annotations

import json
import math
import os
import struct
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

MAX_PNG_BYTES = 16 * 1024 * 1024
DPI = 144
MAX_DIMENSION = 2000
MAX_PIXELS = 4_000_000
TIMEOUT_SECONDS = 15
MEMORY_BYTES = 512 * 1024 * 1024


def render(source: Path, page: int, geometry, root: Path) -> tuple[bytes, dict]:
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure

    from proofops_api.hosted_store import HostedError

    profile = SimpleNamespace(
        timeout_seconds=TIMEOUT_SECONDS, memory_bytes=MEMORY_BYTES, max_output_bytes=MAX_PNG_BYTES
    )
    with TemporaryDirectory(prefix=".hosted-preview-", dir=root) as temporary:
        work = Path(temporary)
        # Caller holds a private verified snapshot; child accesses no shared payload.
        os.link(source, work / "source.pdf")
        (work / "request.json").write_text(json.dumps(dict(page=page, geometry=asdict(geometry))))
        try:
            OpenDataLoaderParser._execute(
                [sys.executable, "-I", str(Path(__file__).resolve()), str(work)],
                work,
                {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                profile,
            )
            png = (work / "output.png").read_bytes()
            metadata = json.loads((work / "result.json").read_bytes())
            width, height = struct.unpack(">II", png[16:24])
            if (
                len(png) > MAX_PNG_BYTES
                or not png.startswith(b"\x89PNG\r\n\x1a\n")
                or not 0 < width <= MAX_DIMENSION
                or not 0 < height <= MAX_DIMENSION
                or width * height > MAX_PIXELS
                or (width, height) != (metadata["width_px"], metadata["height_px"])
            ):
                raise ValueError("invalid output")
            return png, metadata
        except (OSError, ValueError, KeyError, struct.error, ParseFailure):
            raise HostedError("SOURCE_RENDER_UNAVAILABLE", 422) from None


def _child(work: Path) -> None:
    import resource

    import pypdfium2 as pdfium

    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PNG_BYTES, MAX_PNG_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    request = json.loads((work / "request.json").read_bytes())
    with pdfium.PdfDocument(work / "source.pdf") as document:
        page = document.get_page(request["page"] - 1)
        try:
            width, height = page.get_size()
            crop = list(page.get_bbox())
            rotation = page.get_rotation() % 360
            expected = request["geometry"]
            if rotation != expected["rotation"] or not all(
                math.isclose(a, b, abs_tol=0.0001, rel_tol=0)
                for a, b in zip(
                    [width, height, *crop],
                    [expected["width_pt"], expected["height_pt"], *expected["crop_box"]],
                    strict=True,
                )
            ):
                raise ValueError("pinned geometry mismatch")
            scale = DPI / 72
            if (
                math.ceil(width * scale) > MAX_DIMENSION
                or math.ceil(height * scale) > MAX_DIMENSION
                or math.ceil(width * scale) * math.ceil(height * scale) > MAX_PIXELS
            ):
                raise ValueError("page exceeds fixed DPI bounds")
            bitmap = page.render(
                scale=scale, may_draw_forms=False, draw_annots=False, limit_image_cache=True
            )
            try:
                image = bitmap.to_pil()
                try:
                    image.save(work / "output.png", format="PNG")
                    metadata = dict(
                        width_px=image.width,
                        height_px=image.height,
                        dpi=DPI,
                        width_pt=width,
                        height_pt=height,
                        rotation=rotation,
                        crop_box=crop,
                    )
                    (work / "result.json").write_text(json.dumps(metadata))
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()


if __name__ == "__main__":
    _child(Path(sys.argv[1]))
