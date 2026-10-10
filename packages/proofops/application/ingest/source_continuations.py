"""Project PS1 derived paragraphs back onto each literal original SourceRef."""

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
