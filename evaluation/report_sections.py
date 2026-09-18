"""Offline, source-bound section candidates; never approves scope or evidence.

Run: uv run python -m evaluation.report_sections --pdf PATH --output NEW_JSON
No network calls. Printed page numbers are never treated as physical destinations.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote

import pdfplumber
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader

PATTERNS = {
    "esg_data": (
        r"esg\s*(data|fact\s*(?:book|sheet))|fact\s*book|facts\s*(?:&|and)\s*figures|"
        r"데이터북|esg\s*데이터|성과\s*데이터|지속가능경영\s*data"
    ),
    "appendix": r"appendi[xc]|부록|(?:gri|sasb|kssb).*index|assurance|검증의견서|glossary|용어집",
    "e_narrative": (
        r"environment(?:al)?|\bplanet\b|\bclimate\b|\bcarbon\b|"
        r"환경|기후|탄소|순환경제|자연자본|생물다양성|tcfd|"
        r"온실가스|에너지|ghg|greenhouse|자원순환|폐기물|\bcircular\b|\brecycling\b"
    ),
    "other": (
        r"social|governance|overview|introduction|our\s*company|\bpeople\b|\bprinciple\b|"
        r"esg\s*approach|사회|지배구조|회사\s*소개"
    ),
}
POLICY_HASH = canonical_hash(
    {
        "version": 9,
        "unknown_fallback": "unmatched_heading_does_not_override_classified_outline_or_toc",
        "patterns": PATTERNS,
        "heading_min_size": 24,
        "font_tolerance": 0.2,
        "max_heading_chars": 100,
        "max_pdf_bytes": 100 * 1024 * 1024,
        "max_pages": 500,
        "preview_chars": 1200,
        "toc_scan_pages": 8,
        "toc_supplement": "scattered_E_with_bounded_evidence_containers_v1",
        "toc_text_readers": ["pdfplumber", "pypdf"],
        "toc_word_min_size": 16,
        "toc_marker": r"(?im)^\s*(?:목차|contents|table of contents|index)\s*$",
    }
)


def role(path):
    # Evidence containers take precedence over their environmental/social children.
    for kind in ("esg_data", "appendix"):
        if any(re.search(PATTERNS[kind], t, re.I) for t in path):
            return kind
    for title in reversed(path):
        matches = [k for k in ("e_narrative", "other") if re.search(PATTERNS[k], title, re.I)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return "unknown"
    return "unknown"


def build_map(page_count, anchors):
    if type(page_count) is not int or page_count < 1:
        raise ValueError("invalid page count")
    grouped = {}
    for anchor in anchors:
        page = anchor["page"]
        if type(page) is not int or not 1 <= page <= page_count:
            raise ValueError("invalid physical destination")
        if not anchor["path"] or not all(isinstance(t, str) for t in anchor["path"]):
            raise ValueError("invalid section path")
        grouped.setdefault(page, []).append(anchor)
    starts = sorted({1, *grouped})
    sections, claims, evidence, unknown, conflicts, other = [], [], [], [], [], []
    for index, start in enumerate(starts):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else page_count
        sources = grouped.get(start, [])
        explicit = any(
            a.get("method") in ("outline", "toc_links") and role(a["path"]) != "unknown"
            for a in sources
        )
        roles = {
            role(a["path"])
            for a in sources
            if not (
                explicit
                and a.get("method") == "large_heading_fallback"
                and role(a["path"]) == "unknown"
                and not any(
                    re.search(pattern, title, re.I)
                    for pattern in PATTERNS.values()
                    for title in a["path"]
                )
            )
        } or {"unknown"}
        kind = next(iter(roles)) if len(roles) == 1 else "conflict"
        pages = list(range(start, end + 1))
        if kind == "e_narrative":
            claims.extend(pages)
        if kind in ("e_narrative", "esg_data", "appendix"):
            evidence.extend(pages)
        if kind == "unknown":
            unknown.extend(pages)
        if kind == "conflict":
            conflicts.extend(pages)
        if kind == "other":
            other.extend(pages)
        sections.append(dict(start_page=start, end_page=end, role=kind, anchors=sources))
    return dict(
        status="candidate_only",
        sections=sections,
        claim_candidate_pages=claims,
        evidence_candidate_pages=evidence,
        unknown_pages=unknown,
        conflict_pages=conflicts,
        other_candidate_pages=other,
        source_quality="unverified",
    )


def toc_links(pdf, reader, issues):
    """Read labels inside internal link rectangles on explicit front-matter TOCs."""
    anchors = []
    destinations = reader.named_destinations
    page_refs = {
        (p.indirect_reference.idnum, p.indirect_reference.generation): i
        for i, p in enumerate(reader.pages)
        if p.indirect_reference is not None
    }
    with pdfplumber.open(pdf) as document:
        for number, page in enumerate(document.pages[:8], 1):
            text = page.extract_text() or ""
            # Rotated markers and multi-column TOCs have different reading order by parser.
            native_text = reader.pages[number - 1].extract_text() or ""
            marker = any(
                re.search(r"(?im)^\s*(?:목차|contents|table of contents|index)\s*$", value)
                for value in (text, native_text)
            ) or any(
                word["text"].casefold() in {"contents", "목차"} and word["size"] >= 16
                for word in page.extract_words(extra_attrs=["size"])
            )
            if not marker:
                page.close()
                continue
            # ponytail: rotated/non-origin pages need existing affine geometry support first.
            if page.rotation or tuple(page.bbox[:2]) != (0, 0):
                issues.append(dict(kind="toc_geometry_unsupported", page=number))
                page.close()
                continue
            annotations = reader.pages[number - 1].get("/Annots", [])
            if hasattr(annotations, "get_object"):
                annotations = annotations.get_object()
            for reference in annotations:
                item = reference.get_object()
                action = item.get("/A", {})
                action = action.get_object() if hasattr(action, "get_object") else action
                if item.get("/Subtype") != "/Link" or action.get("/S") not in (None, "/GoTo"):
                    continue  # Never follow external links or execute PDF actions.
                destination = item.get("/Dest", action.get("/D"))
                if hasattr(destination, "get_object"):
                    destination = destination.get_object()
                try:
                    if isinstance(destination, str) and destination in destinations:
                        target = reader.get_destination_page_number(destinations[destination])
                        destination_ref = destination
                    elif isinstance(destination, list) and len(destination) >= 2:
                        ref = destination[0]
                        target = page_refs.get(
                            (getattr(ref, "idnum", None), getattr(ref, "generation", None))
                        )
                        destination_ref = dict(
                            object_id=getattr(ref, "idnum", None),
                            generation=getattr(ref, "generation", None),
                        )
                    else:
                        raise ValueError("unresolved internal link")
                    if target is None or not 0 <= target < len(reader.pages):
                        raise ValueError("invalid destination")
                    x0, y0, x1, y1 = map(float, item["/Rect"])
                    box = (
                        min(x0, x1),
                        page.height - max(y0, y1),
                        max(x0, x1),
                        page.height - min(y0, y1),
                    )
                    if not all(math.isfinite(v) for v in box) or not (
                        0 <= box[0] < box[2] <= page.width and 0 <= box[1] < box[3] <= page.height
                    ):
                        raise ValueError("invalid link rectangle")
                    # Centers avoid clipped fragments from neighboring rows in crop extraction.
                    title = "".join(
                        c["text"]
                        for c in page.chars
                        if box[0] <= (c["x0"] + c["x1"]) / 2 <= box[2]
                        and box[1] <= (c["top"] + c["bottom"]) / 2 <= box[3]
                    ).strip()
                    if not title:
                        issues.append(
                            dict(
                                kind="unlabeled_toc_link", page=number, destination_page=target + 1
                            )
                        )
                        continue
                    anchors.append(
                        dict(
                            page=target + 1,
                            title=title,
                            path=[title],
                            method="toc_links",
                            toc_page=number,
                            destination=destination_ref,
                            native_bbox=list(box),
                            coordinate_system="pdfplumber_top_left_points",
                        )
                    )
                except (ValueError, KeyError, TypeError):
                    issues.append(dict(kind="unresolved_toc_link", page=number))
            page.close()
    return anchors


def inspect(pdf: Path):
    # Existing ingest gates still own production acceptance; this is a bounded local study.
    if pdf.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("local section study limit: 100 MiB")
    with pdf.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    reader = PdfReader(pdf)
    if reader.is_encrypted:
        raise ValueError("encrypted input requires the existing ingest gate")
    count = len(reader.pages)
    if not 1 <= count <= 500:
        raise ValueError("local section study limit: 500 pages")
    anchors, issues = [], []

    def outline(items, parents=()):
        previous = parents
        for item in items:
            if isinstance(item, list):
                outline(item, previous)
                continue
            title = item.title
            previous = (*parents, title)
            page = reader.get_destination_page_number(item)
            if page is None or not 0 <= page < count:
                issues.append(dict(kind="unresolved_destination", title=title))
                continue
            anchors.append(dict(page=page + 1, title=title, path=list(previous), method="outline"))

    outline(reader.outline)
    if not anchors:
        for raw_title, destination in reader.named_destinations.items():
            title = unquote(raw_title).lstrip("/")
            # Opaque InDesign IDs carry no section semantics; don't infer from trailing numbers.
            if ".indd" in title.casefold():
                continue
            page = reader.get_destination_page_number(destination)
            if page is None or not 0 <= page < count:
                issues.append(dict(kind="unresolved_destination", title=title))
                continue
            anchors.append(
                dict(page=page + 1, title=title, path=title.split("_"), method="named_destination")
            )
    method = "pdf_navigation"
    if not any(role(a["path"]) != "unknown" for a in anchors):
        anchors = []
        method = "large_heading_fallback"
        # ponytail: explicit large chapter headings only; dispersed/small headings stay unknown.
        # Add TOC-link geometry resolution when this measured coverage ceiling matters.
        with pdfplumber.open(pdf) as document:
            for number, pdf_page in enumerate(document.pages, 1):
                chars = pdf_page.chars
                largest = max((c["size"] for c in chars), default=0)
                title = "".join(c["text"] for c in chars if c["size"] >= largest - 0.2).strip()
                if largest >= 24 and re.search(r"[a-zA-Z가-힣]", title) and len(title) <= 100:
                    anchors.append(
                        dict(
                            page=number,
                            title=title,
                            path=[title],
                            method=method,
                            coordinate_system="pdfplumber_top_left_points",
                            page_bbox=list(pdf_page.bbox),
                            rotation=pdf_page.rotation,
                            native_bboxes=[
                                [c["x0"], c["top"], c["x1"], c["bottom"]]
                                for c in chars
                                if c["size"] >= largest - 0.2
                            ],
                        )
                    )
                pdf_page.close()
    roles = {role(a["path"]) for a in anchors}
    linked = toc_links(pdf, reader, issues)
    if linked:
        # Use bounded known container intervals, not a document-wide cutoff:
        # some reports place a data chapter before another narrative chapter.
        containers = [a for a in linked if role(a["path"]) in ("esg_data", "appendix")]
        evidence_ranges = [
            (section["start_page"], section["end_page"])
            for section in build_map(count, anchors + containers)["sections"]
            if section["role"] in ("esg_data", "appendix")
        ]
        filtered = []
        anchored_pages_roles: dict[int, set[str]] = {}
        for a in anchors:
            anchored_pages_roles.setdefault(a["page"], set()).add(role(a["path"]))
        for a in linked:
            r = role(a["path"])
            # Hierarchy guard: flat TOC children inside Appendix/DataBook stay evidence-only.
            if any(start <= a["page"] <= end for start, end in evidence_ranges) and r not in (
                "esg_data",
                "appendix",
            ):
                continue
            # Preserve existing valid outline: flat unknown truncated titles at same page
            if a["page"] in anchored_pages_roles and r == "unknown":
                if r not in anchored_pages_roles[a["page"]]:
                    issues.append(
                        dict(
                            kind="unclassified_duplicate_toc_boundary",
                            page=a["toc_page"],
                            destination_page=a["page"],
                        )
                    )
                    continue
            filtered.append(a)
        anchored_pages = {a["page"] for a in anchors}
        filtered_roles = {role(a["path"]) for a in filtered}
        filtered_e_pages = {a["page"] for a in filtered if role(a["path"]) == "e_narrative"}
        new_e_pages = filtered_e_pages - anchored_pages
        gains = filtered_roles - roles
        if (gains & {"e_narrative", "esg_data", "appendix"}) or new_e_pages:
            # Preserve existing boundaries too: disagreements become explicit conflicts.
            anchors, method = anchors + filtered, "toc_links"
    result = build_map(count, anchors)
    # Destination-page previews permit review; they are not canonical SourceRefs.
    for section in result["sections"]:
        for anchor in section["anchors"]:
            try:
                text = reader.pages[anchor["page"] - 1].extract_text() or ""
                anchor["destination_preview"] = text[:1200]
                anchor["destination_text_sha256"] = canonical_hash(text)
            except Exception as error:
                issues.append(
                    dict(
                        kind="unreadable_destination",
                        page=anchor["page"],
                        error_type=type(error).__name__,
                    )
                )
    with pdf.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("source changed during section inspection")
    result.update(
        source_path=str(pdf.resolve()),
        source_sha256=digest,
        page_count=count,
        policy_sha256=POLICY_HASH,
        parser_versions={name: version(name) for name in ("pypdf", "pdfplumber")},
        method=method,
        issues=issues,
        coverage="unvalidated",
        live_model="not_run",
        table_figure_validation="not_run",
        limitations=[
            "Ranges end before the next detected anchor; undetected boundaries may overextend.",
            "Unknown/conflict pages need scope review; they are never evidence absence.",
            "Candidate map is not wired into full discovery or production evidence filtering.",
            "Tables and figures inside any selected section still require separate parsing checks.",
        ],
    )
    # Hash all fields except map_sha256 itself; consumers remove that field before verification.
    result["map_sha256"] = canonical_hash(result)
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    result = inspect(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "page_count",
                    "method",
                    "claim_candidate_pages",
                    "unknown_pages",
                    "conflict_pages",
                )
            }
        )
    )
