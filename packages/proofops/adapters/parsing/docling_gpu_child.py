"""Standalone SSH worker: one CUDA conversion per document, picture text retained."""

import gzip
import json
import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from time import monotonic


def page_document(document, number):
    result = {"pages": {str(number): document["pages"][str(number)]}}
    for key in ("texts", "tables", "pictures"):
        result[key] = [
            item
            for item in document.get(key, [])
            if any(p["page_no"] == number for p in item.get("prov", []))
        ]
    return result


def main(work):
    import pypdfium2 as pdfium
    import torch
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice,
        AcceleratorOptions,
        PdfPipelineOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    request = json.loads((work / "request.json").read_bytes())
    if version("docling") != "2.137.0" or not torch.cuda.is_available():
        raise ValueError("PINNED_DOCLING_CUDA_REQUIRED")
    if torch.cuda.device_count() != 1:
        raise ValueError("EXPLICIT_SINGLE_GPU_ALLOCATION_REQUIRED")
    device = torch.cuda.get_device_properties(0)
    if "A100" not in device.name or not 39 * 1024**3 < device.total_memory < 41 * 1024**3:
        raise ValueError("A100_40GB_ALLOCATION_REQUIRED")
    digest = sha256((work / "source.pdf").read_bytes()).hexdigest()
    if digest != request["source_sha256"]:
        raise ValueError("SOURCE_INTEGRITY_MISMATCH")
    pages = request["pages"]
    if not pages or pages != sorted(set(pages)) or any(type(p) is not int or p < 1 for p in pages):
        raise ValueError("PAGE_SELECTION_INVALID")
    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA, num_threads=16)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    # Sparse selections are contiguous groups; never process unrequested pages.
    groups = []
    for p in pages:
        if groups and groups[-1][-1] + 1 == p:
            groups[-1].append(p)
        else:
            groups.append([p])
    started = monotonic()
    output, markdown = {}, {}
    with pdfium.PdfDocument(work / "source.pdf") as pdf:
        if max(pages) > len(pdf):
            raise ValueError("PAGE_SELECTION_INVALID")
        for group in groups:
            result = converter.convert(work / "source.pdf", page_range=(group[0], group[-1]))
            if result.status.value != "success" or result.errors:
                raise ValueError("DOCLING_CONVERSION_INCOMPLETE")
            raw = result.document.export_to_dict()
            if set(map(int, raw["pages"])) != set(group):
                raise ValueError("DOCLING_PAGE_MAPPING_INVALID")
            for number in group:
                page = pdf.get_page(number - 1)
                try:
                    crop = list(page.get_bbox())
                    if page.get_rotation() or crop[:2] != [0, 0]:
                        raise ValueError("ROTATED_OR_CROPPED_PAGE_REQUIRES_REVIEW")
                    geometry = dict(
                        width_pt=page.get_width(),
                        height_pt=page.get_height(),
                        rotation=0,
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
                output[str(number)] = dict(
                    version=version("docling"),
                    page=number,
                    document=page_document(raw, number),
                    geometry=geometry,
                    chars=chars,
                    options=dict(
                        do_ocr=False,
                        table_mode="accurate",
                        do_cell_matching=True,
                        device="cuda",
                        num_threads=16,
                    ),
                )
                # Display cleanup only: raw JSON and native glyphs retain original offsets.
                markdown[str(number)] = result.document.export_to_markdown(
                    page_no=number, traverse_pictures=True
                ).replace("\x07", "")
    envelope = dict(
        source_sha256=digest,
        pages=output,
        pages_markdown=markdown,
        device=device.name,
        device_memory=device.total_memory,
        docling_version=version("docling"),
        torch_version=torch.__version__,
        duration_seconds=monotonic() - started,
        worker_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    payload = json.dumps(envelope, ensure_ascii=True).encode()
    if len(payload) > request["max_output_bytes"]:
        raise ValueError("PARSER_OUTPUT_LIMIT")
    temporary = work / "result.tmp"
    temporary.write_bytes(gzip.compress(payload))
    temporary.replace(work / "result.json.gz")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
