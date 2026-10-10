"""Pinned, free CPU OCR of original PDFium pixels; this never approves a source.

SV1/EV1 independently validate literal text, glyphs, rows/columns and annotations.
An absent/changed runtime returns unresolved. No OCR character corrections.
"""

import io
import json
import math
import shutil
import subprocess
from contextlib import closing
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
from PIL import ImageOps
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

LOCK_PATH = Path(__file__).resolve().parents[4] / "contracts/local_raster_reader_lock.json"
LOCK = json.loads(LOCK_PATH.read_bytes())
TESSDATA = Path("/usr/share/tesseract-ocr/5/tessdata")


def interactive_catalog_requires_review(source):
    # pdfminer omits null dictionary values. Inspect original keys too, so a
    # malformed form/OCG/XFA declaration cannot become "no visibility control".
    root = PdfReader(io.BytesIO(source), strict=False).trailer["/Root"]
    if "/OCProperties" in root:
        return True
    if "/AcroForm" not in root:
        return False
    form = root["/AcroForm"]
    return not isinstance(form, DictionaryObject) or any(
        key in form for key in ("/XFA", "/NeedsRendering")
    )


@lru_cache(maxsize=4)
def _identity(executable, executable_stat, data_files):
    # Cache only an executable's actual bytes/version and traineddata hashes,
    # keyed by file identities. Receipt inputs, crop pixels and OCR stay separate.
    output = (
        subprocess.run([executable, "--version"], capture_output=True, check=True, timeout=5)
        .stdout.decode("utf-8", "strict")
        .splitlines()[0]
    )
    if output != "tesseract " + LOCK["tesseract_version"]:
        raise ValueError("LOCAL_OCR_VERSION_MISMATCH")
    hashes = {name: sha256(Path(path).read_bytes()).hexdigest() for name, path, _ in data_files}
    if hashes != LOCK["languages_sha256"]:
        raise ValueError("LOCAL_OCR_LANGUAGE_MISMATCH")
    return dict(
        executable_sha256=sha256(Path(executable).read_bytes()).hexdigest(), languages=hashes
    )


def runtime_policy():
    common = dict(
        profile=LOCK["profile"],
        lock_sha256=sha256(LOCK_PATH.read_bytes()).hexdigest(),
        reader_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        renderer="PDFium",
        renderer_version=version("pypdfium2"),
        pillow_version=version("pillow"),
        dpi=216,
        psm=6,
        oem=1,
        max_pixels=LOCK["max_pixels"],
        timeout_seconds=30,
    )
    executable = shutil.which("tesseract")
    if executable:
        try:
            stat = Path(executable).stat()
            data = tuple(
                (
                    name,
                    str(TESSDATA / (name + ".traineddata")),
                    (TESSDATA / (name + ".traineddata")).stat().st_mtime_ns,
                )
                for name in ("kor", "eng")
            )
            identity = _identity(executable, (stat.st_mtime_ns, stat.st_size), data)
            return dict(common, status="ready", **identity)
        except (OSError, ValueError, subprocess.SubprocessError, UnicodeError):
            pass
    return dict(common, status="unavailable", reason="pinned_cpu_ocr_runtime_unavailable")


class LocalRasterReader:
    def __init__(self, source):
        self.source, self.policy = source, runtime_policy()
        self.cache = {}

    def read(self, page, box, *, padding_px=0):
        if self.policy["status"] != "ready":
            return dict(
                status="unresolved", reason="rendered_reader_unavailable", reader=LOCK["profile"]
            )
        try:
            if (
                not isinstance(self.source, bytes)
                or not 0 < len(self.source) <= 100 * 1024 * 1024
                or type(page.page_number) is not int
                or type(padding_px) is not int
                or padding_px not in (0, 6)
                or len(box) != 4
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in box)
            ):
                raise ValueError("LOCAL_OCR_INPUT_INVALID")
            key = (page.page_number, tuple(box), padding_px)
            if key in self.cache:
                return dict(self.cache[key])
            with pdfium.PdfDocument(self.source) as doc:
                if not 1 <= page.page_number <= len(doc):
                    raise ValueError("LOCAL_OCR_PAGE_INVALID")
                with closing(doc[page.page_number - 1]) as native:
                    w, h = native.get_size()
                    media = native.get_mediabox()
                    if (
                        native.get_rotation()
                        or media[:2] != (0, 0)
                        or native.get_cropbox() != media
                        or w * h * 9 > LOCK["max_pixels"]
                        or not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h)
                        or abs(page.width - w) > 0.001
                        or abs(page.height - h) > 0.001
                    ):
                        raise ValueError("LOCAL_OCR_GEOMETRY_UNSUPPORTED")
                    with closing(native.render(scale=3, draw_annots=True)) as bitmap:
                        with bitmap.to_pil() as image:
                            pixels = [
                                math.floor(box[0] * 3),
                                math.floor(box[1] * 3),
                                math.ceil(box[2] * 3),
                                math.ceil(box[3] * 3),
                            ]
                            with image.crop(pixels) as crop:
                                with ImageOps.expand(
                                    crop, border=padding_px, fill="white"
                                ) as padded:
                                    buffer = io.BytesIO()
                                    padded.save(buffer, format="PNG")
            png = buffer.getvalue()
            output = subprocess.run(
                [
                    shutil.which("tesseract"),
                    "stdin",
                    "stdout",
                    "--tessdata-dir",
                    str(TESSDATA),
                    "-l",
                    "kor+eng",
                    "--oem",
                    "1",
                    "--psm",
                    "6",
                ],
                input=png,
                capture_output=True,
                check=True,
                timeout=30,
                env={"LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"},
            )
            text = output.stdout.decode("utf-8", "strict")
            if len(text) > 200000:
                raise ValueError("LOCAL_OCR_TEXT_LIMIT")
            result = dict(
                status="read",
                reader=LOCK["profile"],
                text=text,
                image_sha256=sha256(png).hexdigest(),
                source_sha256=sha256(self.source).hexdigest(),
                physical_page=page.page_number,
                box=list(box),
                padding_px=padding_px,
                reader_policy=self.policy,
            )
            self.cache[key] = result
            return dict(result)
        except (
            AttributeError,
            TypeError,
            ValueError,
            OSError,
            UnicodeError,
            subprocess.SubprocessError,
            pdfium.PdfiumError,
        ):
            return dict(
                status="unresolved", reason="local_raster_read_unresolved", reader=LOCK["profile"]
            )
