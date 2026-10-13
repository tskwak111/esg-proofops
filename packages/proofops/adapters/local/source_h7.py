"""Bounded PDFium pixels and conservative metadata from unchanged original bytes.

Historical readers are untouched. A tolerant page supplies only geometry,
annotations and negative layout guards; PDFium glyphs and exact raster OCR still
have to prove every admitted quote. No repaired PDF is created or read here.
"""

import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
from contextlib import closing
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pdfminer.psparser import LIT
from PIL import ImageOps
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from proofops.adapters.local.local_raster_reader import (
    TESSDATA,
    interactive_catalog_requires_review,
    runtime_policy,
)

MAX_PIXELS = 16_000_000
OCR_SCRIPT = Path(__file__).with_name("native_ocr.swift")


def policy():
    return dict(
        profile="original-pdfium-bounded-h7-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        ocr_sha256=sha256(OCR_SCRIPT.read_bytes()).hexdigest(),
        versions={n: version(n) for n in ("pypdfium2", "pypdf", "pillow")},
        max_pixels=MAX_PIXELS,
        nominal_scale=3,
        transform="isotropic-scale; outward-floor-ceil; pdf-top-left-points",
        admission="unchanged-EV1-literal-glyph-layout-and-exact-raster-text",
        runtime="Apple-Vision-CPU" if sys.platform == "darwin" else runtime_policy(),
        paid_calls=0,
    )


def render_scale(width, height, max_pixels=MAX_PIXELS):
    if (
        any(not math.isfinite(v) or v <= 0 for v in (width, height))
        or type(max_pixels) is not int
        or not 1 <= max_pixels <= MAX_PIXELS
    ):
        raise ValueError("H7_RENDER_GEOMETRY_INVALID")
    if math.ceil(width * 3) * math.ceil(height * 3) <= max_pixels:
        return 3.0
    low, high = 0.0, min(3.0, math.sqrt(max_pixels / (width * height)))
    # PDFium rounds each bitmap dimension up, so area alone is insufficient.
    for _ in range(64):
        middle = (low + high) / 2
        if math.ceil(width * middle) * math.ceil(height * middle) <= max_pixels:
            low = middle
        else:
            high = middle
    if low <= 0:
        raise ValueError("H7_RENDER_GEOMETRY_INVALID")
    return low


