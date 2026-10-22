"""ODL/pdfplumber candidate coordinates, identities and quality issues."""

from __future__ import annotations

import math
from dataclasses import replace
from importlib.metadata import version
from typing import Any
from uuid import UUID, uuid5

from proofops.adapters.parsing.odl_parts.common import ParseFailure
from proofops.application.ingest.geometry import affine_apply, invert_affine
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CandidateBlock,
    CandidateEdge,
    ParserProfile,
    QualityIssue,
    SourceArtifact,
)
from proofops.domain.documents import (
    NativeSource,
    PageGeometry,
    _compose_affine,
    _require_finite_bbox,
)
from proofops.domain.errors import DomainValidationError


def _transform_box(box, matrix):
    if box is None:
        return None
    if (
        not isinstance(box, list | tuple)
        or len(box) != 4
        or any(
            isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x)
            for x in box
        )
        or box[0] >= box[2]
        or box[1] >= box[3]
    ):
        raise ParseFailure("PARSER_GEOMETRY_INVALID")
    points = [affine_apply(matrix, x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _geometry(value: dict) -> PageGeometry:
    return PageGeometry(
        value["width_pt"], value["height_pt"], value["rotation"], tuple(value["crop_box"])
    )


def _node_text(node: dict, depth=0) -> str:
    if depth > 100:
        raise ParseFailure("PARSER_OUTPUT_LIMIT")
    if "content" in node:
        if not isinstance(node["content"], str):
            raise ParseFailure("PARSER_SCHEMA_INVALID")
        return node["content"]
    key = "rows" if "rows" in node else "cells" if "cells" in node else "kids"
    children = node.get(key, [])
    if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
        raise ParseFailure("PARSER_SCHEMA_INVALID")
    return ("\t" if key == "cells" else "\n").join(
        _node_text(child, depth + 1) for child in children
    )


def _batch(
    raw: dict,
    geometries: dict,
    source: SourceArtifact,
    profile: ParserProfile,
    config_hash: str,
    *,
    auxiliary=False,
    run_id: str,
) -> CandidateBatch:
    blocks: list[CandidateBlock] = []
    edges: list[CandidateEdge] = []
    if not isinstance(raw.get("kids"), list):
        raise ParseFailure("PARSER_SCHEMA_INVALID")
    partial_blocks = profile.failure_policy in {
        "partial-v4",
        "partial-v5",
        "partial-v6",
        "s3_partial-v7",
    }
    occurrences: dict[str, int] = {}
    stack: list[tuple[dict[str, Any], str | None, int | None, str | None, int, bool]] = [
        (node, None, None, None, 0, False) for node in reversed(raw["kids"])
    ]
    while stack:
        node, parent, inherited_page, table_id, depth, geometry_hold = stack.pop()
        if not isinstance(node, dict) or depth > 100 or len(blocks) >= 100000:
            raise ParseFailure("PARSER_OUTPUT_LIMIT")
        native_id = str(node["id"])
        page = node.get("page number", inherited_page)
        if type(page) is not int or str(page) not in geometries:
            raise ParseFailure("PARSER_PAGE_MAPPING_INVALID")
        if partial_blocks:
            # ODL reuses IDs on different pages within the same JVM output.
            # Qualify each occurrence before constructing parent/table edges.
            key = f"hx4-p{page}-{native_id}"
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            native_id = f"{key}-n{occurrence}"
        info = geometries[str(page)]
        geometry = _geometry(info["crop"])
        kind = {
            "table row": "table_row",
            "table cell": "table_cell",
            "image": "figure",
            "list item": "paragraph",
        }.get(node["type"], node["type"])
        if kind not in (
            "paragraph",
            "heading",
            "table",
            "table_row",
            "table_cell",
            "caption",
            "footnote",
            "figure",
            "unknown",
        ):
            kind = "unknown"
        if kind == "table":
            table_id = native_id
        raw_bbox = node.get("bounding box")
        if auxiliary:
            media = _geometry(info["media"])
            origin = node["page origin"]
            shift = (1.0, 0.0, 0.0, 1.0, -origin[0], -origin[1])
            to_native = _compose_affine(invert_affine(media.to_canonical_affine()), shift)
            to_canonical = _compose_affine(geometry.to_canonical_affine(), to_native)
            coordinate_system = "pdfplumber_top_left_media_points"
        else:
            # Actual OD 2.5.7 output is already rotation/CropBox-relative bottom-left.
            to_canonical = (1.0, 0.0, 0.0, -1.0, 0.0, geometry.height_pt)
            to_native = _compose_affine(invert_affine(geometry.to_canonical_affine()), to_canonical)
            coordinate_system = "opendataloader_display_bottom_left_points"
        try:
            native_bbox = _transform_box(raw_bbox, to_native)
            if native_bbox is not None:
                _require_finite_bbox("native_bbox", native_bbox)
        except (ParseFailure, DomainValidationError) as error:
            if not partial_blocks or (
                isinstance(error, ParseFailure) and str(error) != "PARSER_GEOMETRY_INVALID"
            ):
                raise
            geometry_hold = True
        if geometry_hold:
            # Raw JSON retains the rejected coordinates. An unknown, unlocated
            # candidate cannot be admitted as prose or borrowed as a table owner.
            native_bbox, raw_bbox, kind = None, None, "unknown"
        text = _node_text(node)
        native = NativeSource(
            source.document_version_id,
            profile.parse_manifest_id,
            run_id,
            native_id,
            page,
            info.get("printed_page_label"),
            native_bbox,
            "pdf_bottom_left_points",
            text,
            0,
            len(text),
        )
        context = tuple(
            f"{key}={node[key]}" for key in ("row number", "column number") if key in node
        )
        if geometry_hold:
            context += ("hx4_geometry_invalid=true",)
        blocks.append(
            CandidateBlock(
                kind,
                native,
                geometry,
                context,
                tuple(raw_bbox) if raw_bbox is not None else None,
                coordinate_system,
                to_canonical,
                table_id,
                node.get("row number"),
                node.get("column number"),
                node.get("row span"),
                node.get("column span"),
            )
        )
        if parent is not None:
            edges.append(
                CandidateEdge(native_id, parent, "table_parent" if table_id else "section_parent")
            )
        # OD uses a separate key for list children, including misclassified prose continuations.
        children = [
            child for key in ("kids", "rows", "cells", "list items") for child in node.get(key, [])
        ]
        for child in reversed(children):
            stack.append((child, native_id, page, table_id, depth + 1, geometry_hold))
    name = "pdfplumber" if auxiliary else "opendataloader"
    return CandidateBatch(
        source.tenant_id,
        source.document_version_id,
        profile.parse_manifest_id,
        source.sha256,
        run_id,
        name,
        version("pdfplumber" if auxiliary else "opendataloader-pdf"),
        "pdfminer" if auxiliary else "opendataloader",
        config_hash,
        tuple(blocks),
        tuple(edges),
        synthetic=False,
    )


def _with_quality_issues(graph, selected, profile, vision_pages=()):
    issues = list(graph.issues)
    for page in selected:
        if not any(
            block.page_num == page
            and any(s.raw_text for s in block.sources)
            and (page not in vision_pages or block.bbox is not None)
            for block in graph.blocks
        ):
            issues.append(
                QualityIssue(
                    str(uuid5(UUID(profile.parse_manifest_id), f"unreadable:{page}")),
                    "no_extractable_text",
                    page,
                    (),
                    "unreadable",
                    "No text extracted; absence of evidence is not established.",
                )
            )
    for block in graph.blocks:
        if any("hx4_geometry_invalid=true" in c.context for c in block.candidates):
            issues.append(
                QualityIssue(
                    str(uuid5(UUID(block.source_id), "hx4-geometry-invalid")),
                    "source_geometry_invalid",
                    block.page_num,
                    (block.source_id,),
                    "unreadable",
                    "Invalid parser coordinates retained in raw artifacts; source unresolved.",
                )
            )
        if (
            block.kind == "table"
            and block.page_num not in vision_pages
            and (
                profile.parser_mode == "local"
                or any("mixed_parser_name=opendataloader" in c.context for c in block.candidates)
            )
        ):
            issues.append(
                QualityIssue(
                    str(uuid5(UUID(block.source_id), "vision-not-run")),
                    "table_vision_not_run",
                    block.page_num,
                    (block.source_id,),
                    "open",
                    "Vision cross-check not_run: approved runtime/account required.",
                )
            )
    return replace(graph, issues=tuple(issues))
