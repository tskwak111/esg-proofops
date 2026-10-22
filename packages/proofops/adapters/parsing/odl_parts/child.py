"""Isolated PDF geometry, JVM conversion and auxiliary-table child body."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.parsing.odl_parts.common import ParseFailure, _json
from proofops.adapters.parsing.odl_parts.policies import _local_pages
from proofops.domain.documents import PageGeometry


def run(work: Path, *, child_body) -> None:
    from proofops.adapters.parsing import spp_execution

    profile = json.loads((work / "request.json").read_bytes())["profile"]
    cache = spp_execution.LocalPageCache() if spp_execution.enabled(profile) else None
    try:
        child_body(work, cache)
    finally:
        if cache is not None:
            cache.close()


def run_body(work: Path, page_cache=None, *, apply_limits, locates_auxiliary_cells) -> None:
    from pypdf import PdfReader

    request = json.loads((work / "request.json").read_bytes())
    profile, selected = request["profile"], request["selected"]
    apply_limits(profile)
    reader = PdfReader(
        work / "source.pdf",
        strict=request.get("upload_security_profile", "strict-v1") == "strict-v1",
    )
    if reader.is_encrypted and not reader.decrypt(""):
        raise ParseFailure("PDF_PASSWORD_REQUIRED")
    geometries = {}
    page_labels = reader.page_labels if page_cache is not None else None
    for number in selected:
        page = reader.pages[number - 1]
        rotation = int(page.rotation) % 360

        def box_geometry(box):
            x0, y0, x1, y1 = map(float, box)
            width, height = x1 - x0, y1 - y0
            if rotation in (90, 270):
                width, height = height, width
            return asdict(PageGeometry(width, height, rotation, (x0, y0, x1, y1)))

        geometries[str(number)] = dict(
            crop=box_geometry(page.cropbox),
            media=box_geometry(page.mediabox),
            printed_page_label=(page_labels or reader.page_labels)[number - 1],
        )
    (work / "geometry.json").write_bytes(_json(geometries))
    import opendataloader_pdf

    input_path, java_pages = work / "source.pdf", selected
    h6 = profile.get("local_resource_policy") in {"selected-pdf-h6-v1", "selected-pdf-h6-v2"}
    if h6:
        subset = _local_pages(profile).subset

        input_path = work / "h6-selected.pdf"
        input_path.write_bytes(subset((work / "source.pdf").read_bytes(), tuple(selected)))
        java_pages = tuple(range(1, len(selected) + 1))
    if profile.get("local_resource_policy") == "selected-pdf-h1-v1":
        from proofops.adapters.parsing.h1_local_pages import prepare

        input_path, page_map = prepare(input_path, selected, work)
        java_pages = tuple(range(1, len(page_map) + 1))
    try:
        opendataloader_pdf.convert(
            input_path=[str(input_path)],
            output_dir=str(work),
            format="json,markdown",
            pages=",".join(map(str, java_pages)),
            image_output="off",
            hybrid="off",
            quiet=True,
        )
    except subprocess.CalledProcessError as error:
        stderr = error.stderr or b""
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8", errors="replace")
        path = work / "parser-stderr.txt"
        path.write_bytes(stderr[:65536])
        path.chmod(0o600)
        raise
    if profile.get("local_resource_policy") == "selected-pdf-h1-v1":
        from proofops.adapters.parsing.h1_local_pages import receipt, restore_pages

        raw_subset = json.loads((work / "local-selected.json").read_bytes())
        mapped = restore_pages(raw_subset, page_map, len(reader.pages))
        (work / "source.json").write_bytes(_json(mapped))
        (work / "source.md").write_bytes((work / "local-selected.md").read_bytes())
        (work / "local-page-map.json").write_bytes(
            _json(
                receipt(
                    work / "source.pdf",
                    input_path,
                    page_map,
                    raw_subset,
                    original_page_count=len(reader.pages),
                )
            )
        )
    elif h6:
        remap = _local_pages(profile).remap

        raw_subset = json.loads((work / "h6-selected.json").read_bytes())
        (work / "source.json").write_bytes(
            _json(remap(raw_subset, selected, len(reader.pages), ""))
        )
        (work / "source.md").write_bytes((work / "h6-selected.md").read_bytes())
        if not profile["table_auxiliary"]:
            (work / "auxiliary.json").write_bytes(_json(dict(kids=[])))
    if profile.get("table_structure_repair") in ("odl_header_v1", "odl_header_v2"):
        import pdfplumber
        from proofops.adapters.parsing.odl_table_repair import repair_stacked_headers

        # Unsupported page transforms remain untouched, never guessed.
        words_by_page = {}
        open_pdf = page_cache.open if page_cache is not None else pdfplumber.open
        with open_pdf(input_path if h6 else work / "source.pdf") as document:
            for number in selected:
                info = geometries[str(number)]
                crop, media = info["crop"], info["media"]
                if crop != media or crop["rotation"] or crop["crop_box"][:2] != (0, 0):
                    continue
                page = document.pages[selected.index(number) if h6 else number - 1]
                words_by_page[number] = [
                    {
                        "text": word["text"],
                        "bbox": [
                            word["x0"],
                            page.height - word["bottom"],
                            word["x1"],
                            page.height - word["top"],
                        ],
                    }
                    for word in page.extract_words()
                ]
        raw = json.loads((work / "source.json").read_bytes())
        repaired, receipts = repair_stacked_headers(
            raw, words_by_page, locate_rows=profile["table_structure_repair"] == "odl_header_v2"
        )
        (work / "source-repaired.json").write_bytes(_json(repaired))
        (work / "table-repair.json").write_bytes(
            _json(
                dict(
                    version=profile["table_structure_repair"],
                    source_json_sha256=sha256(_json(raw)).hexdigest(),
                    receipts=receipts,
                )
            )
        )
    if profile["table_auxiliary"]:
        import pdfplumber

        nodes = []
        open_pdf = page_cache.open if page_cache is not None else pdfplumber.open
        with open_pdf(input_path if h6 else work / "source.pdf") as document:
            for number in selected:
                page = document.pages[selected.index(number) if h6 else number - 1]
                for index, table in enumerate(page.find_tables()):
                    table_id = f"p{number}-t{index}"
                    options = {}
                    if profile.get("table_text_y_tolerance") is not None:
                        options["y_tolerance"] = profile["table_text_y_tolerance"]
                    rows, texts = [], table.extract(**options)
                    for row_index, row in enumerate(table.rows):
                        cells = []
                        for column_index, bbox in enumerate(row.cells):
                            if bbox is None:
                                continue
                            cells.append(
                                dict(
                                    type="table cell",
                                    id=f"{table_id}-r{row_index}-c{column_index}",
                                    **{
                                        "page number": number,
                                        "bounding box": bbox,
                                        "page origin": page.bbox[:2],
                                        "row number": row_index + 1,
                                        "column number": column_index + 1,
                                        "content": texts[row_index][column_index] or "",
                                    },
                                )
                            )
                        rows.append(
                            dict(
                                type="table row",
                                id=f"{table_id}-r{row_index}",
                                cells=cells,
                                **{
                                    "page number": number,
                                    "bounding box": row.bbox,
                                    "page origin": page.bbox[:2],
                                    "row number": row_index + 1,
                                },
                            )
                        )
                    nodes.append(
                        dict(
                            type="table",
                            id=table_id,
                            rows=rows,
                            **{
                                "page number": number,
                                "bounding box": table.bbox,
                                "page origin": page.bbox[:2],
                            },
                        )
                    )
        (work / "auxiliary.json").write_bytes(_json(dict(kids=nodes)))
        if locates_auxiliary_cells(profile):
            from proofops.adapters.local.native_glyph_geometry import native_word_ink_geometry
            from proofops.adapters.parsing.odl_table_repair import locate_auxiliary_cells

            # pdfplumber assigns a slot's text by ink midpoint, so a detected slot
            # can hold text its own box does not contain. Snap each slot onto the
            # ink it owns; a table whose ownership is not exact stays untouched.
            words_by_page = {}
            source_pdf_bytes = (work / "source.pdf").read_bytes()
            with open_pdf(input_path if h6 else work / "source.pdf") as document:
                for number in selected:
                    page = document.pages[selected.index(number) if h6 else number - 1]
                    raw_words = page.extract_words()
                    if not raw_words:
                        continue
                    word_indices = list(range(len(raw_words)))
                    try:
                        ink_res = native_word_ink_geometry(source_pdf_bytes, number, word_indices)
                        matched_map = {
                            m["native_word_index"]: m["ink_bbox"]
                            for m in ink_res.get("matched_words", [])
                        }
                        unresolved_set = set(ink_res.get("unresolved_word_indices", []))
                    except Exception:
                        matched_map = {}
                        unresolved_set = set(word_indices)
                    words_by_page[number] = [
                        {
                            "text": word["text"],
                            "bbox": [word["x0"], word["top"], word["x1"], word["bottom"]],
                            "ink_bbox": matched_map.get(idx),
                            "resolved": idx in matched_map and idx not in unresolved_set,
                        }
                        for idx, word in enumerate(raw_words)
                    ]
            located, receipts = locate_auxiliary_cells(
                nodes, words_by_page, source=source_pdf_bytes
            )
            (work / "auxiliary.json").write_bytes(_json(dict(kids=located, cell_locate=receipts)))
