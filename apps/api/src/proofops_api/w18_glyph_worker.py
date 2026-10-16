"""Bounded PDFium character inventory for display only (no source approval)."""

import hashlib
import json
import math
import resource
import sys
from contextlib import closing
from pathlib import Path

MAX_CHARS = 40000
MAX_OUTPUT = 32 * 1024 * 1024


def extract(work):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    request = json.loads((work / "request.json").read_bytes())
    source = Path(request["source"])
    if source.is_symlink() or source.stat().st_size > 157286400:
        raise ValueError("unsafe source")
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != request["sha256"]:
        raise ValueError("source hash mismatch")
    # All page reads use these exact authenticated bytes, even if the path changes.
    (work / "verified.json").write_text(json.dumps({"sha256": request["sha256"]}))
    with pdfium.PdfDocument(content) as document:
        for number in request["pages"]:
            with closing(document[number - 1]) as page, closing(page.get_textpage()) as text:
                if text.count_chars() > MAX_CHARS:
                    continue
                chars = []
                for index in range(text.count_chars()):
                    code = raw.FPDFText_GetUnicode(text, index)
                    char = chr(code)
                    if char.isspace():
                        continue
                    box = list(text.get_charbox(index, loose=False))
                    # Invisible native text is never an exact display location.
                    obj = raw.FPDFText_GetTextObject(text, index)
                    visible = bool(obj) and raw.FPDFTextObj_GetTextRenderMode(obj) in (0, 1, 2)
                    chars.append(
                        [char, index, box if visible and all(map(math.isfinite, box)) else None]
                    )
                result = dict(
                    page=dict(
                        width_pt=page.get_width(),
                        height_pt=page.get_height(),
                        rotation=page.get_rotation() % 360,
                        crop_box=list(page.get_bbox()),
                    ),
                    chars=chars,
                )
                (work / f"page-{number}.json").write_text(json.dumps(result))


if __name__ == "__main__":
    extract(Path(sys.argv[1]))
