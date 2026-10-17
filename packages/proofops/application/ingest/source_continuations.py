"""Project PS1 derived paragraphs back onto each literal original SourceRef."""

from dataclasses import replace
from unicodedata import normalize

JOIN_CONTEXT = "source_recovery_join=ps1-v1"


def continuations(graph):
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
        parts.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        if len(parts) < 2 or "\n".join(p.raw_text for p in parts) != block.raw_text:
            raise ValueError("SOURCE_CONTINUATION_INVALID")
        groups[block.source_id] = tuple(parts)
    return groups


def fragment_refs(parts, start, end):
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


def canonical_source_refs(refs):
    """Collapse overlapping parser copies; retain the order of distinct sources.

    Callers must still validate every input ref against its original graph. This
    selection neither repairs offsets nor grants verification to a candidate.
    """

    def key(ref):
        return (
            ref.document_version_id,
            ref.parse_manifest_id,
            ref.page_num,
            " ".join(normalize("NFC", ref.quote).split()),
        )

    def overlaps(left, right):
        a, b = left.bbox, right.bbox
        return (
            a is not None
            and b is not None
            and (min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]))
        )

    def priority(ref):
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
    groups = []
    for index, ref in sorted(enumerate(refs), key=lambda item: priority(item[1])):
        group = next((g for g in groups if key(g[0]) == key(ref) and overlaps(g[0], ref)), None)
        if group is None:
            groups.append([ref, index])
        else:
            group[1] = min(group[1], index)
    return tuple(g[0] for g in sorted(groups, key=lambda g: g[1]))


def claim_quote_matches_sources(quote, refs, graph):
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
