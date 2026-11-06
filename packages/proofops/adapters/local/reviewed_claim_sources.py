"""Read frozen claim spans and corroborate their original disclosure literals."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber

_COLUMN_TOL = 1.0
_ROW_TOL = 3.0


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass(frozen=True, slots=True)
class FrozenClaimSpan:
    """One claim span exactly as a frozen extraction receipt retained it.

    The receipt's own quote check is what kept this span; that is not a native or
    rendered source verification and is never reported as one.
    """

    receipt_id: str
    tenant_id: str
    document_version_id: str
    parse_manifest_id: str
    source_sha256: str
    block_source_id: str
    page_num: int
    block_kind: str
    block_text: str
    char_start: int
    char_end: int
    quote: str
    topic_ids: tuple[str, ...]
    provider_model: str | None

    @property
    def origin(self) -> dict[str, Any]:
        """The origin provenance, kept verbatim so nothing has to be rewritten."""
        return {
            "receipt_id": self.receipt_id,
            "tenant_id": self.tenant_id,
            "document_version_id": self.document_version_id,
            "parse_manifest_id": self.parse_manifest_id,
            "source_sha256": self.source_sha256,
            "block_source_id": self.block_source_id,
            "page_num": self.page_num,
            "block_kind": self.block_kind,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.quote,
            "topic_ids": list(self.topic_ids),
            "provider_model": self.provider_model,
        }


def load_frozen_claim_spans(
    receipts_dir: Path,
    *,
    pages: Collection[int] | None = None,
    contains: str | None = None,
) -> tuple[FrozenClaimSpan, ...]:
    """Read source-verified claim spans out of frozen extraction receipts.

    Read-only: nothing in the run directory is written, and a receipt whose
    verification rejected a quote contributes no span for it.
    """
    spans: list[FrozenClaimSpan] = []
    for result_path in sorted(receipts_dir.glob("*/result.json")):
        directory = result_path.parent
        packet_path = directory / "packet.json"
        raw_path = directory / "raw_response.json"
        if not packet_path.exists():
            continue
        packet = json.loads(packet_path.read_text())
        result = json.loads(result_path.read_text())
        block = packet.get("untrusted_document_data") or {}
        page = block.get("page_num")
        if not isinstance(page, int) or (pages is not None and page not in pages):
            continue
        raw_text = block.get("text")
        if not isinstance(raw_text, str):
            continue
        provider = None
        if raw_path.exists():
            provider = json.loads(raw_path.read_text()).get("provider_model")
        for span in result.get("spans") or ():
            if span.get("kind") != "claim":
                continue
            quote = span.get("quote")
            if not isinstance(quote, str) or (contains is not None and contains not in quote):
                continue
            start, end = span.get("char_start"), span.get("char_end")
            if type(start) is not int or type(end) is not int:
                raise ValueError("frozen claim span offsets required")
            if raw_text[start:end] != quote:
                raise ValueError(f"frozen claim span does not match its block: {directory.name}")
            spans.append(
                FrozenClaimSpan(
                    receipt_id=result.get("request_id") or directory.name,
                    tenant_id=packet["tenant_id"],
                    document_version_id=packet["document_version_id"],
                    parse_manifest_id=packet["parse_manifest_id"],
                    source_sha256=packet["source_sha256"],
                    block_source_id=block["source_id"],
                    page_num=page,
                    block_kind=block.get("kind") or "unknown",
                    block_text=raw_text,
                    char_start=start,
                    char_end=end,
                    quote=quote,
                    topic_ids=tuple(span.get("topic_ids") or ()),
                    provider_model=provider,
                )
            )
    return tuple(spans)


@dataclass(frozen=True, slots=True)
class SourceReverification:
    """This module's own text re-read of the claim page, independent of any parser.

    Corroboration of literals and their layout relationship, not an attestation.
    """

    page_num: int
    page_height: float
    value_literal: str
    value_bbox: tuple[float, float, float, float] | None
    value_occurrences: int
    year_literal: str
    year_bbox: tuple[float, float, float, float] | None
    row_literals: tuple[str, ...]
    missing_row_literals: tuple[str, ...]
    column_aligned: bool
    row_aligned: bool
    holds: tuple[str, ...]

    @property
    def corroborated(self) -> bool:
        """Every literal was re-found where the claim implies; still not verified."""
        return not self.holds


def reverify_disclosure_cell(
    source: bytes,
    *,
    page_num: int,
    value_literal: str,
    year_literal: str,
    row_literals: Sequence[str],
) -> SourceReverification:
    """Re-find the value, its year column and its row band in the PDF text itself.

    The year is attested by geometry, not by reading order: the nearest year token
    above the value whose horizontal span overlaps it. A duplicated value literal,
    a missing row literal or a year in another column is a hold, never a guess.
    """
    with pdfplumber.open(io.BytesIO(source)) as pdf:
        page = pdf.pages[page_num - 1]
        height = float(page.height)
        words = page.extract_words()
    target = _squeeze(value_literal)
    value_hits = [word for word in words if _squeeze(word["text"]) == target]
    holds: list[str] = []
    if len(value_hits) != 1:
        holds.append(f"claim_value_literal_not_unique_on_page:{len(value_hits)}")
    value_word = value_hits[0] if len(value_hits) == 1 else None

    year_bbox: tuple[float, float, float, float] | None = None
    column_aligned = False
    if value_word is not None:
        above = [
            word
            for word in words
            if _squeeze(word["text"]) == _squeeze(year_literal)
            and word["bottom"] <= value_word["top"] + _ROW_TOL
            and word["x0"] < value_word["x1"] + _COLUMN_TOL
            and word["x1"] > value_word["x0"] - _COLUMN_TOL
        ]
        if above:
            header = max(above, key=lambda word: word["top"])
            year_bbox = _pdf_bbox(header, height)
            column_aligned = True
        else:
            holds.append("claim_year_header_not_column_aligned")

    missing: list[str] = []
    row_aligned = value_word is not None
    for literal in row_literals:
        squeezed = _squeeze(literal)
        same_row = [
            word
            for word in words
            if squeezed in _squeeze(word["text"])
            and value_word is not None
            and abs(word["top"] - value_word["top"]) <= _ROW_TOL
        ]
        if not same_row:
            missing.append(literal)
            row_aligned = False
    if missing:
        holds.append("claim_row_literals_not_in_value_row:" + ",".join(missing))

    return SourceReverification(
        page_num=page_num,
        page_height=height,
        value_literal=value_literal,
        value_bbox=_pdf_bbox(value_word, height) if value_word else None,
        value_occurrences=len(value_hits),
        year_literal=year_literal,
        year_bbox=year_bbox,
        row_literals=tuple(row_literals),
        missing_row_literals=tuple(missing),
        column_aligned=column_aligned,
        row_aligned=row_aligned,
        holds=tuple(holds),
    )


def _pdf_bbox(word: dict[str, Any], height: float) -> tuple[float, float, float, float]:
    return (
        float(word["x0"]),
        height - float(word["bottom"]),
        float(word["x1"]),
        height - float(word["top"]),
    )
