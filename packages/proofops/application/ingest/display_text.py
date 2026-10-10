"""Reversible display only. Deletion offsets must come from trusted glyph proof.

Conservatively join Hangul words only; mixed numeric/Latin units and date tokens
are protected. This module never attests a citation or guesses deletion offsets.
"""

import re
from dataclasses import dataclass
from typing import Any

from proofops.application.ingest.span_alignment import SpanAlignment, _bounds
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash

PROFILE = "glyph-joined-display-v1"
POLICY: dict[str, Any] = dict(
    profile=PROFILE,
    max_gap_height_ratio=0.2,
    min_real_space_ratio=1.5,
    alphabet="Hangul-only",
    protected_unit_matching="whole-token-across-space-split-fragments",
    protected_tokens=[
        "년",
        "월",
        "일",
        "톤",
        "원",
        "억",
        "만",
        "천",
        "백",
        "십",
        "미터",
        "제곱",
        "세제곱",
        "킬로미터",
        "밀리미터",
        "그램",
        "밀리그램",
        "밀리리터",
        "헥타르",
        "와트",
        "킬로와트",
        "메가와트",
        "기가와트",
        "와트시",
        "킬로와트시",
        "메가와트시",
        "시간",
        "초",
        "분",
        "도",
        "퍼센트",
        "개",
        "명",
        "대",
        "건",
        "리터",
        "킬로그램",
    ],
)
_PROTECTED_UNIT_PATTERNS = tuple(
    re.compile(r"(?<![가-힣])" + " *".join(token) + r"(?![가-힣])")
    for token in POLICY["protected_tokens"]
    if len(token) > 1
)
SYSTEM_SUFFIX = (
    "\nDisplay policy glyph-joined-display-v1: only glyph-proven artificial spaces "
    "were removed locally. Copy exact unique literal substrings from the displayed "
    "source. Never translate, insert characters, change numbers/units or combine "
    "sources. The server restores raw offsets and revalidates citations."
    + " Policy SHA256: "
    + canonical_hash(POLICY)
)


def join_allowed(raw: str, offset: int) -> bool:
    if not 0 < offset < len(raw) - 1 or raw[offset] != " ":
        return False
    # A unit can have several artificial splits: protecting only adjacent
    # fragments would still allow a deletion inside "킬 로 그 램".
    if any(
        match.start() < offset < match.end()
        for pattern in _PROTECTED_UNIT_PATTERNS
        for match in pattern.finditer(raw)
    ):
        return False
    left = re.search(r"\S+$", raw[:offset])
    right = re.match(r"\S+", raw[offset + 1 :])
    if left is None or right is None:
        return False
    # Punctuation on the far side of a Korean word is harmless; numeric/Latin
    # codepoints anywhere in either word veto the join (including tCO2e, m²).
    a, b = left[0].strip(".,;:()[]“”\"'•"), right[0].strip(".,;:()[]“”\"'•")
    return (
        bool(re.fullmatch("[가-힣]+", a))
        and bool(re.fullmatch("[가-힣]+", b))
        and a not in POLICY["protected_tokens"]
        and b not in POLICY["protected_tokens"]
        and a + b not in POLICY["protected_tokens"]
        and "가" <= raw[offset - 1] <= "힣"
        and "가" <= raw[offset + 1] <= "힣"
    )


@dataclass(frozen=True)
class DisplayAlignment(SpanAlignment):
    """Two-sided boundary mapping: a removed space belongs to neither edge.

    Interior removed codepoints round-trip in raw substrings. An endpoint
    inside a removed space is not an exact display span and is rejected.
    """

    def raw_span(self, start: int, end: int) -> tuple[int, int]:
        _bounds(start, end, len(self.text))
        return self.raw_boundaries[start + 1] - 1, self.raw_boundaries[end]

    def selected_span(self, start: int, end: int) -> tuple[int, int]:
        _bounds(start, end, len(self.raw))
        try:
            return (
                self.raw_boundaries[1:].index(start + 1),
                self.raw_boundaries[1:].index(end) + 1,
            )
        except ValueError as exc:
            raise DomainValidationError("SPAN_SPLIT_CODEPOINT_MAP") from exc


def display_alignment(raw: str, deleted_offsets) -> DisplayAlignment:
    deleted = tuple(deleted_offsets)
    if deleted != tuple(sorted(set(deleted))) or any(
        type(i) is not int or not join_allowed(raw, i) for i in deleted
    ):
        raise ValueError("DISPLAY_PROTECTED_BOUNDARY")
    deleted_set = set(deleted)
    retained = [i for i in range(len(raw)) if i not in deleted_set]
    return DisplayAlignment(raw, "".join(raw[i] for i in retained), (0, *(i + 1 for i in retained)))


def locate_display(quote: str, mapping: SpanAlignment) -> tuple[int, int, str]:
    if (
        not isinstance(quote, str)
        or not quote.strip()
        or quote not in mapping.text
        or mapping.text.find(quote) != mapping.text.rfind(quote)
    ):
        raise ValueError("display quote absent or ambiguous")
    start = mapping.text.index(quote)
    raw_start, raw_end = mapping.raw_span(start, start + len(quote))
    return raw_start, raw_end, mapping.raw[raw_start:raw_end]


def _deleted(mapping):
    return set(range(len(mapping.raw))) - {i - 1 for i in mapping.raw_boundaries[1:]}


def mapping_pin(mapping: SpanAlignment, *, identity: dict, boundaries: list) -> dict:
    return dict(
        policy=POLICY,
        identity=identity,
        raw_sha256=canonical_hash(mapping.raw),
        text=mapping.text,
        raw_boundaries=list(mapping.raw_boundaries),
        deleted_offsets=sorted(_deleted(mapping)),
        boundaries=boundaries,
    )
