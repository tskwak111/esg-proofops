"""E02 opt-in discovery/catalog and advisory M3 matching, pending policy approval.

Native search identifies page bundles only. Catalog verification uses the trusted
graph's existing source verifier. A scoped match is diagnostic, never an element
vote, absence receipt, or publication authority. Historical link policies do not
import this module. Two opinions sharing a page remain separate and unresolved.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict

from proofops.application.assurance import ClaimContext, extract_assurance, match_assurance
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import _require_sha256

VERSION = "assurance-catalog-shadow-v1"
_TITLE = re.compile(
    r"^\s*(?:.{0,100}검증\s*의견서|Independent\s+Assurance\s+Statement|"
    r".{1,70}의\s*\d{4}년도.{0,70}관련)\s*$",
    re.I | re.M,
)
_SCOPE = re.compile(r"검증\s*기준\s*및\s*범위|검증\s*범위|검증범위|^\s*Scope\s*$", re.I | re.M)
_STANDARD = re.compile(r"ISAE\s*3000|ISAE\s*3410|AA1000|ISO\s*14064", re.I)
_END = re.compile(r"(?:일자\s*:|Issue\s+Date\s*:|Signed\s+(?:on|by)|K\s*M\s*R\s*대표이사)", re.I)
_NEXT_SECTION = re.compile(r"GRI\s*(?:Content\s*)?Index|SASB\s*Index|Appendix|부록", re.I)
POLICY = {
    "version": VERSION,
    "title": _TITLE.pattern,
    "scope": _SCOPE.pattern,
    "standard": _STANDARD.pattern,
    "end": _END.pattern,
    "next_section": _NEXT_SECTION.pattern,
    "discovery": "native_only; title+scope+standard; through_next_opinion; signature_not_end",
    "shared_page": "separate_opinions; unresolved_statement_span_boundary",
    "selection": "whole_overlapping_page_group_or_none; preserve_claim_pages; total_union_cap",
    "authority": "shadow_only; no_element_credit; no_publication; approval_required",
}
POLICY_SHA256 = canonical_hash(POLICY)


def _sealed(data, key):
    return data | {key: canonical_hash(data)}


def _check(data, key):
    if (
        not isinstance(data, dict)
        or data.get("policy_sha256") != POLICY_SHA256
        or data.get(key) != canonical_hash({k: v for k, v in data.items() if k != key})
    ):
        raise ValueError(key.upper().replace("_SHA256", "_HASH") + "_MISMATCH")


def discover_bundles(page_texts: Mapping[int, str], *, page_count: int, source_sha256: str):
    """Find bounded opinion candidates, retaining end/continuation uncertainty.

    Repeated navigation titles alone cannot start an opinion. An explicit scope
    and supported standard must follow its title on that physical page. Unknown
    headings/standards stay undiscovered; this is not an exhaustive absence search.
    A signature marker is a proposed end, never proof of semantic completeness.
    """
    _require_sha256("source_sha256", source_sha256)
    if type(page_count) is not int or not 1 <= page_count <= 500:
        raise ValueError("DISCOVERY_PAGE_COUNT_INVALID")
    if not isinstance(page_texts, Mapping) or any(
        type(p) is not int or not 1 <= p <= page_count or not isinstance(t, str)
        for p, t in page_texts.items()
    ):
        raise ValueError("DISCOVERY_TEXT_INVALID")
    starts = []
    for page in range(1, page_count + 1):
        text = page_texts.get(page, "")
        titles = list(_TITLE.finditer(text))
        # Successive headings before one scope describe one opinion. Prefer the
        # last, most specific title; a new scope after a later title starts another.
        for i, title in enumerate(titles):
            stop = titles[i + 1].start() if i + 1 < len(titles) else len(text)
            tail = text[title.end() : stop]
            if _SCOPE.search(tail) and _STANDARD.search(tail):
                starts.append((page, title.start(), title.group().strip()))
    bundles = []
    for index, (page, offset, title_text) in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        last = next_start[0] if next_start else page_count
        # A date/signature can occur before a continuation table or exclusions.
        # Keep reading to the next opinion. Include its page only when the prefix
        # contains the previous opinion's signature (two opinions on one page).
        if next_start and next_start[0] > page:
            prefix = page_texts.get(next_start[0], "")[: next_start[1]]
            if not _END.search(prefix):
                last -= 1
        reasons, complete, end = [], False, last
        for p in range(page, last + 1):
            text = page_texts.get(p, "")
            first_line = next((s.strip() for s in text.splitlines() if s.strip()), "")
            if complete and p > page and _NEXT_SECTION.fullmatch(first_line):
                end = p - 1
                break
            lower = offset if p == page else 0
            upper = next_start[1] if next_start and p == next_start[0] else len(text)
            segment = text[lower:upper]
            if not segment.strip():
                reasons.append(f"native_page_unreadable:{p}")
            if _END.search(segment):
                complete = True
        if not complete:
            reasons.append("opinion_end_unresolved")
        bundle_pages = list(range(page, end + 1))
        bundle_id = canonical_hash(
            {
                "source_sha256": source_sha256,
                "start_page": page,
                "start_offset": offset,
                "title": title_text,
                "pages": bundle_pages,
            }
        )
        bundles.append(
            dict(
                bundle_id=bundle_id,
                title=title_text,
                pages=bundle_pages,
                start_page=page,
                start_offset=offset,
                boundary_state="candidate_complete" if complete and not reasons else "incomplete",
                source_quality="unverified",
                reasons=reasons,
            )
        )
    for bundle in bundles:
        shared = sorted(
            set(bundle["pages"])
            & {p for other in bundles if other is not bundle for p in other["pages"]}
        )
        bundle["reasons"].extend(f"shared_boundary_page:{p}" for p in shared)
    return _sealed(
        dict(
            schema=VERSION,
            policy_sha256=POLICY_SHA256,
            source_sha256=source_sha256,
            page_count=page_count,
            discovery_only=True,
            native_text_hashes={
                str(p): canonical_hash(page_texts.get(p, "")) for p in range(1, page_count + 1)
            },
            unreadable_pages=[
                p for p in range(1, page_count + 1) if not page_texts.get(p, "").strip()
            ],
            bundles=bundles,
        ),
        "discovery_sha256",
    )


def select_bundles(discovery, *, claim_pages, union_cap):
    """Whole candidate bundles are prioritized; incomplete discovery stays visible."""
    _check(discovery, "discovery_sha256")
    if (
        type(union_cap) is not int
        or not 1 <= union_cap <= discovery["page_count"]
        or not isinstance(claim_pages, list)
        or not claim_pages
        or any(type(p) is not int or not 1 <= p <= discovery["page_count"] for p in claim_pages)
        or claim_pages != sorted(set(claim_pages))
        or len(claim_pages) > union_cap
    ):
        raise ValueError("BUNDLE_SELECTION_INVALID")
    selected, missing, ids = set(claim_pages), set(), []
    incomplete = False
    handled = set()
    for bundle in discovery["bundles"]:
        if bundle["bundle_id"] in handled:
            continue
        group = [bundle]
        pages = set(bundle["pages"])
        # Sharing a physical page makes parsing indivisible, without joining the
        # opinions' semantic scope, provider, level, or exclusions.
        while True:
            overlapping = [
                b for b in discovery["bundles"] if b not in group and pages & set(b["pages"])
            ]
            if not overlapping:
                break
            group.extend(overlapping)
            pages.update(p for b in overlapping for p in b["pages"])
        handled.update(b["bundle_id"] for b in group)
        if len(selected | pages) <= union_cap:
            selected.update(pages)
            ids.extend(b["bundle_id"] for b in group)
        else:
            missing.update(pages - selected)
            incomplete = True
        incomplete |= any(
            b["boundary_state"] != "candidate_complete" or bool(b["reasons"]) for b in group
        )
    return _sealed(
        dict(
            schema=VERSION,
            policy_sha256=POLICY_SHA256,
            discovery_sha256=discovery["discovery_sha256"],
            claim_pages=list(claim_pages),
            selected_pages=sorted(selected),
            evidence_only_pages=sorted(selected - set(claim_pages)),
            selected_bundle_ids=ids,
            missing_bundle_pages=sorted(missing),
            union_cap=union_cap,
            status="evidence_bundle_incomplete" if incomplete else "candidate_only",
            discovery_only=True,
        ),
        "selection_sha256",
    )


def build_catalog(graph, discovery, *, tenant_id):
    """Catalogue exact verified SourceRefs; search text cannot promote a graph.

    The caller supplies a tenant-authorized graph after parsing/attestation. This
    does not perform I/O or mutate that graph. Missing/ambiguous/unverified opinion
    pages remain unresolved and cannot be used even for a covered shadow match.
    """
    _check(discovery, "discovery_sha256")
    if graph.tenant_id != tenant_id or graph.source_sha256 != discovery["source_sha256"]:
        raise ValueError("CATALOG_IDENTITY_MISMATCH")
    bundles, verified_spans = [], set()
    for bundle in discovery["bundles"]:
        refs, unresolved = [], list(bundle["reasons"])
        for page in bundle["pages"]:
            blocks = [b for b in graph.blocks if b.page_num == page]
            if not blocks:
                unresolved.append(f"parsed_page_missing:{page}")
            for block in blocks:
                try:
                    ref = verify_source_ref(block.source_ref(), graph, tenant_id=tenant_id)
                    refs.append(asdict(ref))
                    if ref.verification_state == "verified":
                        verified_spans.add((ref.source_id, ref.char_start, ref.char_end))
                    else:
                        unresolved.append(f"source_unverified:{block.source_id}")
                except (ValueError, KeyError, TypeError):
                    unresolved.append(f"source_unlocated:{block.source_id}")
        bundles.append(
            bundle
            | dict(
                refs=refs,
                unresolved=sorted(set(unresolved)),
                status="source_verified"
                if refs and not unresolved and bundle["boundary_state"] == "candidate_complete"
                else "unresolved",
            )
        )
    return _sealed(
        dict(
            schema=VERSION,
            policy_sha256=POLICY_SHA256,
            tenant_id=tenant_id,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            original_sha256=graph.source_sha256,
            graph_sha256=canonical_hash(asdict(graph)),
            discovery_sha256=discovery["discovery_sha256"],
            bundles=bundles,
            verified_span_count=len(verified_spans),
            authority="shadow_only",
        ),
        "catalog_sha256",
    )


def match_m3_candidate(catalog, *, graph, claim: ClaimContext, statement):
    """One-opinion, one-replica scope diagnostic. No derived vote is minted.

    ClaimContext dimensions must originate from the validated claim-context builder
    for real use. Their strings alone are not an attestation: this receipt always
    requires claim-dimension binding, a frozen packet, independent three-replica
    receipts and the new policy's approval before any fact could be admitted.
    Synthetic/live provenance remains explicit. There is no confirmation switch.
    """
    _check(catalog, "catalog_sha256")
    identity = (
        graph.tenant_id,
        graph.document_version_id,
        graph.parse_manifest_id,
        graph.source_sha256,
        canonical_hash(asdict(graph)),
    )
    if (
        identity
        != tuple(
            catalog[k]
            for k in (
                "tenant_id",
                "document_version_id",
                "parse_manifest_id",
                "original_sha256",
                "graph_sha256",
            )
        )
        or (claim.tenant_id, claim.document_version_id) != identity[:2]
    ):
        raise ValueError("ASSEMBLY_IDENTITY_MISMATCH")
    reasons = [
        "ASSEMBLY_POLICY_APPROVAL_REQUIRED",
        "CLAIM_DIMENSION_BINDING_REQUIRED",
        "FROZEN_PACKET_AND_INDEPENDENT_3_REPLICA_RECEIPTS_REQUIRED",
    ]
    result, bundle_id = None, None
    if statement is not None:
        if (
            statement.tenant_id,
            statement.document_version_id,
            statement.parse_manifest_id,
            statement.source_sha256,
            statement.graph_sha256,
        ) != identity:
            raise ValueError("ASSEMBLY_STATEMENT_IDENTITY_MISMATCH")
        reproduced = extract_assurance(
            graph,
            statement.source_refs,
            statement.binding,
            tagged_fields=dict(statement.tagged_fields),
            tenant_id=claim.tenant_id,
            statement_id=statement.statement_id,
            model_sha256=statement.model_sha256,
            prompt_sha256=statement.prompt_sha256,
            replicate_id=statement.replicate_id,
        )
        if reproduced != statement:
            raise ValueError("ASSEMBLY_STATEMENT_REPLAY_MISMATCH")
        for bundle in catalog["bundles"]:
            if bundle["status"] == "source_verified" and all(
                any(
                    ref["source_id"] == s.source_id
                    and ref["raw_text_sha256"] == s.raw_text_sha256
                    and ref["char_start"] <= s.char_start < s.char_end <= ref["char_end"]
                    for ref in bundle["refs"]
                )
                for s in statement.source_refs
            ):
                bundle_id = bundle["bundle_id"]
                break
        if bundle_id is None:
            reasons.append("CATALOG_SOURCE_UNRESOLVED")
        else:
            result = match_assurance(statement, claim)
    else:
        reasons.append("STATEMENT_UNAVAILABLE")
    candidate = "present" if result and result.status == "covered" else "unknown"
    return _sealed(
        dict(
            schema="m3-scope-shadow-receipt-v1",
            assembly_policy_sha256=POLICY_SHA256,
            catalog_sha256=catalog["catalog_sha256"],
            graph_sha256=identity[-1],
            tenant_id=claim.tenant_id,
            document_version_id=claim.document_version_id,
            original_sha256=graph.source_sha256,
            claim_id=claim.claim_id,
            claim_dimensions=asdict(claim),
            element_id="M3",
            state="unknown",
            candidate_state=candidate,
            authority="shadow_only",
            review_status="needs_review",
            public_auto_confirmed=False,
            bundle_id=bundle_id,
            scope_match=asdict(result) if result else None,
            raw_llm_votes=[],
            derived_results=[asdict(result)] if result else [],
            statement_sha256=statement.semantic_hash if statement else None,
            replicate_id=statement.replicate_id if statement else None,
            synthetic=statement.synthetic
            if statement
            else any(b.synthetic for b in graph.candidates),
            reasons=reasons,
        ),
        "receipt_sha256",
    )
