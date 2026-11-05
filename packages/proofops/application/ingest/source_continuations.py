"""Project PS1 derived paragraphs back onto each literal original SourceRef."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unicodedata import normalize

from proofops.domain.values import SourceRef

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalBlock, CanonicalDocumentGraph


JOIN_CONTEXT = "source_recovery_join=ps1-v1"


def continuations(graph: CanonicalDocumentGraph) -> dict[str, tuple[CanonicalBlock, ...]]:
    blocks = {b.source_id: b for b in graph.blocks}
    groups = {}
    for block in graph.blocks:
        if block.winner is None or block.quality not in ("verified", "unverified"):
            continue
        if JOIN_CONTEXT not in block.candidates[block.winner].context:
            continue
        parts = [
            blocks[e.target_id]
            for e in graph.edges
            if e.source_id == block.source_id and e.relation == "derived_from"
        ]
        if any(
            p.kind != "paragraph"
            or p.winner is None
            or p.bbox is None
            or p.quality not in ("verified", "unverified")
            or p.page_num != block.page_num
            for p in parts
        ):
            raise ValueError("SOURCE_CONTINUATION_INVALID")
        parts.sort(
            key=lambda b: (
                cast(tuple[float, float, float, float], b.bbox)[1],
                cast(tuple[float, float, float, float], b.bbox)[0],
            )
        )
        if len(parts) < 2 or "\n".join(p.raw_text for p in parts) != block.raw_text:
            raise ValueError("SOURCE_CONTINUATION_INVALID")
        groups[block.source_id] = tuple(parts)
    return groups


def fragment_refs(parts: Sequence[CanonicalBlock], start: int, end: int) -> tuple[SourceRef, ...]:
    refs, cursor = [], 0
    for part in parts:
        local_start, local_end = (
            max(0, start - cursor),
            min(len(part.normalized_text), end - cursor),
        )
        if local_start < local_end:
            refs.append(
                part.source_ref(normalized_char_start=local_start, normalized_char_end=local_end)
            )
        cursor += len(part.normalized_text) + 1
    return tuple(refs)


def canonical_source_refs(refs: Sequence[SourceRef]) -> tuple[SourceRef, ...]:
    """Collapse overlapping parser copies; retain the order of distinct sources.

    Callers must still validate every input ref against its original graph. This
    selection neither repairs offsets nor grants verification to a candidate.
    """

    def key(ref: SourceRef) -> tuple[str, str, int, str]:
        return (
            ref.document_version_id,
            ref.parse_manifest_id,
            ref.page_num,
            " ".join(normalize("NFC", ref.quote).split()),
        )

    def overlaps(left: SourceRef, right: SourceRef) -> bool:
        a, b = left.bbox, right.bbox
        return (
            a is not None
            and b is not None
            and (min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]))
        )

    def priority(ref: SourceRef) -> tuple[bool, float, str, int, int, str]:
        area = (ref.bbox[2] - ref.bbox[0]) * (ref.bbox[3] - ref.bbox[1]) if ref.bbox else 0
        return (
            ref.verification_state != "verified",
            -area,
            ref.source_id,
            ref.char_start,
            ref.char_end,
            ref.quote,
        )

    # Choose in canonical priority order, then restore the earliest occurrence
    # of each group. Do not merge disjoint boxes through a transitive bridge.
    groups: list[list[SourceRef | int]] = []
    for index, ref in sorted(enumerate(refs), key=lambda item: priority(item[1])):
        group = next(
            (
                g
                for g in groups
                if key(cast(SourceRef, g[0])) == key(ref) and overlaps(cast(SourceRef, g[0]), ref)
            ),
            None,
        )
        if group is None:
            groups.append([ref, index])
        else:
            group[1] = min(cast(int, group[1]), index)
    return tuple(cast(SourceRef, g[0]) for g in sorted(groups, key=lambda g: cast(int, g[1])))


def claim_quote_matches_sources(
    quote: str, refs: Sequence[SourceRef], graph: CanonicalDocumentGraph
) -> bool:
    """Accept the legacy sequence or PS1's joined span plus its exact fragments.

    PS1 retains the derived paragraph AND original locations, not consecutive
    pieces to concatenate a second time. Validate their lineage and raw offsets;
    this structural check neither removes references nor verifies their authority.
    """
    canonical = canonical_source_refs(refs)
    if len(canonical) < len(refs) and " ".join(normalize("NFC", quote).split()) == (
        " ".join(normalize("NFC", " ".join(ref.quote for ref in canonical)).split())
    ):
        return True
    refs = canonical
    if refs and quote == " ".join(ref.quote for ref in refs):
        return True
    if len(refs) < 2 or quote != refs[0].quote:
        return False
    primary = refs[0]
    parts = continuations(graph).get(primary.source_id)
    if not parts:
        return False
    block = next(b for b in graph.blocks if b.source_id == primary.source_id)
    if not 0 <= primary.char_start < primary.char_end <= len(block.raw_text):
        return False
    expected_primary = replace(
        block.source_ref(),
        char_start=primary.char_start,
        char_end=primary.char_end,
        quote=block.raw_text[primary.char_start : primary.char_end],
    )
    if replace(primary, verification_state="candidate") != expected_primary:
        return False
    expected, cursor = [], 0
    for part in parts:
        start = max(0, primary.char_start - cursor)
        end = min(len(part.raw_text), primary.char_end - cursor)
        if start < end:
            expected.append(
                replace(
                    part.source_ref(),
                    char_start=start,
                    char_end=end,
                    quote=part.raw_text[start:end],
                )
            )
        cursor += len(part.raw_text) + 1
    return tuple(replace(r, verification_state="candidate") for r in refs[1:]) == tuple(expected)
