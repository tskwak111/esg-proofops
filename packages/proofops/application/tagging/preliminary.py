"""Bounded, literal preliminary classification, never grading.

Only trusted, tenant-authorized canonical graphs enter this boundary. Validation
proves source existence, not the model's semantic classification accuracy. Callers
must retain raw responses and model/prompt/rule/replica pins before publication.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, replace
from math import isfinite
from typing import TYPE_CHECKING, Any, cast

from proofops.application.claims import Claim
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.graph_fusion import CanonicalBlock, CanonicalDocumentGraph
from proofops.application.ingest.source_continuations import (
    canonical_source_refs,
    claim_quote_matches_sources,
)
from proofops.application.tagging.contracts import (
    PreliminaryClassification as PreliminaryClassification,
)
from proofops.application.tagging.preliminary_prompts import (
    _EXCLUDED_CONTEXT_KINDS as _EXCLUDED_CONTEXT_KINDS,
)
from proofops.application.tagging.preliminary_prompts import (
    _FIELDS as _FIELDS,
)
from proofops.application.tagging.preliminary_prompts import (
    _P1_METRIC as _P1_METRIC,
)
from proofops.application.tagging.preliminary_prompts import (
    _P1_SAFE_HARBOR as _P1_SAFE_HARBOR,
)
from proofops.application.tagging.preliminary_prompts import (
    _P1_TRACK as _P1_TRACK,
)
from proofops.application.tagging.preliminary_prompts import (
    _REFUSABLE as _REFUSABLE,
)
from proofops.application.tagging.preliminary_prompts import (
    ACTOR_ROLE_SYSTEM_SUFFIX as ACTOR_ROLE_SYSTEM_SUFFIX,
)
from proofops.application.tagging.preliminary_prompts import (
    CONTEXT_SCHEMA as CONTEXT_SCHEMA,
)
from proofops.application.tagging.preliminary_prompts import (
    CONTEXT_SYSTEM_SUFFIX as CONTEXT_SYSTEM_SUFFIX,
)
from proofops.application.tagging.preliminary_prompts import (
    GOAL_ROLE_SYSTEM_SUFFIX as GOAL_ROLE_SYSTEM_SUFFIX,
)
from proofops.application.tagging.preliminary_prompts import (
    P1_SYSTEM_PROMPT as P1_SYSTEM_PROMPT,
)
from proofops.application.tagging.preliminary_prompts import (
    P2_SYSTEM_PROMPT as P2_SYSTEM_PROMPT,
)
from proofops.application.tagging.preliminary_prompts import (
    PERIOD_ROLE_SYSTEM_SUFFIX as PERIOD_ROLE_SYSTEM_SUFFIX,
)
from proofops.application.tagging.preliminary_prompts import (
    SCHEMA as SCHEMA,
)
from proofops.application.tagging.preliminary_prompts import (
    SENTENCE_CONTEXT_PROFILE as SENTENCE_CONTEXT_PROFILE,
)
from proofops.application.tagging.preliminary_prompts import (
    SENTENCE_CONTEXT_SYSTEM_PROMPT as SENTENCE_CONTEXT_SYSTEM_PROMPT,
)
from proofops.application.tagging.preliminary_prompts import (
    SENTENCE_CONTEXT_SYSTEM_SUFFIX as SENTENCE_CONTEXT_SYSTEM_SUFFIX,
)
from proofops.application.tagging.preliminary_prompts import (
    SENTENCE_FALLBACK_BASE_PROMPT as SENTENCE_FALLBACK_BASE_PROMPT,
)
from proofops.application.tagging.preliminary_prompts import (
    SENTENCE_FALLBACK_PROFILE as SENTENCE_FALLBACK_PROFILE,
)
from proofops.application.tagging.preliminary_prompts import (
    SENTENCE_FALLBACK_SYSTEM_PROMPT as SENTENCE_FALLBACK_SYSTEM_PROMPT,
)
from proofops.application.tagging.preliminary_prompts import (
    SYSTEM_PROMPT as SYSTEM_PROMPT,
)
from proofops.application.tagging.preliminary_prompts import (
    TABLE_ROLE_SYSTEM_SUFFIX as TABLE_ROLE_SYSTEM_SUFFIX,
)
from proofops.application.tagging.preliminary_prompts import (
    TABLE_SCHEMA as TABLE_SCHEMA,
)
from proofops.application.tagging.preliminary_prompts import (
    TABLE_SYSTEM_SUFFIX as TABLE_SYSTEM_SUFFIX,
)
from proofops.application.tagging.table_sources import (
    TABLE_SOURCE_POLICY,
    table_structural_sources,
)
from proofops.application.tagging.tracks import validate_track_candidates
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SAFE_HARBOR_CATEGORIES, SourceRef, _require_uuid

if TYPE_CHECKING:
    from proofops.application.tagging.table_sources import TableClaimSource


def _sources(
    claim: Claim, graph: CanonicalDocumentGraph, tenant_id: str, *, allow_unverified: bool = False
) -> tuple[SourceRef, ...]:
    _require_uuid("tenant_id", tenant_id)
    if not isinstance(claim, Claim) or not isinstance(graph, CanonicalDocumentGraph):
        raise DomainValidationError("internal claim and canonical graph required")
    if (
        claim.tenant_id != tenant_id
        or graph.tenant_id != tenant_id
        or (claim.document_version_id, claim.parse_manifest_id, claim.source_sha256)
        != (graph.document_version_id, graph.parse_manifest_id, graph.source_sha256)
        or (claim.source_quality != "verified" and not allow_unverified)
        or not claim.source_refs
    ):
        raise DomainValidationError("preliminary source identity or quality mismatch")
    verified = tuple(
        verify_source_ref(ref, graph, tenant_id=tenant_id) for ref in claim.source_refs
    )
    if any(
        (ref.verification_state != "verified" and not allow_unverified)
        or ref.quote != original.quote
        for ref, original in zip(verified, claim.source_refs, strict=True)
    ):
        # Relative offsets require literal raw text, not a normalized offset space.
        raise DomainValidationError("preliminary source validation required")
    if allow_unverified:
        blocks = {b.source_id: b for b in graph.blocks}
        for ref in claim.source_refs:
            block = blocks.get(ref.source_id)
            if block is None or block.winner is None or ref.location_quality != "located":
                raise DomainValidationError("candidate source location required")
            canonical = block.source_ref()
            if (
                any(
                    getattr(ref, k) != getattr(canonical, k)
                    for k in (
                        "document_version_id",
                        "parse_manifest_id",
                        "page_num",
                        "bbox",
                        "raw_text_sha256",
                        "printed_page_label",
                    )
                )
                or not 0 <= ref.char_start < ref.char_end <= len(block.raw_text)
                or block.raw_text[ref.char_start : ref.char_end] != ref.quote
            ):
                raise DomainValidationError("candidate literal source mismatch")
    # Validate all input locations before eliminating parser copies, so a bad
    # duplicate cannot conceal a foreign artifact or altered literal span.
    if not claim_quote_matches_sources(claim.quote, verified, graph):
        raise DomainValidationError("preliminary source identity or quality mismatch")
    return canonical_source_refs(verified)


def _sentence_window(text: str, start: int, end: int) -> tuple[int, int] | None:
    # A decimal point is not a sentence end. Never manufacture punctuation,
    # normalize text, cross a block boundary, or include an unfinished tail.
    spans = []
    begin = 0
    for match in re.finditer(r"[.!?。！？](?=\s|$)", text):
        stop = match.end()
        if text[begin:stop].strip():
            left = begin
            while left < stop and text[left].isspace():
                left += 1
            spans.append((left, stop))
        begin = stop
    hits = [i for i, (left, right) in enumerate(spans) if left < end and right > start]
    if not hits or spans[hits[0]][0] > start or spans[hits[-1]][1] < end:
        return None
    return spans[max(0, hits[0] - 2)][0], spans[min(len(spans) - 1, hits[-1] + 2)][1]


def _sentence_context(
    graph: CanonicalDocumentGraph,
    sources: tuple[SourceRef, ...],
    tenant_id: str,
    max_chars: int,
    max_blocks: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    blocks = {block.source_id: block for block in graph.blocks}
    entries: list[dict[str, Any]] = []
    omitted, used, seen = [], 0, set()
    for ref in sources:
        if ref.source_id in seen:
            continue
        seen.add(ref.source_id)
        block = blocks[ref.source_id]
        if block.kind not in {"paragraph", "caption", "footnote"}:
            omitted.append(ref.source_id)
            continue
        bounds = _sentence_window(block.raw_text, ref.char_start, ref.char_end)
        if bounds is None:
            omitted.append(ref.source_id)
            continue
        start, end = bounds
        expanded = replace(
            block.source_ref(), char_start=start, char_end=end, quote=block.raw_text[start:end]
        )
        verified = verify_source_ref(expanded, graph, tenant_id=tenant_id)
        if verified.verification_state != "verified" or verified.quote != expanded.quote:
            omitted.append(ref.source_id)
            continue
        if len(entries) >= max_blocks or used + len(expanded.quote) > max_chars:
            omitted.append(ref.source_id)
            continue  # whole sentence window only, never character truncation
        entry = _context_entry(len(entries), block, "parent_paragraph")
        entry.update(
            text=expanded.quote,
            quality="verified",
            source_ref={k: v for k, v in asdict(verified).items() if k != "quote"},
        )
        entries.append(entry)
        used += len(expanded.quote)
    return entries, omitted


def sentence_context_ready(claim: Claim, packet: dict[str, Any]) -> bool:
    """The opt-in trial requires verified complete interpretation input.

    Missing or byte-bounded-away sentence context never licenses classification
    of an isolated fragment. Verified own-table headers remain the equivalent
    structural interpretation input for a table value, under the existing guard.
    """
    data = packet["untrusted_document_data"]
    table = packet.get("table_policy", {})
    if (
        table.get("lineage") == "resolved"
        and table.get("verified_sources_only") is True
        and any(s.get("table_role") in {"row_header", "column_header"} for s in data["sources"])
    ):
        return True
    context = [
        b["source_ref"]
        for b in data.get("context_blocks", [])
        if b["role"] == "parent_paragraph"
        and b["quality"] == "verified"
        and b["source_ref"].get("verification_state") == "verified"
    ]
    return all(
        any(
            b["source_id"] == ref.source_id
            and b["char_start"] <= ref.char_start < ref.char_end <= b["char_end"]
            for b in context
        )
        for ref in claim.source_refs
    )


def _center(bbox: tuple[float, float, float, float] | None) -> tuple[float, float] | None:
    if bbox is None:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


_ROLE_PRIORITY = {"parent_paragraph": 0, "heading": 1, "nearby": 2}
CONTEXT_POSITION_ORDER = {
    "version": "document-position-v1",
    "sha256": canonical_hash(
        ["page_num", "canonical_bbox_top", "canonical_bbox_left", "raw_text", "kind"]
    ),
}


def _position_key(block: CanonicalBlock) -> tuple[int, bool, float, float, str, str]:
    # Canonical boxes use a top-left origin. Missing geometry sorts last on its page.
    return (
        block.page_num,
        block.bbox is None,
        block.bbox[1] if block.bbox else 0,
        block.bbox[0] if block.bbox else 0,
        block.raw_text,
        block.kind,
    )


def _context_candidates(
    graph: CanonicalDocumentGraph, sources: tuple[SourceRef, ...], *, position_order: bool = False
) -> list[tuple[CanonicalBlock, str]]:
    """Bounded, source-bound interpretation-only blocks for the claim's own sources.

    Never returns a claim-eligible ref; callers keep context strictly outside
    the indexable ``sources`` tuple. Three roles, most useful first:
    * ``parent_paragraph`` -- the FULL block containing an atomic claim quote,
      whenever the claim is a strict sub-span of a longer block (an atomic
      claim's own ``sources[i].text`` is already the exact quote span; this
      role restores the surrounding sentence/paragraph it was cut from).
    * ``heading`` -- the block's immediate ``section_parent`` ancestor, when
      the real parser populated that edge (e.g. OpenDataLoader). At most one
      per claim source, deduplicated.
    * ``nearby`` -- same-page sibling blocks ranked by bbox-center distance,
      whole blocks only, excluding tables/table cells (a numeric-heavy kind
      that would tempt the model to borrow a neighboring figure).
    """
    claim_ids = {ref.source_id for ref in sources}
    blocks = {b.source_id: b for b in graph.blocks}
    parent_targets: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.relation == "section_parent":
            parent_targets.setdefault(edge.source_id, set()).add(edge.target_id)
    # Only an UNAMBIGUOUS single section_parent target is usable as a heading;
    # multiple distinct declared parents for the same child stay unresolved
    # rather than silently picking one (never guess an arbitrary parent).
    parents = {
        source_id: next(iter(targets))
        for source_id, targets in parent_targets.items()
        if len(targets) == 1
    }
    candidates: dict[str, tuple[CanonicalBlock, str]] = {}
    for ref in sources:
        target = blocks.get(ref.source_id)
        if (
            target is not None
            and target.winner is not None
            and ref.char_end - ref.char_start < len(target.raw_text)
        ):
            # The claim is a strict sub-span of its own containing block's RAW
            # text (compared in the same raw offset space as SourceRef/
            # source_ref, not the normalized-text length); the block itself
            # (whole, unmodified) is the "parent paragraph".
            candidates.setdefault(target.source_id, (target, "parent_paragraph"))
        parent_id = parents.get(ref.source_id)
        parent = blocks.get(parent_id) if parent_id else None
        if (
            parent is not None
            and parent.source_id not in claim_ids
            and parent.quality in _REFUSABLE
            and parent.winner is not None
            and parent.raw_text.strip()
        ):
            candidates.setdefault(parent.source_id, (parent, "heading"))
        center = _center(target.bbox) if target is not None else None
        if target is None or center is None:
            continue
        page = target.page_num

        def distance(block: CanonicalBlock) -> float:
            other = _center(block.bbox)
            return abs(center[0] - cast("tuple[float, float]", other)[0]) + abs(
                center[1] - cast("tuple[float, float]", other)[1]
            )

        nearby = sorted(
            (
                b
                for b in graph.blocks
                if b.source_id not in claim_ids
                and b.source_id not in candidates
                and b.page_num == page
                and b.quality in _REFUSABLE
                and b.winner is not None
                and b.kind not in _EXCLUDED_CONTEXT_KINDS
                and b.raw_text.strip()
                and b.bbox is not None
            ),
            key=lambda b: (
                (distance(b), tuple(b.bbox), b.raw_text, b.source_id)
                if not position_order
                else (distance(b), _position_key(b))
            ),
        )
        for block in nearby[:2]:
            candidates.setdefault(block.source_id, (block, "nearby"))
    # Keep role priority for bounded selection; opt-in ties use document position.
    ordered = sorted(
        candidates.values(),
        key=(
            (lambda pair: (_ROLE_PRIORITY[pair[1]], _position_key(pair[0])))
            if position_order
            else (lambda pair: (_ROLE_PRIORITY[pair[1]], pair[0].source_id))
        ),
    )
    return ordered


def _context_entry(context_index: int, block: CanonicalBlock, role: str) -> dict[str, Any]:
    """Full-provenance context entry: never a bare index/text pair.

    ``text`` is the block's RAW text (same string space as ``source_ref``'s
    raw offsets/``raw_text_sha256``), not the NFC-normalized render, so the
    sent text and its provenance always describe the identical bytes.
    """
    ref = block.source_ref()
    return dict(
        context_index=context_index,
        role=role,
        source_id=block.source_id,
        page_num=block.page_num,
        quality=block.quality,
        text=block.raw_text,
        source_ref={k: v for k, v in asdict(ref).items() if k != "quote"},
    )


def _bounded_context_blocks(
    graph: CanonicalDocumentGraph,
    sources: tuple[SourceRef, ...],
    *,
    max_context_chars: int,
    max_context_blocks: int,
    position_order: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    if type(position_order) is not bool:
        raise DomainValidationError("preliminary context order invalid")
    if (
        type(max_context_chars) is not int
        or not 1 <= max_context_chars <= 20000
        or type(max_context_blocks) is not int
        or not 0 <= max_context_blocks <= 20
    ):
        raise DomainValidationError("preliminary context bounds invalid")
    candidates = _context_candidates(graph, sources, position_order=position_order)
    chosen: list[tuple[CanonicalBlock, str]] = []
    used, omitted = 0, []
    for block, role in candidates[:max_context_blocks]:
        size = len(block.raw_text) + (1 if chosen else 0)
        if used + size > max_context_chars:
            omitted.append(block.source_id)
            continue  # whole blocks only; never char-truncate a neighbour
        chosen.append((block, role))
        used += size
    omitted.extend(block.source_id for block, _ in candidates[max_context_blocks:])
    if position_order:
        chosen.sort(key=lambda pair: _position_key(pair[0]))
    blocks = [_context_entry(i, block, role) for i, (block, role) in enumerate(chosen)]
    return blocks, omitted


def preliminary_request(
    claim: Claim,
    graph: CanonicalDocumentGraph,
    *,
    tenant_id: str,
    include_context: bool = False,
    max_context_chars: int = 2000,
    max_context_blocks: int = 4,
    position_order: bool = False,
    allow_unverified: bool = False,
) -> dict[str, Any]:
    """Trusted preliminary envelope; ``include_context`` is opt-in and additive.

    Omitting ``include_context`` (the default) reproduces the exact legacy
    ``SCHEMA``/shape byte-for-byte: no ``context_blocks`` key at all. When set,
    a separate ``context_blocks`` list is added under a distinct
    ``CONTEXT_SCHEMA`` so old and new envelopes stay structurally
    distinguishable; context entries are never appended into ``sources`` and
    can never be selected by a dimension's ``source_index``.
    """
    if type(position_order) is not bool or (position_order and not include_context):
        raise DomainValidationError("preliminary context order requires context")
    sources = _sources(claim, graph, tenant_id, allow_unverified=allow_unverified)
    envelope: dict[str, Any] = dict(
        schema=SCHEMA,
        tenant_id=tenant_id,
        claim_id=claim.claim_id,
        claim_sha256=canonical_hash(asdict(claim)),
        graph_sha256=canonical_hash(asdict(graph)),
        prompt_sha256=canonical_hash(SYSTEM_PROMPT),
        untrusted_document_data=dict(
            sources=[dict(source_index=i, text=ref.quote) for i, ref in enumerate(sources)]
        ),
    )
    if not include_context:
        return envelope
    blocks, omitted = _bounded_context_blocks(
        graph,
        sources,
        max_context_chars=max_context_chars,
        max_context_blocks=max_context_blocks,
        position_order=position_order,
    )
    envelope["schema"] = CONTEXT_SCHEMA
    # The actual rendered prompt sent to the model includes the additive
    # context suffix; prompt_sha256 always pins the prompt actually used.
    envelope["prompt_sha256"] = canonical_hash(SYSTEM_PROMPT + CONTEXT_SYSTEM_SUFFIX)
    envelope["untrusted_document_data"]["context_blocks"] = blocks
    envelope["untrusted_document_data"]["omitted_source_ids"] = omitted
    envelope["context_policy"] = dict(
        same_page_or_section_parent_only=True,
        excluded_kinds=sorted(_EXCLUDED_CONTEXT_KINDS),
        max_context_chars=max_context_chars,
        max_context_blocks=max_context_blocks,
        whole_blocks_only=True,
    )
    if position_order:
        envelope["context_ordering"] = CONTEXT_POSITION_ORDER
    return envelope


def _table_source_entry(index: int, item: TableClaimSource) -> dict[str, Any]:
    """Numbered source entry for one real, verified table axis cell."""
    return dict(
        source_index=index,
        text=item.ref.quote,
        table_role=item.role,
        table_association=item.association,
        table_row_number=item.row_number,
        table_column_number=item.column_number,
    )


def _table_context_entry(context_index: int, item: TableClaimSource) -> dict[str, Any]:
    """Interpretation-only entry for a table axis cell that is NOT verified.

    Same provenance shape as ``_context_entry``; the role is prefixed so a
    reader can never confuse it with a numbered, quotable source. Its real
    ``verification_state`` travels with it, so an unverified axis cell is
    visible as a candidate and can never be read as approved evidence.
    """
    return dict(
        context_index=context_index,
        role="table_" + item.role,
        source_id=item.ref.source_id,
        page_num=item.ref.page_num,
        quality="unverified",
        text=item.ref.quote,
        source_ref={key: value for key, value in asdict(item.ref).items() if key != "quote"},
    )


def preliminary_table_request(
    claim: Claim,
    graph: CanonicalDocumentGraph,
    *,
    tenant_id: str,
    max_context_chars: int = 2000,
    max_context_blocks: int = 4,
    max_table_sources: int = 8,
    max_table_chars: int = 600,
    role_resolution: bool = False,
    goal_role: bool = False,
    actor_role: bool = False,
    period_role: bool = False,
    p1: bool = False,
    p2: bool = False,
    position_order: bool = False,
    sentence_context: bool = False,
    allow_unverified: bool = False,
) -> dict[str, Any]:
    """Opt-in ``TABLE_SCHEMA`` envelope: context plus verified table axis sources.

    Built on the existing ``CONTEXT_SCHEMA`` envelope, so ordinary context
    behaviour is unchanged and index 0..n-1 remain the claim's own literal
    sources byte-for-byte. Appended sources are real cells of the claim value's
    own table row/column that passed BOTH the existing source verification and
    an actual same-table row/column association (``table_sources``). An axis
    cell that is not verified is NOT appended: it travels as an explicitly
    prefixed context block instead, and an unresolvable lineage appends nothing
    and records ``lineage="unresolved"`` rather than inventing a row or column.

    ``role_resolution`` is opt-in and changes ONLY ``prompt_sha256``: the
    wire shape, the source list, the index space and both policies stay
    byte-identical, because the difference is purely the additive prompt suffix
    that resolves the atomic-source/table-axis conflict. Omitting it reproduces
    the existing table envelope exactly.

    ``goal_role`` is opt-in and requires ``role_resolution=True``. It
    appends ``GOAL_ROLE_SYSTEM_SUFFIX`` after ``TABLE_ROLE_SYSTEM_SUFFIX`` in
    the prompt hash ONLY; the wire shape, source list, index space, and both
    policies are byte-identical to the role-resolution envelope. Omitting it
    reproduces the exact table-role envelope. ``goal_role=False`` must yield the
    same hash as a plain ``role_resolution=True`` call.
    """
    if type(sentence_context) is not bool or (
        sentence_context
        and (
            role_resolution or goal_role or actor_role or period_role or p1 or p2 or position_order
        )
    ):
        raise DomainValidationError("preliminary sentence context profile is exclusive")
    if type(role_resolution) is not bool:
        raise DomainValidationError("preliminary table role resolution must be boolean")
    if type(goal_role) is not bool:
        raise DomainValidationError("preliminary table goal role must be boolean")
    if type(actor_role) is not bool:
        raise DomainValidationError("preliminary table actor role must be boolean")
    if goal_role and not role_resolution:
        raise DomainValidationError("preliminary table goal role requires role_resolution")
    if actor_role and not goal_role:
        raise DomainValidationError("preliminary table actor role requires goal_role")
    if type(period_role) is not bool:
        raise DomainValidationError("preliminary table period role must be boolean")
    if period_role and not actor_role:
        raise DomainValidationError("preliminary table period role requires actor_role")
    if type(p1) is not bool or (
        p1 and (not role_resolution or goal_role or actor_role or period_role)
    ):
        raise DomainValidationError("preliminary P1 requires only table role resolution")
    if type(p2) is not bool or (
        p2 and (not role_resolution or goal_role or actor_role or period_role or p1)
    ):
        raise DomainValidationError("preliminary P2 requires only table role resolution")
    envelope = preliminary_request(
        claim,
        graph,
        tenant_id=tenant_id,
        include_context=True,
        max_context_chars=max_context_chars,
        max_context_blocks=max_context_blocks,
        position_order=position_order,
        allow_unverified=allow_unverified,
    )
    sources = _sources(claim, graph, tenant_id, allow_unverified=allow_unverified)
    if sentence_context:
        blocks, omitted = _sentence_context(
            graph, sources, tenant_id, max_context_chars, max_context_blocks
        )
        envelope["untrusted_document_data"]["context_blocks"] = blocks
        envelope["untrusted_document_data"]["omitted_source_ids"] = omitted
        envelope["context_policy"]["whole_blocks_only"] = False
    table = table_structural_sources(
        graph,
        sources,
        tenant_id=tenant_id,
        max_sources=max_table_sources,
        max_chars=max_table_chars,
    )
    data = envelope["untrusted_document_data"]
    source_offset = len(data["sources"])
    data["sources"].extend(
        _table_source_entry(source_offset + index, item)
        for index, item in enumerate(table.verified)
    )
    # A cell's atomic paragraph is an ordinary paragraph block, so the plain
    # neighbour scan can legitimately have picked the same block. Its table role
    # (or its promotion to a numbered source) is strictly more informative, so
    # the duplicate neighbour entry is dropped and the list is renumbered rather
    # than sending the same source twice under two identities.
    axis_ids = {item.ref.source_id for item in table.verified + table.context_only}
    kept = [block for block in data["context_blocks"] if block["source_id"] not in axis_ids]
    kept.extend(
        _table_context_entry(len(kept) + index, item)
        for index, item in enumerate(table.context_only)
    )
    if position_order:
        by_id = {block.source_id: block for block in graph.blocks}
        kept.sort(key=lambda entry: _position_key(by_id[entry["source_id"]]))
    data["context_blocks"] = [{**block, "context_index": index} for index, block in enumerate(kept)]
    data["omitted_source_ids"] = [
        *data["omitted_source_ids"],
        *(
            source_id
            for source_id in table.omitted_source_ids
            if source_id not in data["omitted_source_ids"]
        ),
    ]
    if position_order:
        data["omitted_source_ids"].sort(key=lambda source_id: _position_key(by_id[source_id]))
    envelope["schema"] = TABLE_SCHEMA
    envelope["prompt_sha256"] = canonical_hash(
        P1_SYSTEM_PROMPT
        if p1
        else P2_SYSTEM_PROMPT
        if p2
        else SYSTEM_PROMPT
        + CONTEXT_SYSTEM_SUFFIX
        + TABLE_SYSTEM_SUFFIX
        + (TABLE_ROLE_SYSTEM_SUFFIX if role_resolution else "")
        + (GOAL_ROLE_SYSTEM_SUFFIX if goal_role else "")
        + (ACTOR_ROLE_SYSTEM_SUFFIX if actor_role else "")
        + (PERIOD_ROLE_SYSTEM_SUFFIX if period_role else "")
    )
    if sentence_context:
        envelope["prompt_sha256"] = canonical_hash(SENTENCE_CONTEXT_SYSTEM_PROMPT)
    envelope["table_policy"] = dict(
        policy=TABLE_SOURCE_POLICY,
        role_basis="structural_layout_interpretation",
        lineage=table.lineage,
        focal_table_native_id=table.focal_table_native_id,
        focal_row_number=table.focal_row_number,
        focal_column_number=table.focal_column_number,
        max_table_sources=max_table_sources,
        max_table_chars=max_table_chars,
        verified_sources_only=True,
    )
    return envelope


def validate_preliminary_table_sources(
    claim: Claim,
    graph: CanonicalDocumentGraph,
    response: Mapping[str, Any],
    *,
    tenant_id: str,
    max_table_sources: int = 8,
    max_table_chars: int = 600,
    allow_unverified: bool = False,
) -> PreliminaryClassification:
    """``TABLE_SCHEMA`` counterpart of ``validate_preliminary``; same guarantees.

    The quotable source tuple is RECOMPUTED here from the claim and the graph
    with the identical deterministic policy the envelope used, so a model cannot
    widen its own index space: an index the server did not offer is refused.
    Every dimension quote is then restored through the unchanged
    ``_literal_dimension_ref``, which re-runs source verification and rejects
    anything not verified. ``validate_preliminary`` itself is untouched, so
    historical responses keep replaying under their original validator.
    """
    sources = _sources(claim, graph, tenant_id, allow_unverified=allow_unverified)
    table = table_structural_sources(
        graph,
        sources,
        tenant_id=tenant_id,
        max_sources=max_table_sources,
        max_chars=max_table_chars,
    )
    quotable = (*sources, *(item.ref for item in table.verified))
    if not isinstance(response, Mapping) or set(response) != _FIELDS:
        raise DomainValidationError("invalid preliminary fields; grades are prohibited")
    confidence, category = response["track_confidence"], response["safe_harbor_category"]
    if category is not None and (
        not isinstance(category, str) or category not in SAFE_HARBOR_CATEGORIES
    ):
        raise DomainValidationError("invalid preliminary safe harbor category")
    if response["track"] is None:
        if confidence is not None:
            raise DomainValidationError("unresolved track requires null confidence")
        track = None
        if response["claim_id"] != claim.claim_id:
            raise DomainValidationError("preliminary claim mismatch")
    else:
        if (
            type(confidence) not in (int, float)
            or not 0 <= confidence <= 1
            or not isfinite(confidence)
        ):
            raise DomainValidationError("invalid preliminary confidence")
        track = validate_track_candidates(
            (claim,),
            [{key: response[key] for key in ("claim_id", "track", "safe_harbor_category")}],
        )[0]
    raw_dimensions = response["dimensions"]
    if (
        not isinstance(raw_dimensions, Mapping)
        or not {"entity", "metric", "reporting_period"} <= raw_dimensions.keys()
    ):
        raise DomainValidationError("required preliminary dimension roles missing")
    dimensions: dict[str, SourceRef | None] = {}
    for name, span in raw_dimensions.items():
        if span is None:
            dimensions[name] = None
            continue
        dimensions[name] = _literal_dimension_ref(
            span,
            quotable,
            graph,
            tenant_id=tenant_id,
            allow_offsets=True,
            allow_unverified=allow_unverified,
        )
    return PreliminaryClassification(track, ClaimContext(claim, dimensions), confidence, category)


def _literal_dimension_ref(
    span: Mapping[str, Any],
    sources: tuple[SourceRef, ...],
    graph: CanonicalDocumentGraph,
    *,
    tenant_id: str,
    allow_offsets: bool,
    allow_unverified: bool = False,
) -> SourceRef | None:
    """Restore one model-selected, unique literal quote to trusted provenance."""
    allowed = ({"source_index", "quote"}, {"source_index", "start", "end", "quote"})
    if not isinstance(span, Mapping) or set(span) not in (
        allowed if allow_offsets else allowed[:1]
    ):
        raise DomainValidationError("invalid preliminary source span")
    index, quote = span["source_index"], span["quote"]
    if type(index) is not int or not 0 <= index < len(sources) or not isinstance(quote, str):
        raise DomainValidationError("invalid preliminary source selection")
    if "start" in span:
        start, end = span["start"], span["end"]
    else:
        start = sources[index].quote.find(quote)
        if not quote or start < 0 or start != sources[index].quote.rfind(quote):
            raise DomainValidationError("preliminary quote absent or ambiguous")
        end = start + len(quote)
    if (
        any(type(value) is not int for value in (index, start, end))
        or not 0 <= start < end <= len(sources[index].quote)
        or sources[index].quote[start:end] != quote
    ):
        raise DomainValidationError("preliminary span outside literal claim source")
    source = sources[index]
    ref = verify_source_ref(
        replace(
            source,
            char_start=source.char_start + start,
            char_end=source.char_start + end,
            quote=quote,
        ),
        graph,
        tenant_id=tenant_id,
    )
    if ref.verification_state != "verified":
        if allow_unverified:
            return None
        raise DomainValidationError("preliminary dimension validation required")
    return ref


def validate_preliminary(
    claim: Claim,
    graph: CanonicalDocumentGraph,
    response: Mapping[str, Any],
    *,
    tenant_id: str,
    allow_unverified: bool = False,
) -> PreliminaryClassification:
    sources = _sources(claim, graph, tenant_id, allow_unverified=allow_unverified)
    if not isinstance(response, Mapping) or set(response) != _FIELDS:
        raise DomainValidationError("invalid preliminary fields; grades are prohibited")
    confidence, category = response["track_confidence"], response["safe_harbor_category"]
    if category is not None and (
        not isinstance(category, str) or category not in SAFE_HARBOR_CATEGORIES
    ):
        raise DomainValidationError("invalid preliminary safe harbor category")
    if response["track"] is None:
        if confidence is not None:
            raise DomainValidationError("unresolved track requires null confidence")
        track = None
        if response["claim_id"] != claim.claim_id:
            raise DomainValidationError("preliminary claim mismatch")
    else:
        if (
            type(confidence) not in (int, float)
            or not 0 <= confidence <= 1
            or not isfinite(confidence)
        ):
            raise DomainValidationError("invalid preliminary confidence")
        track = validate_track_candidates(
            (claim,),
            [{key: response[key] for key in ("claim_id", "track", "safe_harbor_category")}],
        )[0]
    raw_dimensions = response["dimensions"]
    if (
        not isinstance(raw_dimensions, Mapping)
        or not {"entity", "metric", "reporting_period"} <= raw_dimensions.keys()
    ):
        raise DomainValidationError("required preliminary dimension roles missing")
    dimensions: dict[str, SourceRef | None] = {}
    for name, span in raw_dimensions.items():
        if span is None:
            dimensions[name] = None
            continue
        dimensions[name] = _literal_dimension_ref(
            span,
            sources,
            graph,
            tenant_id=tenant_id,
            allow_offsets=True,
            allow_unverified=allow_unverified,
        )
    return PreliminaryClassification(track, ClaimContext(claim, dimensions), confidence, category)
