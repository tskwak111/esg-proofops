"""Bounded original PDFium region rendering without shrinking the entire page."""

import io
import math
import subprocess
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdfium
from PIL import ImageOps

from proofops.adapters.local import source_h7

MAX_PIXELS = source_h7.MAX_PIXELS
SCALE = 3


def policy():
    return dict(
        profile="original-region-fxe-v1",
        base=source_h7.policy(),
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        render="original-page-objects; outward-rounded-region; 216dpi; annotations",
        max_pixels=MAX_PIXELS,
        oversized_region="unresolved; no-downscale",
    )


class RasterReader(source_h7.RasterReader):
    def read(self, page, box, *, padding_px=0):
        if self.visibility_hold:
            return dict(status="unresolved", reason="interactive_visibility_requires_review")
        try:
            if (
                not isinstance(self.source, bytes)
                or not 0 < len(self.source) <= 100 * 1024 * 1024
                or type(page.page_number) is not int
                or type(padding_px) is not int
                or padding_px not in (0, 6)
                or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
            ):
                raise ValueError("FXE_RENDER_INPUT_INVALID")
            key = (page.page_number, page.width, page.height, tuple(box), padding_px)
            if key in self.cache:
                return dict(self.cache[key])
            with pdfium.PdfDocument(self.source) as document:
                if not 1 <= page.page_number <= len(document):
                    raise ValueError("FXE_PAGE_MAPPING_MISMATCH")
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
                        raise ValueError("FXE_PAGE_MAPPING_MISMATCH")
                    width, height = math.ceil(w * SCALE), math.ceil(h * SCALE)
                    left, top = math.floor(box[0] * SCALE), math.floor(box[1] * SCALE)
                    right, bottom = math.ceil(box[2] * SCALE), math.ceil(box[3] * SCALE)
                    if (right - left + 2 * padding_px) * (
                        bottom - top + 2 * padding_px
                    ) > MAX_PIXELS:
                        raise ValueError("FXE_REGION_RENDER_LIMIT")
                    # PDFium's crop is rounded UP in pixels. nextafter avoids
                    # an extra pixel from division/multiplication roundoff.
                    crop = tuple(
                        math.nextafter(value / SCALE, -math.inf) if value else 0
                        for value in (left, height - bottom, width - right, top)
                    )
                    with closing(native.render(scale=SCALE, crop=crop, draw_annots=True)) as bitmap:
                        if (bitmap.width, bitmap.height) != (right - left, bottom - top):
                            raise ValueError("FXE_PIXEL_MAPPING_MISMATCH")
                        with (
                            bitmap.to_pil() as image,
                            ImageOps.expand(image, border=padding_px, fill="white") as padded,
                        ):
                            buffer = io.BytesIO()
                            padded.save(buffer, format="PNG")
            png = buffer.getvalue()
            result = dict(
                **source_h7._ocr(png),
                status="read",
                source_sha256=self.digest,
                image_sha256=sha256(png).hexdigest(),
                physical_page=page.page_number,
                bbox=list(box),
                scale=SCALE,
                padding_px=padding_px,
                pixel_bbox=[left, top, right, bottom],
                page_pixels=[width, height],
                rendered_pixels=[right - left, bottom - top],
                max_pixels=MAX_PIXELS,
                crop_to_pdf=[
                    1 / SCALE,
                    0,
                    0,
                    1 / SCALE,
                    (left - padding_px) / SCALE,
                    (top - padding_px) / SCALE,
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
                reason="fxe_raster_unresolved",
                error=str(error) if isinstance(error, ValueError) else type(error).__name__,
            )