def _ocr(png):
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory(prefix="proofops-h7-") as folder:
            path = Path(folder) / "region.png"
            path.write_bytes(png)
            result = subprocess.run(
                ["swift", str(OCR_SCRIPT), str(path)],
                capture_output=True,
                check=True,
                timeout=30,
            )
        reading = json.loads(result.stdout)
    else:
        if runtime_policy()["status"] != "ready":
            raise ValueError("H7_LOCAL_OCR_UNAVAILABLE")
        result = subprocess.run(
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
        reading = dict(text=result.stdout.decode("utf-8", "strict"), reader="pinned-CPU-OCR")
    if not isinstance(reading.get("text"), str) or len(reading["text"]) > 200000:
        raise ValueError("H7_OCR_RESPONSE_INVALID")
    return reading


class RasterReader:
    def __init__(self, source, *, max_pixels=MAX_PIXELS):
        self.source, self.max_pixels = source, max_pixels
        self.digest = sha256(source).hexdigest()
        self._image = None
        self._page_number = None
        self.cache = {}
        try:
            self.visibility_hold = interactive_catalog_requires_review(source)
        except (PdfReadError, ValueError, KeyError, TypeError, AttributeError):
            self.visibility_hold = True

    def close(self):
        if self._image is not None:
            self._image.close()
            self._image = None

    def read(self, page, box, *, padding_px=0):
        if self.visibility_hold:
            return dict(status="unresolved", reason="interactive_visibility_requires_review")
        try:
            if (
                type(page.page_number) is not int
                or type(padding_px) is not int
                or padding_px not in (0, 6)
                or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
            ):
                raise ValueError("H7_RENDER_INPUT_INVALID")
            key = (page.page_number, page.width, page.height, tuple(box), padding_px)
            if key in self.cache:
                return dict(self.cache[key])
            with pdfium.PdfDocument(self.source) as document:
                if not 1 <= page.page_number <= len(document):
                    raise ValueError("H7_PAGE_MAPPING_MISMATCH")
                with closing(document[page.page_number - 1]) as native:
                    w, h = native.get_size()
                    media = native.get_mediabox()
                    if (
                        native.get_rotation()
                        or media[:2] != (0, 0)
                        or native.get_cropbox() != media
                        or abs(page.width - w) > 0.001
                        or abs(page.height - h) > 0.001
                        or not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h)
                    ):
                        raise ValueError("H7_PAGE_MAPPING_MISMATCH")
                    scale = render_scale(w, h, self.max_pixels)
                    if scale == 3 and sys.platform == "darwin" and hasattr(page, "to_image"):
                        # Preserve the normal report's exact raster/OCR path.
                        # Only pages that need bounding gain the new renderer.
                        from proofops.adapters.local.source_verification import _rendered_text

                        reading = _rendered_text(page, box, padding_px=padding_px)
                        if reading.get("status") != "read":
                            return reading
                        pixels = reading["pixel_bbox"]
                        result = dict(
                            reading,
                            source_sha256=self.digest,
                            physical_page=page.page_number,
                            bbox=list(box),
                            page_pixels=[math.ceil(w * scale), math.ceil(h * scale)],
                            max_pixels=self.max_pixels,
                            pixel_to_pdf_bbox=[v / scale for v in pixels],
                            crop_to_pdf=[
                                1 / scale,
                                0,
                                0,
                                1 / scale,
                                (pixels[0] - padding_px) / scale,
                                (pixels[1] - padding_px) / scale,
                            ],
                        )
                        self.cache[key] = result
                        return dict(result)
                    if self._page_number != page.page_number or self._image is None:
                        self.close()
                        with closing(native.render(scale=scale, draw_annots=True)) as bitmap:
                            self._image = bitmap.to_pil().copy()
                        self._page_number = page.page_number
                    image = self._image
                    if image.width * image.height > self.max_pixels:
                        raise ValueError("H7_RENDER_LIMIT")
                    pixels = [
                        math.floor(box[0] * scale),
                        math.floor(box[1] * scale),
                        math.ceil(box[2] * scale),
                        math.ceil(box[3] * scale),
                    ]
                    if (pixels[2] - pixels[0] + 2 * padding_px) * (
                        pixels[3] - pixels[1] + 2 * padding_px
                    ) > self.max_pixels:
                        raise ValueError("H7_CROP_LIMIT")
                    with (
                        image.crop(pixels) as crop,
                        ImageOps.expand(crop, border=padding_px, fill="white") as padded,
                    ):
                        buffer = io.BytesIO()
                        padded.save(buffer, format="PNG")
            png = buffer.getvalue()
            result = dict(
                **_ocr(png),
                status="read",
                source_sha256=self.digest,
                image_sha256=sha256(png).hexdigest(),
                physical_page=page.page_number,
                bbox=list(box),
                scale=scale,
                padding_px=padding_px,
                pixel_bbox=pixels,
                page_pixels=[image.width, image.height],
                max_pixels=self.max_pixels,
                pixel_to_pdf_bbox=[v / scale for v in pixels],
                crop_to_pdf=[
                    1 / scale,
                    0,
                    0,
                    1 / scale,
                    (pixels[0] - padding_px) / scale,
                    (pixels[1] - padding_px) / scale,
                ],
            )
            self.cache[key] = result
            return dict(result)
        except (
            ValueError,
            TypeError,
            AttributeError,
            OSError,
            UnicodeError,
            subprocess.SubprocessError,
            pdfium.PdfiumError,
        ) as error:
            return dict(
                status="unresolved",
                reason="h7_raster_unresolved",
                error=str(error) if isinstance(error, ValueError) else type(error).__name__,
            )


