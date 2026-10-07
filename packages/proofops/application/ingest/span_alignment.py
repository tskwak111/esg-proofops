"""Candidate-only, reversible codepoint spans (end exclusive).

No source attestation or glyph geometry is inferred here. The only display
rewrite is CRLF -> LF; even spaces and Unicode typography remain literal.
IDs bind the full raw context and provenance pins. Callers must supply trusted
server inputs, never a model-provided catalog. Existing readers are untouched.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash

PROFILE = "raw-span-candidate-v1"


def _bounds(start: int, end: int, length: int) -> None:
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= length:
        raise DomainValidationError("SPAN_RANGE")


@dataclass(frozen=True)
class SourceIdentity:
    tenant_id: str
    document_version_id: str
    source_id: str
    parse_manifest_id: str
    graph_sha256: str
    original_sha256: str
    physical_page: int

    def __post_init__(self) -> None:
        for name in ("tenant_id", "document_version_id", "source_id", "parse_manifest_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise DomainValidationError("SPAN_IDENTITY")
        for digest in (self.graph_sha256, self.original_sha256):
            if not isinstance(digest, str) or re.fullmatch("[0-9a-f]{64}", digest) is None:
                raise DomainValidationError("SPAN_HASH")
        if type(self.physical_page) is not int or self.physical_page < 1:
            raise DomainValidationError("SPAN_PAGE")


@dataclass(frozen=True)
class SpanAlignment:
    raw: str
    text: str
    raw_boundaries: tuple[int, ...]

    def raw_span(self, start: int, end: int) -> tuple[int, int]:
        _bounds(start, end, len(self.text))
        return self.raw_boundaries[start], self.raw_boundaries[end]

    def selected_span(self, start: int, end: int) -> tuple[int, int]:
        _bounds(start, end, len(self.raw))
        try:
            return self.raw_boundaries.index(start), self.raw_boundaries.index(end)
        except ValueError as exc:
            raise DomainValidationError("SPAN_SPLIT_CODEPOINT_MAP") from exc

    def restore(self, start: int, end: int) -> str:
        raw_start, raw_end = self.raw_span(start, end)
        return self.raw[raw_start:raw_end]


def build_alignment(raw: str) -> SpanAlignment:
    if not isinstance(raw, str):
        raise DomainValidationError("SPAN_TEXT")
    chars, boundaries = [], [0]
    offset = 0
    while offset < len(raw):
        if raw.startswith("\r\n", offset):
            chars.append("\n")
            offset += 2
        else:
            chars.append(raw[offset])
            offset += 1
        boundaries.append(offset)
    return SpanAlignment(raw, "".join(chars), tuple(boundaries))


def align_span(mapping: SpanAlignment, start: int, end: int, quote: str) -> tuple[int, int]:
    """Compare an exact selected display span; never search/fuzzily repair it."""
    raw_span = mapping.raw_span(start, end)
    if not isinstance(quote, str) or mapping.text[start:end] != quote:
        raise DomainValidationError("SPAN_LITERAL_MISMATCH")
    return raw_span


@dataclass(frozen=True)
class SpanCandidate:
    span_id: str
    identity: SourceIdentity
    kind: str
    raw_start: int
    raw_end: int
    quote: str
    occurrence: int
    cell_id: str | None
    context_quote: str

    @property
    def verification_state(self) -> str:
        return "candidate"


def _candidate(
    identity: SourceIdentity,
    raw: str,
    start: int,
    end: int,
    kind: str,
    occurrence: int = 0,
    cell_id: str | None = None,
) -> SpanCandidate:
    _bounds(start, end, len(raw))
    splits_crlf = any(
        0 < boundary < len(raw) and raw[boundary - 1 : boundary + 1] == "\r\n"
        for boundary in (start, end)
    )
    if splits_crlf:
        raise DomainValidationError("SPAN_SPLIT_CODEPOINT_MAP")
    payload = {
        "profile": PROFILE,
        "identity": asdict(identity),
        "raw": raw,
        "start": start,
        "end": end,
        "kind": kind,
        "occurrence": occurrence,
        "cell_id": cell_id,
    }
    return SpanCandidate(
        canonical_hash(payload),
        identity,
        kind,
        start,
        end,
        raw[start:end],
        occurrence,
        cell_id,
        raw,
    )


def validate_candidate(candidate: SpanCandidate, identity: SourceIdentity) -> None:
    """Integrity check, not proof of a trusted writer or source verification."""
    if not isinstance(candidate, SpanCandidate) or candidate.identity != identity:
        raise DomainValidationError("SPAN_IDENTITY_MISMATCH")
    if (
        candidate.kind not in ("clause", "bullet", "cell", "occurrence")
        or type(candidate.occurrence) is not int
        or candidate.occurrence < 0
        or not isinstance(candidate.context_quote, str)
    ):
        raise DomainValidationError("SPAN_CATALOG")
    expected = _candidate(
        identity,
        candidate.context_quote,
        candidate.raw_start,
        candidate.raw_end,
        candidate.kind,
        candidate.occurrence,
        candidate.cell_id,
    )
    if candidate != expected:
        raise DomainValidationError("SPAN_CATALOG")


def build_candidates(
    identity: SourceIdentity, raw: str, *, cells: tuple[tuple[str, int, int], ...] = ()
) -> tuple[SpanCandidate, ...]:
    """Split explicit bullets, or preserve a whole prose block as a clause.

    Commas, semicolons, sentences and line wraps do not prove independent
    subjects/conditions. Keep the full source context on every candidate.
    Table cells require explicit server ranges; no inferred cell geometry.
    """
    build_alignment(raw)  # Validate raw input; candidate quotes remain raw.
    result: list[SpanCandidate] = []
    if cells:
        seen: set[str] = set()
        ranges: list[tuple[int, int]] = []
        for cell_id, start, end in cells:
            _bounds(start, end, len(raw))
            if (
                not isinstance(cell_id, str)
                or not cell_id
                or cell_id in seen
                or any(start < right and left < end for left, right in ranges)
            ):
                raise DomainValidationError("SPAN_CELL")
            seen.add(cell_id)
            ranges.append((start, end))
            result.append(_candidate(identity, raw, start, end, "cell", cell_id=cell_id))
        return tuple(result)
    starts = [m.start() for m in re.finditer(r"(?<!\S)[•●▪](?=\s)", raw)]
    boundaries = sorted({0, *starts, len(raw)})
    for start, end in zip(boundaries, boundaries[1:]):
        if raw[start:end].strip():
            result.append(
                _candidate(identity, raw, start, end, "bullet" if start in starts else "clause")
            )
    return tuple(result)


def occurrence_candidates(
    identity: SourceIdentity, raw: str, quote: str
) -> tuple[SpanCandidate, ...]:
    """Issue separate IDs for every exact occurrence, including overlaps."""
    build_alignment(raw)
    if not isinstance(quote, str) or not quote:
        raise DomainValidationError("SPAN_EMPTY_QUOTE")
    result: list[SpanCandidate] = []
    offset = 0
    while (start := raw.find(quote, offset)) != -1:
        result.append(
            _candidate(identity, raw, start, start + len(quote), "occurrence", len(result))
        )
        offset = start + 1
    return tuple(result)
