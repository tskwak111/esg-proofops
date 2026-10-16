"""RG1 adaptive batches; original H6 bisection, limits and replay remain intact."""

import io
import json
import os
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from time import monotonic

import pypdfium2 as pdfium
from proofops.domain.provenance import canonical_hash

POLICY = {
    "profile": "selected-pdf-h6-v2",
    "batch_pages": "normal-selected-scope; oversized-pages-four",
    "subset": "PDFium-import-original-page-objects; candidate-only",
    "mapping": "original-physical-pages-and-geometry; batch-prefixed-native-ids",
    "limits": "existing-process-memory; shared-wall-deadline-and-output-ceiling",
    "failure": "bisect-local-batch; single-page-unreadable; no-paid-retry",
}
FAILURES = {
    "PARSER_MEMORY_LIMIT",
    "PARSER_JAVA_HEAP_EXHAUSTED",
    "PARSER_FAILED",
    "PARSER_NATIVE_TEXT_UNREADABLE",
    "PARSER_SUBSET_PDF_INVALID",
}


def subset(content, pages):
    """Preserve page objects (including boxes/rotation), discarding broken xrefs."""
    if not pages or tuple(sorted(set(pages))) != tuple(pages):
        raise ValueError("UPSTAGE_PAGE_SELECTION_INVALID")
    with pdfium.PdfDocument(content) as source, pdfium.PdfDocument.new() as target:
        if any(type(p) is not int or not 1 <= p <= len(source) for p in pages):
            raise ValueError("UPSTAGE_PAGE_SELECTION_INVALID")
        target.import_pages(source, [p - 1 for p in pages])
        # Verify the displayed geometry before admitting any candidate coordinates.
        for i, number in enumerate(pages):
            a, b = source[number - 1], target[i]
            try:
                if any(
                    getattr(a, method)() != getattr(b, method)()
                    for method in ("get_size", "get_cropbox", "get_mediabox", "get_rotation")
                ):
                    raise ValueError("PARSER_GEOMETRY_INVALID")
            finally:
                a.close()
                b.close()
        stream = io.BytesIO()
        target.save(stream)
        return stream.getvalue()


def remap(raw, pages, count, prefix):
    from proofops.adapters.parsing.h1_local_pages import restore_pages

    return _prefix(restore_pages(raw, pages, count), prefix)


def batches(content, selected):
    """Amortize JVM startup for ordinary pages; bound oversized originals as H6."""
    with pdfium.PdfDocument(content) as document:
        oversized = False
        for number in selected:
            page = document[number - 1]
            try:
                width, height = page.get_size()
                oversized |= width * height * 9 > 16_000_000
            finally:
                page.close()
    size = 4 if oversized else 30
    return [selected[i : i + size] for i in range(0, len(selected), size)]


def execute(command, work, env, profile, run):
    """Each batch gets fresh Python/JVM heaps and the same aggregate deadline."""
    from proofops.adapters.parsing.opendataloader import ParseFailure, _json, _output_bytes

    request = json.loads((work / "request.json").read_bytes())
    selected = request["selected"]
    deadline = monotonic() + profile.timeout_seconds
    records, geometry, kids, auxiliary, markdown = [], {}, [], [], []
    repaired_kids, repairs = [], []
    pending = batches((work / "source.pdf").read_bytes(), selected)
    original_count = None
    while pending:
        pages = pending.pop(0)
        remaining = deadline - monotonic()
        if remaining <= 0:
            records.extend(
                dict(pages=p, status="unreadable", error_code="PARSER_TIMEOUT")
                for p in [pages, *pending]
            )
            break
        number = len(records)
        scratch = work / f"batch-{number}"
        scratch.mkdir(mode=0o700)
        try:
            os.link(work / "source.pdf", scratch / "source.pdf")
            child_request = deepcopy(request)
            child_request["selected"] = pages
            child_request["profile"]["timeout_seconds"] = remaining
            (scratch / "request.json").write_bytes(_json(child_request))
            child_env = dict(env)
            # Keep Windows scratch files inside this batch's watchdog directory.
            for key in ("TEMP", "TMP"):
                if key in child_env:
                    child_env[key] = str(scratch)
            child_command = [*command[:-1], str(scratch)]
            auxiliary_failure = None
            try:
                run(child_command, scratch, child_env, replace(profile, timeout_seconds=remaining))
            except ParseFailure as error:
                if str(error) not in FAILURES | {"PARSER_TIMEOUT"}:
                    raise
                if str(error) == "PARSER_NATIVE_TEXT_UNREADABLE" and all(
                    (scratch / name).is_file()
                    for name in ("source.json", "geometry.json", "source.md", "h6-selected.pdf")
                ):
                    # A secondary text reader may fail after ODL has succeeded.
                    # Keep the primary candidates and a separate unreadable issue.
                    auxiliary_failure = str(error)
                    (scratch / "auxiliary.json").write_bytes(_json(dict(kids=[])))
                    if profile.table_structure_repair is not None:
                        (scratch / "source-repaired.json").write_bytes(
                            (scratch / "source.json").read_bytes()
                        )
                        (scratch / "table-repair.json").write_bytes(
                            _json(dict(version=profile.table_structure_repair, status="unreadable"))
                        )
                elif len(pages) > 1 and str(error) in FAILURES:
                    middle = len(pages) // 2
                    pending[:0] = [pages[:middle], pages[middle:]]
                    continue
                else:
                    records.append(dict(pages=pages, status="unreadable", error_code=str(error)))
                    continue
            raw = json.loads((scratch / "source.json").read_bytes())
            count = raw["number of pages"]
            if original_count is not None and original_count != count:
                raise ParseFailure("PARSER_PAGE_MAPPING_INVALID")
            original_count = count
            prefix = f"h6-b{number}-"
            # The child already restores page numbers; prefix IDs across JVMs.
            raw = _prefix(raw, prefix)
            aux = _prefix(json.loads((scratch / "auxiliary.json").read_bytes()), prefix)
            info = json.loads((scratch / "geometry.json").read_bytes())
            if set(info) != set(map(str, pages)):
                raise ParseFailure("PARSER_PAGE_MAPPING_INVALID")
            artifacts = {}
            for name in ("source.json", "auxiliary.json", "geometry.json", "h6-selected.pdf"):
                data = (scratch / name).read_bytes()
                target = f"h6-b{number}-{name}"
                (work / target).write_bytes(data)
                artifacts[target] = sha256(data).hexdigest()
            records.append(dict(pages=pages, status="parsed", prefix=prefix, artifacts=artifacts))
            if auxiliary_failure:
                records[-1]["auxiliary_failure"] = auxiliary_failure
            geometry.update(info)
            kids.extend(raw["kids"])
            auxiliary.extend(aux["kids"])
            markdown.append((scratch / "source.md").read_text())
            if profile.table_structure_repair is not None:
                repaired = _prefix(
                    json.loads((scratch / "source-repaired.json").read_bytes()), prefix
                )
                repaired_kids.extend(repaired["kids"])
                repairs.append(json.loads((scratch / "table-repair.json").read_bytes()))
        finally:
            import shutil

            shutil.rmtree(scratch)
        if _output_bytes(work) > profile.max_output_bytes:
            raise ParseFailure("PARSER_OUTPUT_LIMIT")
    if original_count is None:
        raise ParseFailure(records[0]["error_code"] if records else "PARSER_FAILED")
    (work / "source.json").write_bytes(_json({"number of pages": original_count, "kids": kids}))
    (work / "auxiliary.json").write_bytes(_json({"kids": auxiliary}))
    (work / "geometry.json").write_bytes(_json(geometry))
    (work / "source.md").write_text("\n".join(markdown))
    if profile.table_structure_repair is not None:
        (work / "source-repaired.json").write_bytes(
            _json({"number of pages": original_count, "kids": repaired_kids})
        )
        (work / "table-repair.json").write_bytes(
            _json(dict(version=profile.table_structure_repair, batches=repairs))
        )
    (work / "h6-local.json").write_bytes(
        _json(
            dict(
                policy=POLICY,
                source_sha256=sha256((work / "source.pdf").read_bytes()).hexdigest(),
                original_page_count=original_count,
                selected=selected,
                batches=records,
            )
        )
    )


