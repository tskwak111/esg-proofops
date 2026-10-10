"""Keep P1 fact selections out of the typed attribution-dimension namespace.

Recognized auxiliary fact fields are retained as diagnostics, never dimensions,
P1 votes or grading facts. All ordinary preliminary/source guards still run.
Unknown dimension names (including grade/label attempts) remain rejected.
"""

from copy import deepcopy
from dataclasses import asdict

from proofops.application.tagging.preliminary import (
    _literal_dimension_ref,
    _sources,
    validate_preliminary_table_sources,
)
from proofops.application.tagging.table_sources import table_structural_sources
from proofops.domain.provenance import canonical_hash

POLICY = dict(
    profile="preliminary-fact-fields-pb2-v1",
    auxiliary_fields=["unit", "value", "quantity"],
    credit="diagnostic-only",
)
POLICY_HASH = canonical_hash(POLICY)


def enabled(claim, graph, analysis_policy):
    if analysis_policy.get("preliminary_fact_fields") != POLICY["profile"]:
        return False
    scope = analysis_policy.get("preliminary_fact_fields_scope")
    if scope is None:
        return True  # Exact earlier PB2 behavior stays replayable.
    if scope != "table_claims":
        raise ValueError("PRELIMINARY_FACT_FIELDS_SCOPE_UNKNOWN")
    ids = {ref.source_id for ref in claim.source_refs}
    return any(b.source_id in ids and b.kind in ("table", "table_cell") for b in graph.blocks)


def validate_preliminary(claim, graph, response, *, tenant_id, allow_unverified=False):
    data = deepcopy(response)
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict):
        return validate_preliminary_table_sources(
            claim, graph, data, tenant_id=tenant_id, allow_unverified=allow_unverified
        ), []
    sources = _sources(claim, graph, tenant_id, allow_unverified=allow_unverified)
    table = table_structural_sources(graph, sources, tenant_id=tenant_id)
    quotable = (*sources, *(item.ref for item in table.verified))
    auxiliary = []
    for name in POLICY["auxiliary_fields"]:
        if name not in dimensions:
            continue
        span = dimensions.pop(name)
        if span is None:
            auxiliary.append(dict(field=name, state="unknown", selection=None))
            continue
        # This enforces the very same numbered-source, exact-offset and tenant
        # gates as the real dimension validator; no reinterpretation of context.
        ref = _literal_dimension_ref(
            span,
            quotable,
            graph,
            tenant_id=tenant_id,
            allow_offsets=True,
            allow_unverified=allow_unverified,
        )
        auxiliary.append(
            dict(
                field=name,
                state=ref.verification_state if ref else "unknown",
                selection=asdict(ref) if ref else span,
                credit="none",
            )
        )
    return validate_preliminary_table_sources(
        claim, graph, data, tenant_id=tenant_id, allow_unverified=allow_unverified
    ), auxiliary
