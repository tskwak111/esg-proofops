"""Literal sentence interpretation; focal atoms and evidence authority stay separate."""

import json
import re
import unicodedata
from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.j7_split import _top_level
from proofops.application.ingest.w9_tables import graph_cells, grid
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

TERMINAL = r"[.!?。！？](?=\s|$)"
BULLET = r"(?<!\S)[•▪▶]|\n\s*\n"
SUPERLATIVE = r"(?:업계|국내|세계|반도체\s*업계)\s*(?:최초|최대|최고)|최초로"
CONTINUATION = (
    r"(?:[을를의에]|에서는|으로|위해|하여|통해|하며|하고|함께|ESG|태양광|NDC\)|[,，])\s*$"
)
POLICY = dict(
    profile="literal-sentence-context-k5-v1",
    focal="unchanged-atomic-quote-offsets-identities-and-selection",
    offsets="raw-source-codepoints; explicit-NFC-backmap-for-origin-grid",
    boundary=dict(terminal=TERMINAL, bullet=BULLET, nested="no-cut-inside-brackets-or-quotes"),
    continuation=dict(
        same_page=True,
        max_indent_pt=12,
        min_gap_pt=-2,
        max_gap_pt=12,
        max_parts=3,
        ambiguity="no-join",
        heading_min_chars=60,
        origin="located-canonical-prose; individually-source-checked; no-subject-synthesis",
        incomplete_ending=CONTINUATION,
    ),
    table="one-explicit-origin-cell-and-its-spanned-column-header; no-cross-bullet",
    credit="interpretation-only; no-number-year-element-or-binding-credit",
    superlative=dict(pattern=SUPERLATIVE, admission="verified-context-only; missing-tag-holds"),
    max_chars=2000,
)


def _bounds(text, start, end):
    boundaries = {0, len(text)}
    allowed = _top_level(text)
    for match in re.finditer(TERMINAL + "|" + BULLET, text):
        if match.start() in allowed and match.end() in allowed:
            boundaries.add(match.start() if match[0] in {"•", "▪", "▶"} else match.end())
    left = max(x for x in boundaries if x <= start)
    right = min(x for x in boundaries if x >= end)
    while left < start and text[left].isspace():
        left += 1
    while right > end and text[right - 1].isspace():
        right -= 1
    return left, right


def _ref(block, start, end, graph, *, normalized=False):
    ref = (
        block.source_ref(normalized_char_start=start, normalized_char_end=end)
        if normalized
        else replace(
            block.source_ref(), char_start=start, char_end=end, quote=block.raw_text[start:end]
        )
    )
    # An origin cell can carry literal interpretation without a cell bbox.
    # Keep its location unlocated and its authority candidate; the focal table
    # reference still provides the original page/region for the reader.
    if ref.location_quality == "unlocated" and block.kind == "table_cell":
        candidate = block.candidates[block.winner]
        if block.quality in ("verified", "unverified") and any(
            batch.tenant_id == graph.tenant_id
            and batch.document_version_id == graph.document_version_id
            and batch.parse_manifest_id == graph.parse_manifest_id
            and batch.source_sha256 == graph.source_sha256
            and candidate in batch.blocks
            for batch in graph.candidates
        ):
            return replace(ref, verification_state="candidate")
    return _check(ref, graph)


def _check(ref, graph):
    checked = verify_source_ref(ref, graph, tenant_id=graph.tenant_id)
    if checked.verification_state != "rejected":
        return checked
    # Check the same tenant/artifact/raw-offset/geometry chain for interpretation
    # candidates. This temporary structural view grants no source authority: the
    # original graph is unchanged and the returned reference stays candidate.
    block = next((b for b in graph.blocks if b.source_id == ref.source_id), None)
    if block is not None and block.quality == "unverified":
        structural = replace(
            graph,
            blocks=tuple(replace(b, quality="verified") if b == block else b for b in graph.blocks),
        )
        literal = verify_source_ref(ref, structural, tenant_id=graph.tenant_id)
        if literal.verification_state == "verified":
            return replace(literal, verification_state="candidate")
    return checked


def _prose(block):
    return (
        block.winner is not None
        and block.bbox is not None
        and block.quality in ("verified", "unverified")
        and (block.kind == "paragraph" or block.kind == "heading" and len(block.raw_text) >= 60)
    )


def _neighbour(block, graph, *, before):
    choices = []
    for candidate in graph.blocks:
        if candidate.source_id == block.source_id or not _prose(candidate):
            continue
        if candidate.page_num != block.page_num or abs(candidate.bbox[0] - block.bbox[0]) > 12:
            continue
        left, right = (candidate, block) if before else (block, candidate)
        if right.bbox[1] <= left.bbox[1] or not -2 <= right.bbox[1] - left.bbox[3] <= 12:
            continue
        if re.search(TERMINAL + r"\s*$", left.raw_text) or re.match(r"\s*[•▪▶]", right.raw_text):
            continue
        if not re.search(CONTINUATION, left.raw_text):
            continue
        choices.append(candidate)
    return choices[0] if len(choices) == 1 else None


