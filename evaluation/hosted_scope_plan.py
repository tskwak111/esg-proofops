"""Disk-backed scope proposals in the hosted child; never an evidence reader.

Reuse AS1 selection/hash validation. PDFium previews are a distinct inspection
method, do not repair original conflicts, and never produce verified SourceRefs.
"""

from __future__ import annotations

import ctypes
import math
import re
import signal
from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path
from statistics import median

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from proofops.domain.provenance import canonical_hash

from evaluation.report_scope import _ceo_title, build_plan
from evaluation.report_sections import build_map, role


def failed_plan(source_sha256, page_count, reason):
    study = build_map(page_count, [])
    study.update(
        source_path="original.pdf",
        source_sha256=source_sha256,
        page_count=page_count,
        method="hosted_scope_unreadable",
        issues=[dict(kind="scope_inspection_failed", error_code=reason)],
    )
    plan = build_plan(study, {})
    plan["failure_reasons"] = [reason]
    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def _timeout(signum, frame):
    raise TimeoutError("scope page deadline")


def _page_text(document, index):
    page = document[index]
    try:
        textpage = page.get_textpage()
        try:
            count = textpage.count_chars()
            if count > 100_000:
                raise ValueError("scope page character cap")
            text = textpage.get_text_range()
            # Font runs use PDFium's own character indices, never Python text offsets.
            sizes = []
            matrix = raw.FS_MATRIX()
            for i in range(count):
                size = raw.FPDFText_GetFontSize(textpage, i)
                if raw.FPDFText_GetMatrix(textpage, i, ctypes.byref(matrix)):
                    size *= math.hypot(matrix.c, matrix.d)
                sizes.append(round(size, 2))
            runs, start = [], 0
            for end in range(1, count + 1):
                if end == count or sizes[end] != sizes[start]:
                    size = sizes[start]
                    if math.isfinite(size) and size > 0:
                        runs.append((size, textpage.get_text_range(start, end - start).strip()))
                    start = end
            body_size = median(s for s in sizes if s > 0) if sizes else 0
            headings = list(
                dict.fromkeys(
                    t.strip()
                    for size, value in runs
                    for t in value.splitlines()
                    if 0 < len(t.strip()) <= 100
                    and size >= (12 if _ceo_title(t) else max(12, body_size * 1.15))
                )
            )
            main_size = max((s for s, t in runs if re.search(r"[a-zA-Z가-힣]", t)), default=0)
            primary = list(
                dict.fromkeys(
                    t.strip()
                    for size, value in runs
                    for t in value.splitlines()
                    if t.strip() in headings and size >= max(12, main_size * 0.75)
                )
            )
            return text, headings, primary
        finally:
            textpage.close()
    finally:
        page.close()  # Free page/XObject/text caches before loading the next page.


def inspect_streaming(pdf: Path, *, source_sha256: str | None = None):
    if pdf.stat().st_size > 150 * 1024 * 1024:
        raise ValueError("hosted scope limit: 150 MiB")
    with pdf.open("rb") as stream:
        input_digest = file_digest(stream, "sha256").hexdigest()
    # HostedStore has verified the derivative against the immutable original.
    digest = source_sha256 or input_digest
    texts, headings, primary, anchors, issues = {}, {}, {}, [], []
    with pdfium.PdfDocument(pdf) as document:
        count = len(document)
        if not 1 <= count <= 300:
            raise ValueError("hosted scope limit: 300 pages")
        parents = {}
        for bookmark in document.get_toc(max_depth=20):
            title = bookmark.get_title()
            parents[bookmark.level] = title
            destination = bookmark.get_dest()
            index = destination.get_index() if destination else None
            if index is None or not 0 <= index < count:
                issues.append(dict(kind="unresolved_destination", title=title))
                continue
            anchors.append(
                dict(
                    page=index + 1,
                    title=title,
                    path=[parents[level] for level in sorted(parents) if level <= bookmark.level],
                    method="outline",
                )
            )
        meaningful_navigation = any(role(a["path"]) != "unknown" for a in anchors)
        prior_handler = signal.signal(signal.SIGALRM, _timeout)
        try:
            for index in range(count):
                signal.setitimer(signal.ITIMER_REAL, 2)
                try:
                    text, titles, main = _page_text(document, index)
                    texts[index + 1], headings[index + 1], primary[index + 1] = text, titles, main
                    if not meaningful_navigation:
                        anchors.extend(
                            dict(page=index + 1, title=t, path=[t], method="pdfium_heading")
                            for t in main
                            if role([t]) != "unknown"
                        )
                except Exception as error:
                    texts[index + 1] = ""
                    issues.append(
                        dict(
                            kind="native_text_unreadable",
                            page=index + 1,
                            error_type=type(error).__name__,
                        )
                    )
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
        finally:
            signal.signal(signal.SIGALRM, prior_handler)
    with pdf.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != input_digest:
            raise ValueError("source changed during scope inspection")
    study = build_map(count, anchors)
    study.update(
        source_path="original.pdf",
        source_sha256=digest,
        page_count=count,
        method="hosted_pdfium_streaming_v1",
        issues=issues,
        parser_versions={"pypdfium2": version("pypdfium2")},
    )
    plan = build_plan(study, texts, page_headings=headings, page_primary_headings=primary)
    from evaluation.reporting_period import detect_reporting_period

    plan["reporting_period_detection"] = detect_reporting_period(texts, count, digest)
    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan
