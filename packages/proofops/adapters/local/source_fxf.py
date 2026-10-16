"""Original bounded PDFium page pixels for trusted, portable OCR collections.

No repaired PDF, character substitutions or caller-supplied OCR is admitted.
Historical page renderers and their receipt policies remain byte-for-byte intact.
"""

import io
from contextlib import closing
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium

from proofops.adapters.local import source_h7
from proofops.adapters.local.local_raster_reader import interactive_catalog_requires_review
from proofops.adapters.local.upstage_ocr_page import MAX_PIXELS, reader_policy


def policy():
    return dict(
        profile="fxf_bounded-page-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        scale_helper_sha256=sha256(Path(source_h7.__file__).read_bytes()).hexdigest(),
        ocr_policy=reader_policy(),
        renderer_version=version("pypdfium2"),
        pillow_version=version("pillow"),
        max_pixels=MAX_PIXELS,
        max_pages=10,
        pixel_mapping="PDFium-page-to-device; width_pt/pixel_width; height_pt/pixel_height",
        admission="original-annotated-pixels; exact-text; FXA-native-guards",
    )


def render_page(source, page_num):
    if (
        not isinstance(source, bytes)
        or not 0 < len(source) <= 100 * 1024 * 1024
        or type(page_num) is not int
    ):
        raise ValueError("FXF_SOURCE_INVALID")
    if interactive_catalog_requires_review(source):
        raise ValueError("FXF_INTERACTIVE_VISIBILITY")
    with pdfium.PdfDocument(source) as document:
        if not 1 <= page_num <= len(document):
            raise ValueError("FXF_PAGE_INVALID")
        with closing(document[page_num - 1]) as page:
            width, height = page.get_size()
            media, crop = page.get_mediabox(), page.get_cropbox()
            if page.get_rotation() or media[:2] != (0, 0) or crop != media:
                raise ValueError("FXF_PAGE_GEOMETRY_UNSUPPORTED")
            scale = source_h7.render_scale(width, height)
            with closing(page.render(scale=scale, draw_annots=True)) as bitmap:
                if bitmap.width * bitmap.height > MAX_PIXELS:
                    raise ValueError("FXF_RENDER_LIMIT")
                with bitmap.to_pil() as image:
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    size = list(image.size)
    png = buffer.getvalue()
    if len(png) > 50 * 1024 * 1024:
        raise ValueError("FXF_RENDER_LIMIT")
    # PDFium's integer viewport rounds the requested scale outward. Mapping
    # pixels back uses the page dimensions divided by that actual viewport.
    manifest = dict(
        profile="fxf_bounded-page-v1",
        source_sha256=sha256(source).hexdigest(),
        physical_page=page_num,
        rotation=0,
        crop_box=list(crop),
        media_box=list(media),
        width_pt=width,
        height_pt=height,
        pixel_size=size,
        png_sha256=sha256(png).hexdigest(),
        renderer="PDFium",
        renderer_version=version("pypdfium2"),
        scale=scale,
        draw_annotations=True,
    )
    return dict(manifest=manifest, png=png)
