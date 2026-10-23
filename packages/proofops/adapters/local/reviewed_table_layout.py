"""Reviewed layout validation, ink geometry and unverified graph construction."""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from functools import lru_cache
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from proofops.adapters.local.native_glyph_geometry import native_word_ink_geometry
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CandidateBlock,
    CandidateEdge,
    CanonicalDocumentGraph,
    fuse_candidates,
)
from proofops.application.ingest.normalize import (
    NormalizationResult,
    Observation,
    normalize_table_bindings,
)
from proofops.domain.documents import NativeSource, PageGeometry
from proofops.domain.provenance import canonical_hash

_SCHEMA = "reviewed_table_bridge_v1"
# Identity of the numeric-input view below. It adds no verification of its own:
# every promotion decision is read back out of the existing native receipt and
# the existing citation verifier.
_NUMERIC_INPUT_SCHEMA = "reviewed_table_numeric_input_v1"
# Canonical cell boxes now come from real glyph ink, so this bridge no longer
# produces the same parse as the R02h v1 artifacts. The parse manifest, parser run
# and config hash carry that rule identity; the raw PDF document version does not
# change, because the source did not.
_GEOMETRY_SCHEMA = "reviewed_table_native_ink_geometry_v2"
# Identity rule of a snapshot that carries more than one reviewed grid of the same
# original bytes. It is deliberately not either grid's own manifest key.
_COMBINED_SCHEMA = "reviewed_table_combined_snapshot_v1"
_TENANT = str(uuid5(NAMESPACE_URL, "proofops:reviewed-table:evaluation-tenant"))
# A reviewed word box and the reader's own word box must still be the same word.
_LINEAGE_TOL = 0.01


def _id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"proofops:reviewed-table:{name}"))


def _native_bbox(box: list[float], height: float) -> tuple[float, float, float, float]:
    x0, top, x1, bottom = box
    return (float(x0), height - float(bottom), float(x1), height - float(top))


def _require_review(review: dict[str, Any], source: bytes) -> None:
    if not isinstance(review, dict) or review.get("status") != "candidate_only":
        raise ValueError("candidate-only reviewed layout required")
    if sha256(source).hexdigest() != review.get("source_sha256"):
        raise ValueError("reviewed layout source mismatch")
    if review.get("coordinate_system") != "pdf_top_left_points":
        raise ValueError("unsupported reviewed layout coordinate system")
    if (
        review.get("native_verification") != "not_run"
        or review.get("semantic_verification") != "not_run"
    ):
        raise ValueError("review artifact must not claim verification")
    if not isinstance(review.get("physical_page"), int) or review["physical_page"] < 1:
        raise ValueError("reviewed physical page required")
    if not isinstance(review.get("page_bbox"), list) or len(review["page_bbox"]) != 4:
        raise ValueError("reviewed page bbox required")
    if not isinstance(review.get("cells"), dict) or not review["cells"]:
        raise ValueError("reviewed cells required")
    if not isinstance(review.get("candidates"), list) or not review["candidates"]:
        raise ValueError("reviewed numeric candidates required")


# Caller-reviewed passages outside the table grid (footnotes, coverage notes, ...).
# ``notes``/``row_labels`` on a candidate bind an *in-table* cell key; this is the
# separate, table-level set of reviewed passages that are not any cell at all, so
# they can never be bound by that per-candidate mechanism. Nothing here promotes,
# reads or reinterprets the passage: it only carries the caller's own review
# forward instead of dropping it, and reports it as unresolved.
_EXTERNAL_CONTEXT_FIELDS = frozenset(
    {"kind", "raw_text", "bbox", "word_indices", "clipped_word_indices", "rotated_word_indices"}
)