def _prefix(raw, prefix):
    mapped = deepcopy(raw)
    stack = [mapped]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "id" in value:
                value["id"] = prefix + str(value["id"])
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return mapped


def validate(receipt, values, artifacts, source, selected):
    """Reconstruct the merged raw candidates from their hash-checked batches."""
    if (
        receipt["policy"] != POLICY
        or receipt["source_sha256"] != source.sha256
        or receipt["selected"] != list(selected)
    ):
        raise ValueError("H6_LOCAL_IDENTITY_MISMATCH")
    covered, kids, auxiliary, geometry = [], [], [], {}
    for record in receipt["batches"]:
        pages = record["pages"]
        if not pages or any(type(p) is not int for p in pages):
            raise ValueError("H6_LOCAL_PAGE_MAPPING_INVALID")
        covered.extend(pages)
        if record["status"] == "unreadable":
            if record["error_code"] not in FAILURES | {"PARSER_TIMEOUT"}:
                raise ValueError("H6_LOCAL_FAILURE_INVALID")
            continue
        if record["status"] != "parsed" or any(
            artifacts.get(name) != digest for name, digest in record["artifacts"].items()
        ):
            raise ValueError("H6_LOCAL_ARTIFACT_MISMATCH")
        if record.get("auxiliary_failure") not in (None, "PARSER_NATIVE_TEXT_UNREADABLE"):
            raise ValueError("H6_LOCAL_FAILURE_INVALID")
        prefix = record["prefix"]
        raw = values[prefix + "source.json"]
        if raw["number of pages"] != receipt["original_page_count"]:
            raise ValueError("H6_LOCAL_PAGE_COUNT_INVALID")
        info = values[prefix + "geometry.json"]
        if set(info) != set(map(str, pages)):
            raise ValueError("H6_LOCAL_GEOMETRY_INVALID")
        geometry.update(info)
        kids.extend(_prefix(raw, prefix)["kids"])
        auxiliary.extend(_prefix(values[prefix + "auxiliary.json"], prefix)["kids"])
    if sorted(covered) != list(selected) or len(covered) != len(set(covered)):
        raise ValueError("H6_LOCAL_PAGE_MAPPING_INVALID")
    if (
        canonical_hash(values["source.json"])
        != canonical_hash({"number of pages": receipt["original_page_count"], "kids": kids})
        or values["auxiliary.json"] != {"kids": auxiliary}
        or values["geometry.json"] != geometry
    ):
        raise ValueError("H6_LOCAL_MERGE_MISMATCH")


def failures(receipt):
    return [
        dict(pages=b["pages"], error_code=b["error_code"])
        for b in receipt["batches"]
        if b["status"] == "unreadable"
    ] + [
        dict(pages=b["pages"], error_code=b["auxiliary_failure"])
        for b in receipt["batches"]
        if b.get("auxiliary_failure")
    ]
