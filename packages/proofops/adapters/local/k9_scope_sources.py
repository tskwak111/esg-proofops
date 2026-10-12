"""Supplemental same-paragraph scope spans using the pinned v13 source verifier."""

from dataclasses import asdict, replace
from hashlib import sha256

from proofops.application.evidence.span_citations import span_verified_graph
from proofops.application.tagging.k9_contract import (
    BINDING_POLICY,
    BINDING_V1_POLICY,
    BINDING_V2_POLICY,
    BINDING_V3_POLICY,
    BINDING_V4_POLICY,
    scope_definition_refs,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef


def scope_graph(graph, source, claims, *, tenant_id, run_id, policy):
    if policy.get("local_implementation_binding_policy") not in (
        BINDING_V1_POLICY,
        BINDING_V2_POLICY,
        BINDING_V3_POLICY,
        BINDING_V4_POLICY,
        BINDING_POLICY,
    ):
        raise ValueError("K9_BINDING_POLICY_MISMATCH")
    if tenant_id != graph.tenant_id or sha256(source).hexdigest() != graph.source_sha256:
        raise ValueError("K9_SCOPE_SOURCE_MISMATCH")
    if any(
        (c.tenant_id, c.document_version_id, c.parse_manifest_id, c.source_sha256)
        != (tenant_id, graph.document_version_id, graph.parse_manifest_id, graph.source_sha256)
        for c in claims
    ):
        raise ValueError("K9_SCOPE_SOURCE_MISMATCH")
    candidates = {c.claim_id: scope_definition_refs(c, graph) for c in claims}
    refs = tuple(dict.fromkeys(r for values in candidates.values() for r in values))
    if not refs:
        return graph, {}
    from proofops.adapters.local import upstage_ocr_profile_v13

    # Native text, glyphs, annotations and visible-text/OCR checks stay identical
    # to the run's v13 reader. Only individually verified spans gain authority.
    receipt = upstage_ocr_profile_v13.for_run(run_id).attest_claim_spans(
        graph, source, refs, tenant_id=tenant_id
    )
    approved = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in receipt["records"]
        if r["status"] == "verified"
    )
    scoped = (
        span_verified_graph(
            graph, (*getattr(graph, "verified_spans", ()), *approved), receipt["artifact_sha256"]
        )
        if approved
        else graph
    )
    by_key = {(r.source_id, r.char_start, r.char_end): r for r in approved}
    records = {
        claim_id: dict(
            source_refs=[
                asdict(by_key[(r.source_id, r.char_start, r.char_end)])
                for r in values
                if (r.source_id, r.char_start, r.char_end) in by_key
            ],
            receipt=receipt,
            receipt_sha256=canonical_hash(receipt),
            rule_credit=False,
        )
        for claim_id, values in candidates.items()
        if values
    }
    return scoped, records