class OriginalPage:
    """Tolerant original metadata; paths only veto prose, never approve tables."""

    def __init__(self, page, native, number):
        self.page_number = number
        self.mediabox = tuple(float(v) for v in page.mediabox)
        self.cropbox = tuple(float(v) for v in page.cropbox)
        self.width = self.mediabox[2] - self.mediabox[0]
        self.height = self.mediabox[3] - self.mediabox[1]
        self.rotation = page.rotation
        if (
            any(abs(a - b) > 0.001 for a, b in zip(self.mediabox, native.get_mediabox()))
            or any(abs(a - b) > 0.001 for a, b in zip(self.cropbox, native.get_cropbox()))
            or self.rotation != native.get_rotation()
            or page.get("/UserUnit", 1) != 1
        ):
            raise ValueError("H7_PAGE_MAPPING_MISMATCH")
        self.annots = []
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            bounds = annotation.get("/Rect")
            data = {str(k)[1:]: v for k, v in annotation.items()}
            data["Subtype"] = LIT(str(annotation.get("/Subtype", ""))[1:])
            item = dict(data=data)
            if bounds is not None and len(bounds) == 4:
                item.update(
                    x0=float(bounds[0]),
                    x1=float(bounds[2]),
                    top=self.height - float(bounds[3]),
                    bottom=self.height - float(bounds[1]),
                )
            self.annots.append(item)
        self.edges, self.regions = [], []
        for obj in native.get_objects(max_depth=16):
            if obj.type == raw.FPDF_PAGEOBJ_FORM and obj.level >= 15:
                raise ValueError("H7_LAYOUT_DEPTH_UNRESOLVED")
            if obj.type != raw.FPDF_PAGEOBJ_PATH:
                continue
            bounds = obj.get_bounds()
            parent = obj.container
            while parent is not None:
                matrix = parent.get_matrix()
                if (
                    not all(math.isfinite(v) for v in matrix.get())
                    or matrix.b
                    or matrix.c
                    or not matrix.a
                    or not matrix.d
                ):
                    raise ValueError("H7_LAYOUT_TRANSFORM_UNRESOLVED")
                bounds = matrix.on_rect(*bounds)
                parent = parent.container
            left, bottom, right, top = bounds
            box = (left, self.height - top, right, self.height - bottom)
            if not all(math.isfinite(v) for v in box):
                raise ValueError("H7_LAYOUT_GEOMETRY_UNRESOLVED")
            # Broad negative guard includes filled boxes and curved paths too.
            # Page-sized backgrounds have no row ownership signal.
            if right - left < 0.95 * self.width or top - bottom < 0.5 * self.height:
                self.regions.append(SimpleNamespace(bbox=box))
            if top - bottom <= 2:
                self.edges.append(dict(orientation="h", x0=left, x1=right, top=box[1]))

    def find_tables(self, settings):
        return self.regions


class OriginalDocument:
    def __init__(self, source, native):
        self.reader = PdfReader(io.BytesIO(source), strict=False)
        if len(self.reader.pages) != len(native):
            raise ValueError("H7_PAGE_MAPPING_MISMATCH")
        root = self.reader.trailer["/Root"]
        form = root.get("/AcroForm")
        form = form.get_object() if form is not None else None
        catalog = {}
        if "/OCProperties" in root:
            catalog["OCProperties"] = True
        if "/AcroForm" in root:
            catalog["AcroForm"] = (
                {str(k)[1:]: v for k, v in form.items()} if isinstance(form, dict) else None
            )
        self.doc = SimpleNamespace(catalog=catalog)
        self.native = native
        self.pages = self
        self.cache = {}

    def __len__(self):
        return len(self.reader.pages)

    def __getitem__(self, index):
        if index not in self.cache:
            with closing(self.native[index]) as page:
                self.cache[index] = OriginalPage(self.reader.pages[index], page, index + 1)
        return self.cache[index]
