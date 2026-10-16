"""Consume SC1's replayed per-run inventory. No search, invocation or grading.

The entry point deliberately requires SC1's reader, delivered in its own branch.
A matching hash alone is not a substitute for replay of the three raw receipts.
Links are a new artifact; callers keep existing revisions and apply final gates.
"""

from dataclasses import asdict
from unicodedata import normalize

from proofops.application.evidence.report_level import scope_rejection_reason
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.qt2_context import POLICY_HASH, context_refs, guard
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import LlmElement, SourceRef

_AXES = dict(subject="entity", metric="metric", site="facility", period="reporting_period")


def _key(text):
    return " ".join(normalize("NFC", text).casefold().split())


def _contains(outer, inner):
    return outer.source_id == inner.source_id and (
        outer.char_start <= inner.char_start < inner.char_end <= outer.char_end
    )


def _candidate_element(candidate, context, graph, *, tenant_id, rulepack):
    """SC1 has replayed receipts; QT2 checks claim attribution and semantics."""
    claim = context.claim
    if candidate["element_id"] not in ("P2", "M2", "M4"):
        return None
    if claim.source_quality != "verified" or len(claim.source_refs) != 1:
        return None
    focal = claim.source_refs[0]
    evidence = SourceRef(**candidate["evidence_ref"])

    def checked(r):
        return verify_source_ref(r, graph, tenant_id=tenant_id).verification_state == "verified"

    if not checked(focal) or not checked(evidence):
        return None
    votes = candidate["votes"]
    if set(votes) != {"1", "2", "3"} or any(v["state"] != "present" for v in votes.values()):
        return None
    for vote in votes.values():
        if vote["evidence_ref"] != candidate["evidence_ref"]:
            return None
        for attr, axis in _AXES.items():
            expected = context.dimensions.get(axis)
            raw = vote["attributes"].get(attr)
            if expected is None or raw is None:
                return None
            actual = SourceRef(**raw)
            if candidate["element_id"] != "P2" and not _contains(evidence, actual):
                return None
            if (
                not checked(expected)
                or not checked(actual)
                or _key(expected.quote) != _key(actual.quote)
            ):
                return None
            if not _contains(focal, expected):
                return None
        # Extra claim qualifiers cannot disappear through the four-axis schema.
        if any(k not in _AXES.values() for k in context.dimensions):
            return None
    element_id = candidate["element_id"]
    if scope_rejection_reason(element_id, (evidence,), rulepack=rulepack, original=graph):
        return None
    element = LlmElement(element_id, "present", (evidence,), None, None, None)
    if element_id == "P2":
        from proofops.application.tagging.pb2_table_evidence import observation_sources

        sources = observation_sources(
            claim, graph, tenant_id=tenant_id, recover_row_unit=True, observed_headers=True
        )
        if sources is None or not sources["comparisons"] or not _contains(evidence, sources["row"]):
            return None
        comp = max(sources["comparisons"], key=lambda c: c["year"].quote)
        return LlmElement(
            "P2",
            "present",
            (comp["value"]["ref"], comp["year"]),
            comp["value"]["ref"].quote,
            None,
            None,
        )
    # No long-range route is invented here. SC1's catalog can span all selected
    # pages; unsupported distant references remain held for a future source contract.
    if not _contains(focal, evidence) and not any(
        _contains(r, evidence) for r in context_refs(claim, graph, tenant_id=tenant_id)
    ):
        return None
    admitted = guard(element)
    return admitted if admitted.state == "present" else None


def link_inventory(context, inventory, graph, *, run_id, tenant_id, rulepack):
    """Replay SC1, then return additive QT2 links with the immutable inventory hash."""
    from proofops.application.tagging.analysis_scope import InventoryIndex
    from proofops.application.tagging.element_inventory import replay_inventory

    if isinstance(inventory, InventoryIndex) and inventory.graph is not graph:
        raise ValueError("QT2_INVENTORY_GRAPH_MISMATCH")
    inventory = (
        inventory.inventory
        if isinstance(inventory, InventoryIndex)
        else replay_inventory(inventory, graph)
    )
    selection = inventory["selection"]
    claim = context.claim
    if (
        selection["run_id"] != run_id
        or selection["tenant_id"] != tenant_id
        or (graph.tenant_id, claim.tenant_id, rulepack.tenant_id) != (tenant_id,) * 3
        or (claim.document_version_id, claim.parse_manifest_id, claim.source_sha256)
        != (graph.document_version_id, graph.parse_manifest_id, graph.source_sha256)
    ):
        raise ValueError("QT2_INVENTORY_IDENTITY_MISMATCH")
    links = []
    for candidate in inventory["candidates"]:
        element = _candidate_element(
            candidate, context, graph, tenant_id=tenant_id, rulepack=rulepack
        )
        if element:
            links.append(
                dict(
                    candidate_id=candidate["candidate_id"],
                    element=asdict(element),
                    replica_ids=[1, 2, 3],
                    link_status="accepted",
                )
            )
    body = dict(
        schema="qt2-inventory-links-v1",
        run_id=run_id,
        claim_id=claim.claim_id,
        inventory_sha256=inventory["inventory_sha256"],
        qt2_policy_sha256=POLICY_HASH,
        links=links,
        grade_credit=False,
    )
    return body | dict(qt2_links_sha256=canonical_hash(body))