def _table_refs(block, focal, graph):
    try:
        rows = grid(block.normalized_text, graph_cells(block, graph))
    except ValueError:
        return []
    entries = [e for row in rows for e in row["entries"] if e["cell"]]
    focal_start = len(unicodedata.normalize("NFC", block.raw_text[: focal.char_start]))
    focal_end = len(unicodedata.normalize("NFC", block.raw_text[: focal.char_end]))
    matches = [e for e in entries if e["start"] <= focal_start < focal_end <= e["end"]]
    if len(matches) != 1:
        return []
    entry = matches[0]
    cells = {b.source_id: b for b in graph.blocks}
    start, end = _bounds(entry["text"], focal_start - entry["start"], focal_end - entry["start"])
    # A cell's introductory label belongs to its first bullet, never its next bullet.
    if not re.search(BULLET, entry["text"][:start]):
        start = 0
    refs = []
    for header in rows[0]["entries"]:
        c = header["cell"]
        if (
            entry["cell"]["row"] > 0
            and c
            and header["text"]
            and c["column"] <= entry["column"] < c["column"] + c["column_span"]
        ):
            hb = cells[c["source_id"]]
            refs.append(_ref(hb, 0, len(hb.raw_text), graph))
    refs.append(_ref(block, entry["start"] + start, entry["start"] + end, graph, normalized=True))
    return refs


def sentence_context(claim, graph):
    if claim.tenant_id != graph.tenant_id or len(claim.source_refs) != 1:
        return None
    focal = claim.source_refs[0]
    checked = _check(focal, graph)
    if checked.verification_state == "rejected":
        return None
    block = next((b for b in graph.blocks if b.source_id == focal.source_id), None)
    if block is None or block.winner is None or block.bbox is None:
        return None
    from proofops.application.ingest.k6_coverage import native_figure_context_blocks

    native_context = native_figure_context_blocks(block, graph)
    if native_context:
        refs = [_ref(b, 0, len(b.raw_text), graph) for b in native_context]
    elif block.kind == "table":
        refs = _table_refs(block, focal, graph)
    elif _prose(block):
        start, end = _bounds(block.raw_text, focal.char_start, focal.char_end)
        parts = [(block, start, end)]
        while len(parts) < POLICY["continuation"]["max_parts"]:
            b, a, z = parts[0]
            neighbour = _neighbour(b, graph, before=True) if a == 0 else None
            if neighbour is None:
                break
            a, z = _bounds(
                neighbour.raw_text,
                len(neighbour.raw_text) - 1,
                len(neighbour.raw_text),
            )
            parts.insert(0, (neighbour, a, z))
        while len(parts) < POLICY["continuation"]["max_parts"]:
            b, a, z = parts[-1]
            neighbour = _neighbour(b, graph, before=False) if z == len(b.raw_text) else None
            if neighbour is None:
                break
            a, z = _bounds(neighbour.raw_text, 0, 1)
            parts.append((neighbour, a, z))
        refs = [_ref(b, a, z, graph) for b, a, z in parts]
    else:
        return None
    if not refs or any(r.verification_state == "rejected" for r in refs):
        return None
    text = "\n".join(r.quote for r in refs)
    if len(text) > POLICY["max_chars"]:
        return None  # never truncate a condition or scope to fit
    return dict(
        policy=POLICY,
        text=text,
        source_refs=[json.loads(canonical_json(asdict(r))) for r in refs],
        verification_state="verified"
        if all(r.verification_state == "verified" for r in refs)
        else "candidate",
        role="parent_paragraph",
        rule_credit=False,
    )


def configured_context(claim, graph, configured):
    """Keep historical K4 behavior; select K5 only by its new frozen policy hash."""
    from proofops.application.ingest.j7_split import CONTEXT_POLICY
    from proofops.application.ingest.j7_split import sentence_context as legacy

    policy = configured.get("sentence_context_policy")
    if policy is None:
        return None
    if policy not in (POLICY, CONTEXT_POLICY) or configured.get(
        "sentence_context_policy_sha256"
    ) != canonical_hash(policy):
        raise ValueError("SENTENCE_CONTEXT_POLICY_MISMATCH")
    return sentence_context(claim, graph) if policy == POLICY else legacy(claim, graph)


def preliminary_context(packet, context):
    """Reuse the existing interpretation wire; these are never evidence candidates."""
    if context is None:
        return packet
    refs = context.get("source_refs") or [context["source_ref"]]
    if len(context["text"]) > packet["context_policy"]["max_context_chars"]:
        if context["policy"] != POLICY:
            return packet  # historical K4 skipped oversized interpretation
        raise ValueError("SENTENCE_CONTEXT_TOO_LARGE")
    packet["untrusted_document_data"]["context_blocks"] = [
        dict(
            context_index=i,
            role="parent_paragraph",
            source_id=r["source_id"],
            page_num=r["page_num"],
            quality="verified"
            if (
                r["verification_state"] == "verified"
                if context["policy"] == POLICY
                else context["verification_state"] == "verified"
            )
            else "unverified",
            text=r["quote"],
            source_ref={k: v for k, v in r.items() if k != "quote"},
        )
        for i, r in enumerate(refs)
    ]
    packet["context_policy"]["whole_blocks_only"] = False
    return packet


def superlative_errors(quote, claim_quote, context):
    verified = context and context["verification_state"] == "verified"
    if quote and quote not in claim_quote and not (verified and quote in context["text"]):
        return ["SUPERLATIVE_SOURCE_INVALID"]
    if context and re.search(SUPERLATIVE, context["text"]) and (not quote or not verified):
        return ["K5_SUPERLATIVE_REQUIRES_RETAG"]
    return []
