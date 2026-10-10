"""Standalone bounded CPU worker. No application imports or provider credentials."""

import json
import sys
from importlib.metadata import version
from pathlib import Path

VERSION = "2.137.0"


def main(work):
    if version("docling") != VERSION:
        raise ValueError("DOCLING_VERSION_UNSUPPORTED")
    import pypdfium2 as pdfium
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        PdfPipelineOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    request = json.loads((work / "request.json").read_bytes())
    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=2)
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        }
    )
    number = request["page"]
    result = converter.convert(work / "source.pdf", page_range=(number, number))
    if result.status.value != "success":
        raise ValueError("DOCLING_CONVERSION_INCOMPLETE")
    raw = result.document.export_to_dict()
    if set(map(int, raw["pages"])) != {number}:
        raise ValueError("DOCLING_PAGE_MAPPING_INVALID")
    with pdfium.PdfDocument(work / "source.pdf") as pdf:
        page = pdf.get_page(number - 1)
        try:
            # Rotated/cropped inputs require a dedicated tested transform, never guess.
            crop = list(page.get_bbox())
            rotation = page.get_rotation() % 360
            if rotation or crop[:2] != [0, 0]:
                raise ValueError("DOCLING_ROTATED_OR_CROPPED_PAGE_REQUIRES_REVIEW")
            geometry = dict(
                width_pt=page.get_width(),
                height_pt=page.get_height(),
                rotation=rotation,
                crop_box=crop,
            )
            text = page.get_textpage()
            try:
                chars = [
                    dict(text=text.get_text_range(i, 1), bbox=list(text.get_charbox(i)))
                    for i in range(text.count_chars())
                ]
            finally:
                text.close()
        finally:
            page.close()
    output = dict(
        version=VERSION,
        page=number,
        document=raw,
        geometry=geometry,
        chars=chars,
        options=dict(
            do_ocr=False, table_mode="accurate", do_cell_matching=True, device="cpu", num_threads=2
        ),
    )
    (work / "result.json").write_text(json.dumps(output, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