def _external_review_context(review: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Validate and carry forward ``review["context"]`` byte-for-byte; never drop it.

    Each entry is a passage the caller already reviewed and pinned to real words,
    outside the table's own cells. A missing, wrong-typed or malformed entry is a
    caller-review defect and must stop the bridge rather than be silently filtered
    into an empty list, the same way a malformed candidate role already does.
    ``extraction_status`` is read back, not assumed: a clipped/rotated/unreadable
    passage stays exactly that, and only ``source_text_extracted`` can ever be
    treated as source-bound text below.
    """
    raw = review.get("context", [])
    if not isinstance(raw, list):
        raise ValueError("reviewed external context must be a list")
    words = {
        word["index"]
        for word in review.get("words") or ()
        if isinstance(word, dict) and isinstance(word.get("index"), int)
    }
    entries = []
    for entry in raw:
        if not isinstance(entry, dict) or not _EXTERNAL_CONTEXT_FIELDS <= set(entry):
            raise ValueError("reviewed external context entry malformed")
        if not isinstance(entry.get("kind"), str) or not entry["kind"]:
            raise ValueError("reviewed external context kind required")
        if not isinstance(entry.get("raw_text"), str) or not entry["raw_text"]:
            raise ValueError("reviewed external context raw_text required")
        if not isinstance(entry.get("bbox"), list) or len(entry["bbox"]) != 4:
            raise ValueError("reviewed external context bbox required")
        indices = entry.get("word_indices")
        if (
            not isinstance(indices, list)
            or not indices
            or any(type(index) is not int or index < 0 for index in indices)
        ):
            raise ValueError("reviewed external context word_indices required")
        for optional in ("clipped_word_indices", "rotated_word_indices"):
            if not isinstance(entry.get(optional), list) or any(
                type(index) is not int for index in entry[optional]
            ):
                raise ValueError(f"reviewed external context {optional} invalid")
        status = entry.get("extraction_status")
        if not isinstance(status, str) or not status:
            raise ValueError("reviewed external context extraction_status required")
        readable = (
            status == "source_text_extracted"
            and not entry["clipped_word_indices"]
            and not entry["rotated_word_indices"]
            and set(indices) <= words
        )
        entries.append(
            {
                "kind": entry["kind"],
                "raw_text": entry["raw_text"],
                "bbox": [float(v) for v in entry["bbox"]],
                "word_indices": list(indices),
                "clipped_word_indices": list(entry["clipped_word_indices"]),
                "rotated_word_indices": list(entry["rotated_word_indices"]),
                "extraction_status": status,
                # This module only ever reads the caller's own review-declared
                # lineage back; it never re-derives or verifies it against the
                # source itself. "readable" therefore means "the review declares
                # this passage as clean source-bound text", not "natively proven".
                "review_lineage_complete": readable,
                "source_verification": "not_run",
                "association_status": "unknown",
            }
        )
    return tuple(entries)


def _union(boxes: Sequence[Sequence[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _overlaps(inner: Sequence[float], outer: Sequence[float]) -> bool:
    horizontal = min(inner[2], outer[2]) > max(inner[0], outer[0])
    vertical = min(inner[3], outer[3]) > max(inner[1], outer[1])
    return horizontal and vertical


@lru_cache(maxsize=4)
def _page_word_ink(
    source: bytes,
    page_number: int,
    pinned: tuple[int, ...],
    lineage: tuple[tuple[int, str, tuple[float, ...]], ...],
) -> tuple[tuple[tuple[int, tuple[float, ...]], ...], tuple[tuple[str, object], ...]]:
    """Reader words and their real glyph ink for one page, or a recorded refusal.

    A reviewed rectangle is drawn on the extractor's *word* boxes.  Those boxes
    are font metric boxes, not ink: on ``lotte.pdf`` page 117 every one of the
    111 pinned words inks about 6pt above its reported box (measured median
    5.957pt, range 3.290-9.751pt), so a reviewed row rectangle contains its own
    glyphs nowhere and the native verifier's promoted-crop check refuses it.
    Resolving the ink of the *same pinned words* corrects only the rectangle.
    Membership, text, grid indices and spans are never touched here, and a word
    the review did not pin is never pulled in.
    """
    try:
        with pdfplumber.open(io.BytesIO(source)) as document:
            if not 1 <= page_number <= len(document.pages):
                return (), (("status", "operator_reviewed_region"), ("reason", "page_absent"))
            words = document.pages[page_number - 1].extract_words()
    except (PdfminerException, OSError, ValueError) as error:
        return (
            (),
            (
                ("status", "operator_reviewed_region"),
                ("reason", f"source_not_readable:{type(error).__name__}"),
            ),
        )
    # The correction is index-addressed, so every pinned index must carry its own
    # recorded identity exactly once. Missing or duplicated lineage would leave
    # the box of an unchecked word to be moved.
    covered = [index for index, _, _ in lineage]
    if sorted(covered) != sorted(pinned) or len(set(covered)) != len(covered):
        raise ValueError("reviewed word lineage incomplete")
    for index, text, box in lineage:
        if index >= len(words):
            raise ValueError("reviewed word lineage out of range")
        word = words[index]
        if word["text"] != text or any(
            abs(float(word[key]) - value) > _LINEAGE_TOL
            for key, value in zip(("x0", "top", "x1", "bottom"), box, strict=True)
        ):
            # A reader change that renumbers or moves words must stop the bridge,
            # not shift a box.
            raise ValueError("reviewed word lineage drifted")
    result = native_word_ink_geometry(source, page_number, list(pinned))
    unresolved = set(result.get("unresolved_word_indices") or ())
    ink = tuple(
        (int(match["native_word_index"]), tuple(float(v) for v in match["ink_bbox"]))
        for match in result.get("matched_words") or ()
        if int(match["native_word_index"]) not in unresolved and match.get("ink_bbox")
    )
    return ink, (
        ("status", "native_word_ink_union"),
        ("reader", result.get("reader")),
        ("reader_version", result.get("reader_version")),
        ("matcher_sha256", result.get("matcher_sha256")),
        ("proof_sha256", result.get("proof_sha256")),
        ("pinned_words", len(pinned)),
        ("resolved_word_ink", len(ink)),
    )


def _canonical_cell_boxes(
    review: dict[str, Any], source: bytes
) -> tuple[dict[str, list[float]], dict[str, dict[str, Any]], dict[str, Any]]:
    """Per-cell canonical box: the ink union of that cell's own pinned words.

    A cell whose pinned ink cannot be resolved, or whose ink union does not even
    overlap the reviewed rectangle, keeps the reviewed rectangle and records why.
    That fallback can only hold a cell back; it never admits one.
    """
    cells = review["cells"]
    pinned = set()
    for cell in cells.values():
        for index in cell.get("word_indices") or ():
            if type(index) is not int or index < 0:
                raise ValueError("reviewed cell word index invalid")
            pinned.add(index)
    lineage = tuple(
        (int(word["index"]), word["text"], tuple(float(v) for v in word["bbox"]))
        for word in review.get("words") or ()
        if isinstance(word, dict) and word.get("index") in pinned
    )
    pairs, diagnostics = _page_word_ink(
        source, review["physical_page"], tuple(sorted(pinned)), lineage
    )
    ink = dict(pairs)
    boxes: dict[str, list[float]] = {}
    detail: dict[str, dict[str, Any]] = {}
    for key, cell in cells.items():
        region = [float(v) for v in cell["bbox"]]
        cell_words = [int(i) for i in (cell.get("word_indices") or ())]
        resolved = [ink[i] for i in cell_words if i in ink]
        record = {"reviewed_region_bbox": region, "pinned_word_indices": cell_words}
        if not cell_words or len(resolved) != len(cell_words):
            boxes[key] = region
            detail[key] = {
                **record,
                "canonical_bbox_source": "operator_reviewed_region",
                "reason": "pinned_word_ink_unresolved",
            }
            continue
        box = _union(resolved)
        if box[0] >= box[2] or box[1] >= box[3] or not _overlaps(box, region):
            boxes[key] = region
            detail[key] = {
                **record,
                "canonical_bbox_source": "operator_reviewed_region",
                "reason": "pinned_word_ink_outside_reviewed_region",
            }
            continue
        boxes[key] = box
        detail[key] = {
            **record,
            "canonical_bbox_source": "native_word_ink_union",
            "reviewed_region_offset_pt": [round(box[i] - region[i], 4) for i in range(4)],
        }
    return boxes, detail, dict(diagnostics)


def reviewed_cell_geometry(review: dict[str, Any], source: bytes) -> dict[str, Any]:
    """Which canonical cell box came from real ink, and how far it moved."""
    _, detail, diagnostics = _canonical_cell_boxes(review, source)
    return {"cells": detail, "pinned_word_ink": diagnostics}


def graph_from_review(
    review: dict[str, Any],
    source: bytes,
    *,
    tenant_id: str = _TENANT,
    also: Sequence[dict[str, Any]] = (),
) -> tuple[CanonicalDocumentGraph, dict[str, str]]:
    """Make a one-review candidate graph with unverified cell quality only.

    ``also`` adds further reviewed grids of the *same original bytes* (another page,
    or another table of the same page) to one explicitly new combined snapshot. It
    exists so a value disclosed in two physically separate places can be read out of
    a single pinned snapshot instead of having one side's identity rewritten onto the
    other. Nothing is transplanted: every grid keeps its own physical page, its own
    reviewed rectangles, its own layout hash in the block context and its own cell
    keys, and the combined snapshot is its *own* parse manifest derived from the
    ordered layout hashes. With ``also`` empty the identity, cell native ids and
    returned mapping are byte-for-byte what they were, so existing artifacts still
    reproduce. Verified quality is never carried over: the combined snapshot starts
    entirely ``unverified`` and must be re-attested natively by the callers below.
    """
    reviews = (review, *tuple(also))
    for item in reviews:
        _require_review(item, source)
    source_sha256 = review["source_sha256"]
    layouts = []
    for item in reviews:
        layout_sha256 = item.get("layout_sha256")
        if not isinstance(layout_sha256, str) or len(layout_sha256) != 64:
            raise ValueError("reviewed layout hash required")
        if item["source_sha256"] != source_sha256:
            raise ValueError("combined reviewed layouts must share one source")
        layouts.append(layout_sha256)
    if len(set(layouts)) != len(layouts):
        raise ValueError("duplicate reviewed layout in combined snapshot")
    # A combined snapshot is a different parse rule from either grid alone, so it
    # gets its own manifest key. A single review keeps the existing key exactly.
    manifest_key = (
        layouts[0]
        if len(reviews) == 1
        else canonical_hash({"schema": _COMBINED_SCHEMA, "layout_sha256": layouts})
    )
    document_version_id = _id(f"document:{source_sha256}")
    parse_manifest_id = _id(f"manifest:{source_sha256}:{manifest_key}:{_GEOMETRY_SCHEMA}")
    parser_run_id = _id(f"review:{source_sha256}:{manifest_key}:{_GEOMETRY_SCHEMA}")
    config = {
        "schema": _SCHEMA,
        "geometry_schema": _GEOMETRY_SCHEMA,
        "layout_sha256": layouts[0],
        "tool_sha256": review.get("tool_sha256"),
        "reader_version": review.get("reader_version"),
    }
    if len(reviews) > 1:
        config["combined"] = [
            {
                "layout_sha256": layout,
                "physical_page": item["physical_page"],
                "tool_sha256": item.get("tool_sha256"),
                "reader_version": item.get("reader_version"),
            }
            for layout, item in zip(layouts, reviews, strict=True)
        ]
    config_hash = canonical_hash(config)

    def make_candidate(
        page: int, geometry: PageGeometry, layout_sha256: str
    ) -> Callable[..., CandidateBlock]:
        height = geometry.height_pt

        def candidate(
            native_id: str, kind: str, raw_text: str, box: list[float], **grid: Any
        ) -> CandidateBlock:
            native = _native_bbox(box, height)
            return CandidateBlock(
                kind,
                NativeSource(
                    document_version_id,
                    parse_manifest_id,
                    parser_run_id,
                    native_id,
                    page,
                    None,
                    native,
                    "pdf_bottom_left_points",
                    raw_text,
                    0,
                    len(raw_text),
                ),
                geometry,
                context=("operator_reviewed_layout", f"layout_sha256={layout_sha256}"),
                parser_bbox=native,
                parser_coordinate_system="pdf_bottom_left_points",
                parser_to_canonical=geometry.to_canonical_affine(),
                **grid,
            )

        return candidate

    blocks: list[CandidateBlock] = []
    edges: list[CandidateEdge] = []
    native_ids: dict[str, str] = {}
    for index, item in enumerate(reviews):
        prefix = "" if index == 0 else f"{index}:"
        page = item["physical_page"]
        x0, y0, x1, y1 = item["page_bbox"]
        if (x0, y0) != (0, 0) or not (isinstance(x1, int | float) and isinstance(y1, int | float)):
            raise ValueError("offset reviewed page geometry unsupported")
        width, height = float(x1), float(y1)
        geometry = PageGeometry(width, height, 0, (0, 0, width, height))
        candidate = make_candidate(page, geometry, layouts[index])
        cells = item["cells"]
        cell_items = sorted(
            cells.items(),
            key=lambda entry: (entry[1].get("row", -1), entry[1].get("column", -1), entry[0]),
        )
        if any(
            not isinstance(cell, dict) or not isinstance(cell.get("raw_text"), str)
            for _, cell in cell_items
        ):
            raise ValueError("reviewed raw cell text required")
        if any(
            not isinstance(cell.get("bbox"), list) or len(cell["bbox"]) != 4
            for _, cell in cell_items
        ):
            raise ValueError("reviewed cell bbox required")
        canonical_boxes, _, _ = _canonical_cell_boxes(item, source)
        table_box = _union([canonical_boxes[key] for key, _ in cell_items])
        table_text = "\n".join(cell["raw_text"] for _, cell in cell_items)
        table_native_id = f"{prefix}reviewed-table"
        blocks.append(candidate(table_native_id, "table", table_text, table_box))
        if len(reviews) > 1:
            native_ids[table_native_id] = table_native_id
        for key, cell in cell_items:
            if cell.get("extraction_status") != "source_text_extracted":
                raise ValueError(f"reviewed cell source boundary held: {key}")
            row, column = cell.get("row"), cell.get("column")
            row_span, column_span = cell.get("row_span", 1), cell.get("column_span", 1)
            if any(type(value) is not int or value < 0 for value in (row, column)) or any(
                type(value) is not int or value < 1 for value in (row_span, column_span)
            ):
                raise ValueError(f"reviewed cell grid invalid: {key}")
            native_id = f"reviewed-cell:{prefix}{key}"
            blocks.append(
                candidate(
                    native_id,
                    "table_cell",
                    cell["raw_text"],
                    canonical_boxes[key],
                    table_native_id=table_native_id,
                    row_number=row,
                    column_number=column,
                    row_span=row_span,
                    column_span=column_span,
                )
            )
            edges.append(CandidateEdge(native_id, table_native_id, "table_parent"))
            native_ids[f"{prefix}{key}"] = native_id
    batch = CandidateBatch(
        tenant_id=tenant_id,
        document_version_id=document_version_id,
        parse_manifest_id=parse_manifest_id,
        source_sha256=source_sha256,
        parser_run_id=parser_run_id,
        parser_name="operator_reviewed_table_layout",
        parser_version=_SCHEMA,
        parser_family="operator_reviewed_layout",
        config_hash=config_hash,
        blocks=tuple(blocks),
        edges=tuple(edges),
        synthetic=False,
    )
    return fuse_candidates((batch,), tenant_id=tenant_id), native_ids


def normalize_reviewed_layout(
    review: dict[str, Any], source: bytes, *, tenant_id: str = _TENANT
) -> tuple[CanonicalDocumentGraph, NormalizationResult, str, list[dict[str, Any]]]:
    """Run existing explicit-role normalization and retain the review's raw lineage."""
    graph, native_ids = graph_from_review(review, source, tenant_id=tenant_id)
    canonical_ids = {
        candidate.source.source_native_id: block.source_id
        for block in graph.blocks
        for candidate in block.candidates
    }
    table_id = canonical_ids["reviewed-table"]
    observations: list[Observation]
    observations, issues, role_bindings = [], list(graph.issues), []
    for index, item in enumerate(review["candidates"]):
        refs = item.get("source_cells")
        if not isinstance(refs, dict):
            raise ValueError("reviewed candidate cell roles required")
        required = {"metric", "unit", "year", "value"}
        if not required <= set(refs) or any(not isinstance(refs[key], str) for key in required):
            raise ValueError("reviewed candidate explicit metric/unit/year/value roles required")
        if any(refs[key] not in native_ids for key in required):
            raise ValueError("reviewed candidate references an unknown cell")
        binding = {
            "metric_raw": canonical_ids[native_ids[refs["metric"]]],
            "unit_raw": canonical_ids[native_ids[refs["unit"]]],
            "reporting_period": canonical_ids[native_ids[refs["year"]]],
            "value_raw": canonical_ids[native_ids[refs["value"]]],
        }
        record = {"candidate_index": index, "bindings": binding, "normalization_status": "held"}
        try:
            normalized = normalize_table_bindings(
                graph, table_id=table_id, bindings=(binding,), tenant_id=tenant_id
            )
        except ValueError as error:
            # An explicit parent row is not a geometry span: do not widen it to
            # make a child value normalize.  Keep the usable role mapping held.
            record["hold_reason"] = str(error)
        else:
            record["normalization_status"] = "normalized_unverified"
            observations.extend(normalized.observations)
            issues.extend(normalized.conflicts)
        role_bindings.append(record)
    return (
        graph,
        NormalizationResult(tuple(observations), tuple(issues), graph),
        table_id,
        role_bindings,
    )
