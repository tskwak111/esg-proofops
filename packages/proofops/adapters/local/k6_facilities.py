"""Rebuild K6's supplemental header attestations from the immutable PDF."""

from pdfplumber.utils.exceptions import PdfminerException

from proofops.adapters.local.k4_facilities import restore_facilities
from proofops.application.evidence.span_citations import span_verified_graph
from proofops.application.tagging.k4_contract import FACILITY_POLICY
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef


def facility_graph(graph, source, claims, *, tenant_id, policy):
    profile = policy.get("facility_tagging_candidates")
    if profile is None:
        return graph, {}
    if (
        profile != "native-proof-boundary-candidates-k6-v1"
        or policy.get("facility_dimensions_policy") != FACILITY_POLICY
        or policy.get("facility_dimensions_policy_sha256") != canonical_hash(FACILITY_POLICY)
    ):
        raise ValueError("K6_FACILITY_POLICY_MISMATCH")
    try:
        dimensions = restore_facilities(graph, source, claims, tenant_id=tenant_id)
    except PdfminerException:
        if policy.get("auxiliary_native_failure") != "unreadable-no-supplemental-credit-hx6-v1":
            raise
        # No facility source was proved. Keep the original graph and the
        # downstream unresolved dimension; never create an absent/present fact.
        return graph, {}
    refs = tuple(SourceRef(**r) for d in dimensions.values() for r in d["facility"]["source_refs"])
    if not refs:
        return graph, dimensions
    return span_verified_graph(
        graph,
        (*getattr(graph, "verified_spans", ()), *refs),
        canonical_hash(dimensions),
    ), dimensions
