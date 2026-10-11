"""Bound local Java preprocessing to selected pages; retain the original mapping."""

from copy import deepcopy
from hashlib import sha256

from pypdf import PdfReader, PdfWriter

POLICY = {
    "profile": "selected-pdf-h1-v1",
    "input": "selected-original-pages-only; unchanged-page-objects-and-geometry",
    "mapping": "explicit-one-based-subset-to-original; nested-page-numbers",
    "jvm": "existing-sanitized-child-environment; heap-half-parser-memory",
    "failure": "bounded-failure; no-higher-memory-or-paid-retry",
    "artifacts": "subset-pdf-and-raw-json-plus-page-map-and-hashes",
}


def prepare(source, selected, work):
    reader = PdfReader(source, strict=False)
    pages = list(selected)
    if (
        pages != sorted(set(pages))
        or not pages
        or any(type(p) is not int or not 1 <= p <= len(reader.pages) for p in pages)
    ):
        raise ValueError("LOCAL_PAGE_SELECTION_INVALID")
    writer = PdfWriter()
    for number in pages:
        writer.add_page(reader.pages[number - 1])
    path = work / "local-selected.pdf"
    with path.open("xb") as stream:
        writer.write(stream)
    return path, pages


def restore_pages(raw, page_map, original_page_count):
    if raw.get("number of pages") != len(page_map):
        raise ValueError("LOCAL_PAGE_MAPPING_INVALID")
    mapped = deepcopy(raw)
    stack = [mapped]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if "page number" in item:
                number = item["page number"]
                if type(number) is not int or not 1 <= number <= len(page_map):
                    raise ValueError("LOCAL_PAGE_MAPPING_INVALID")
                item["page number"] = page_map[number - 1]
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    mapped["number of pages"] = original_page_count
    return mapped


def receipt(source, selected_pdf, page_map, raw, *, original_page_count):
    from proofops.domain.provenance import canonical_hash

    return dict(
        policy=POLICY,
        policy_sha256=canonical_hash(POLICY),
        source_sha256=sha256(source.read_bytes()).hexdigest(),
        subset_sha256=sha256(selected_pdf.read_bytes()).hexdigest(),
        raw_json_sha256=canonical_hash(raw),
        original_page_count=original_page_count,
        physical_page_map=page_map,
    )
