"""SY1 technical attribution guard; no semantic approval or absence inference.

New runs pin this policy separately from the immutable model/prompt/rule hashes.
Snapshots without the pin retain their original reader and behavior.
"""

import re
from collections.abc import Mapping

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash

POLICY = {
    "version": "relation-attribution-v1",
    "ownership": "same-page;same-canonical-paragraph-or-verified-literal-block-group",
    "table": "existing-verified-same-row-or-column-sources-only",
    "tokens": "whole-lexical-tokens;complete-korean-particle-suffix-only",
    "particles": ["은", "는", "이", "가", "의", "을", "를", "에", "에서", "으로", "로", "와", "과"],
    "non_product_material_names": ["RE100", "SBTi", "CDP", "GRI"],
    "certification_name_pattern": r"(?i)\bISO\s*\d{4,5}(?:[-:]\d+)?\b",
    "paragraph_breaks": r"\r?\n\s*\r?\n|[•●▪]",
    "block_group_marker": "source_recovery_join=ps1-v1",
    "refused_state": "unknown",
}


def snapshot_policy(snapshot):
    keys = {"relation_attribution_policy", "relation_attribution_policy_sha256"}
    if not keys & snapshot.keys():
        return None
    if (
        not keys <= snapshot.keys()
        or snapshot["relation_attribution_policy"] != POLICY
        or snapshot["relation_attribution_policy_sha256"] != canonical_hash(POLICY)
    ):
        raise ValueError("RELATION_ATTRIBUTION_POLICY_MISMATCH")
    return POLICY


def role_rejection(text, start, end, role):
    """Refuse token fragments and known name/role contradictions, never award roles."""
    if (
        not isinstance(text, str)
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
    ):
        return "RELATION_SPAN_INVALID"
    for token in re.finditer(r"[\w%]+", text):
        if token.start() < start < token.end():
            return "RELATION_TOKEN_FRAGMENT"
        if token.start() < end < token.end():
            suffix = text[end : token.end()]
            if suffix not in POLICY["particles"] or not re.fullmatch(r"[가-힣]+", suffix):
                return "RELATION_TOKEN_FRAGMENT"
    if role in {"product", "material"}:
        quote = text[start:end]
        # Strip only the same complete grammatical suffix admitted above.
        words = set()
        for token in re.findall(r"[\w%]+", quote):
            words.add(token.casefold())
            for suffix in POLICY["particles"]:
                if token.endswith(suffix):
                    words.add(token[: -len(suffix)].casefold())
        if words & {n.casefold() for n in POLICY["non_product_material_names"]} or re.search(
            POLICY["certification_name_pattern"], quote
        ):
            return "RELATION_INITIATIVE_ROLE"
    return None


def _paragraphs(text):
    start = 0
    for match in re.finditer(POLICY["paragraph_breaks"], text):
        if text[start : match.start()].strip():
            yield start, match.start()
        start = match.end()
    if text[start:].strip():
        yield start, len(text)


def literal_scope_rejection(targets, ref, text):
    """Candidate veto core, also replayable offline; never authenticates a source."""
    if not targets or any(
        (r.document_version_id, r.parse_manifest_id)
        != (ref.document_version_id, ref.parse_manifest_id)
        for r in targets
    ):
        return "RELATION_IDENTITY_MISMATCH"
    same_page = [r for r in targets if r.page_num == ref.page_num]
    if not same_page:
        return "RELATION_OTHER_PAGE"
    same_block = [r for r in same_page if r.source_id == ref.source_id]
    if not same_block:
        return "RELATION_OTHER_BLOCK"
    if text is None:
        return "RELATION_SOURCE_UNRESOLVED"
    if any(
        a <= target.char_start < target.char_end <= b and a <= ref.char_start < ref.char_end <= b
        for target in same_block
        for a, b in _paragraphs(text)
    ):
        return None
    return "RELATION_OTHER_PARAGRAPH"


def _same_group(left, right, graph):
    """Only explicit, verified literal paragraph joins; headings are not groups."""
    blocks = {b.source_id: b for b in graph.blocks}
    for parent in graph.blocks:
        if (
            parent.kind != "paragraph"
            or parent.winner is None
            or parent.quality != "verified"
            or POLICY["block_group_marker"] not in parent.candidates[parent.winner].context
        ):
            continue
        parts = [
            blocks[e.target_id]
            for e in graph.edges
            if e.source_id == parent.source_id and e.relation == "derived_from"
        ]
        ids = {parent.source_id, *(p.source_id for p in parts)}
        if left.source_id not in ids or right.source_id not in ids:
            continue
        if len(parts) < 2 or any(
            p.kind != "paragraph"
            or p.winner is None
            or p.bbox is None
            or p.quality != "verified"
            or p.page_num != parent.page_num
            for p in parts
        ):
            continue
        parts.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        if (
            "\n".join(p.raw_text for p in parts) == parent.raw_text
            and len(list(_paragraphs(parent.raw_text))) == 1
        ):
            return True
    return False


def source_rejection(claim, ref, graph, *, tenant_id):
    """Check real provenance and paragraph ownership before proposing any axes."""
    if (claim.tenant_id, graph.tenant_id) != (tenant_id, tenant_id) or (
        claim.document_version_id,
        claim.parse_manifest_id,
        claim.source_sha256,
    ) != (graph.document_version_id, graph.parse_manifest_id, graph.source_sha256):
        return "RELATION_IDENTITY_MISMATCH"
    refs = (*claim.source_refs, ref)
    if not claim.source_refs:
        return "RELATION_SOURCE_UNRESOLVED"
    if any(
        verify_source_ref(r, graph, tenant_id=tenant_id).verification_state != "verified"
        for r in refs
    ):
        return "RELATION_SOURCE_UNRESOLVED"
    targets = [r for r in claim.source_refs if r.page_num == ref.page_num]
    if not targets:
        return "RELATION_OTHER_PAGE"
    blocks = {b.source_id: b for b in graph.blocks}
    reason = literal_scope_rejection(claim.source_refs, ref, blocks[ref.source_id].raw_text)
    if reason is None:
        return None
    for target in targets:
        if target.source_id != ref.source_id and _same_group(target, ref, graph):
            return None
    # Reuse the existing table lineage/coordinate contract. It supplies context,
    # never a role, a page join, or a semantic relationship.
    if blocks[ref.source_id].kind == "table_cell" or any(
        edge.source_id == ref.source_id and edge.relation == "table_parent" for edge in graph.edges
    ):
        from proofops.application.tagging.table_sources import table_structural_sources

        table = table_structural_sources(graph, claim.source_refs, tenant_id=tenant_id)
        if any(item.ref.source_id == ref.source_id for item in table.verified):
            return None
    return reason


def filter_dimensions(claim, dimensions: Mapping, graph, *, tenant_id):
    """Return a new map and safe rejection codes; explicit null stays unresolved."""
    filtered, rejected = dict(dimensions), {}
    blocks = {b.source_id: b for b in graph.blocks}
    for role, ref in dimensions.items():
        if ref is None:
            continue
        reason = source_rejection(claim, ref, graph, tenant_id=tenant_id)
        if reason is None:
            reason = role_rejection(
                blocks[ref.source_id].raw_text, ref.char_start, ref.char_end, role
            )
        if reason is not None:
            filtered[role] = None
            rejected[role] = reason
    return filtered, rejected
