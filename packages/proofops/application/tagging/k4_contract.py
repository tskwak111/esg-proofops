"""Opt-in R2 repairs: dispatch identity and literal selections, never new votes."""

import re
from dataclasses import replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.k1_semantics import POLICY as K1_POLICY
from proofops.application.tagging.k2_recovery import _NUMBER
from proofops.domain.values import SourceRef

RESPONSE_POLICY = dict(
    profile="dispatch-owned-tag-identity-k4-v1",
    identity="server-request-only; model-does-not-emit-claim-packet-replica",
    retry="no-additional-dispatch; provider-existing-one-retry-within-reservation",
)
VALUE_POLICY = dict(
    profile="selected-local-quantities-k4-v1",
    value="present-only; all-selected-local-literals; unique-quantity-per-citation",
    table_unit="verified-row-subspan-when-cell-has-no-location; no-coordinate-invention",
)
MARKER = r"추정|산정|계산|estimate[d]?|calculat(?:ed|ion)"
SEMANTIC_POLICY = K1_POLICY | dict(
    profile="tagging-semantic-admission-k4-v1",
    estimate_marker=MARKER,
    category="verified-local-or-exact-parent-marker-only",
    scope3="independent-calculation-review-hold; no-unproven-estimate-category",
)
QUANTITY = re.compile(_NUMBER + r"\s*(?:tCO[₂2](?:eq|e)?|MWh|kWh|GWh|%)(?:/대)?")

FACILITY_LABELS = r"데이터센터\s+각\s+[^\n\t]+|1784|그린팩토리|커넥트원"
FACILITY_POLICY = dict(
    profile="native-column-facility-k4-v1",
    owner="same-parser-grid-and-native-column",
    heading="nearest-preceding-literal-heading; native-above-value",
    credit="source-dimension-for-review-only; no-LLM-vote-or-rule-credit",
    facility_labels=FACILITY_LABELS,
    citation="original-header-cell-when-located; otherwise-exact-table-subspan",
)


def bind_response(payload, request, *, policy):
    if policy != RESPONSE_POLICY:
        raise ValueError("K4_RESPONSE_POLICY_MISMATCH")
    if not isinstance(payload, dict):
        raise ValueError("K4_RESPONSE_OBJECT_REQUIRED")
    if {"claim_id", "packet_sha256", "replicate_id"} & payload.keys():
        raise ValueError("K4_MODEL_IDENTITY_FIELDS_PROHIBITED")
    # This is called by the transport handling THIS dispatch, never by the
    # cross-request cache reader. The original response/echo remains in receipts.
    return payload | {k: request[k] for k in ("claim_id", "packet_sha256", "replicate_id")}


def recover_selected_quantities(element, refs, claim, graph, *, tenant_id):
    if (
        element.state != "present"
        or element.element_id != "P1"
        or element.normalized_value is not None
        or not refs
        or claim.source_quality != "verified"
        or len(claim.source_refs) != 1
    ):
        return element, refs
    own = claim.source_refs[0]
    if any(
        r.source_id != own.source_id
        or not own.char_start <= r.char_start < r.char_end <= own.char_end
        or verify_source_ref(r, graph, tenant_id=tenant_id).verification_state != "verified"
        for r in refs
    ):
        return element, refs
    # Keep multiple facts as one literal contiguous source interval. Never pick
    # the first of two values and silently discard the other one.
    if any(len(list(QUANTITY.finditer(r.quote))) != 1 for r in refs):
        return element, refs
    start, end = min(r.char_start for r in refs), max(r.char_end for r in refs)
    quote = own.quote[start - own.char_start : end - own.char_start]
    quantities = {
        (r.char_start + m.start(), r.char_start + m.end())
        for r in refs
        for m in QUANTITY.finditer(r.quote)
    }
    if len(list(QUANTITY.finditer(quote))) != len(quantities):
        return element, refs
    selected = replace(
        own, char_start=start, char_end=end, quote=quote, verification_state="candidate"
    )
    checked = verify_source_ref(selected, graph, tenant_id=tenant_id)
    if checked.verification_state != "verified":
        return element, refs
    return replace(element, normalized_value=checked.quote), [*refs, checked]


def estimate_evidence(data, graph):
    if data.get("safe_harbor_category") != "emissions_estimate":
        return []
    if graph is None or (data.get("tenant_id"), data.get("document_version_id")) != (
        graph.tenant_id,
        graph.document_version_id,
    ):
        return []
    refs = data.get("claim_source_refs", [])
    checked = [verify_source_ref(SourceRef(**r), graph, tenant_id=graph.tenant_id) for r in refs]
    if not checked or any(r.verification_state != "verified" for r in checked):
        return []
    if any(re.search(MARKER, r.quote, re.I) for r in checked):
        return refs
    blocks = {b.source_id: b for b in graph.blocks}
    # A whole-table marker needs its own verified literal citation; a table's
    # unverified text or another table/page never establishes this category.
    for ref in checked:
        table = blocks[ref.source_id]
        if table.kind != "table":
            continue
        for match in re.finditer(MARKER, table.raw_text, re.I):
            source = table.source_ref(
                normalized_char_start=match.start(), normalized_char_end=match.end()
            )
            if (
                verify_source_ref(source, graph, tenant_id=graph.tenant_id).verification_state
                == "verified"
            ):
                from dataclasses import asdict

                return [asdict(source)]
    return []


def scope3_evidence(data, graph):
    from proofops.application.tagging.k1_semantics import estimate_evidence as old

    return old(data | dict(safe_harbor_category=None), graph)
