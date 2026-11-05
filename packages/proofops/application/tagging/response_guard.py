"""Post-response source, binding and semantic admission; no transport or billing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from proofops.application.claims import Claim
from proofops.application.evidence.binding import ClaimContext
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.tagging import service
from proofops.application.tagging.contracts import ContextAdmission, TagRun
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.errors import DomainValidationError
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import LlmTags, SourceRef


def guard_response(
    raw_tags: LlmTags,
    claim: Claim,
    accepts_context: ContextAdmission | None,
    accepts_v3: ContextAdmission | None,
    qa2_policy: dict[str, Any],
    run: TagRun,
    track: TrackCandidate,
    context: ClaimContext,
    data: dict[str, Any],
    original: CanonicalDocumentGraph,
    tenant_id: str,
    relation_tags: Mapping[str, Mapping[str, SourceRef | None]],
    rulepack: RulePackSnapshot,
    approved_refs: list[SourceRef],
    source_candidates: dict[str, dict[str, Any]],
    definitions: dict[str, Any],
    sentence_interpretation: dict[str, Any] | None,
    contextual_policy: dict[str, Any] | None,
    v3_policy: dict[str, Any] | None,
    local_recovery: dict[str, Any] | None,
    implementation_binding: dict[str, Any] | None,
    structural_policy: dict[str, Any] | None,
    semantic_policy: dict[str, Any] | None,
    r12_quality: bool,
    qt1_tuples: list[dict[str, Any]],
    qt1_links: list[dict[str, Any]],
    tb1_bundles: list[dict[str, Any]],
    allow_edge_whitespace: bool,
) -> TagRun:
    elements, errors, scopes, bindings = [], [], [], []
    if raw_tags.track != track.track or raw_tags.safe_harbor_category != track.safe_harbor_category:
        errors.append("TRACK_CATEGORY_CHANGED")
    if "sentence_context" in data:
        from proofops.application.ingest.k5_context import superlative_errors

        errors.extend(
            superlative_errors(raw_tags.superlative_quote, claim.quote, sentence_interpretation)
        )
    elif raw_tags.superlative_quote and raw_tags.superlative_quote not in claim.quote:
        errors.append("SUPERLATIVE_SOURCE_INVALID")
    for element in raw_tags.elements:
        model_element = element
        table_selected = False
        tb1_selected = False
        qt1_table_selected = baseline_selected = False
        if data.get("table_evidence_policy", {}).get("profile") in (
            "table-selected-evidence-pb2-v1",
            "table-selected-evidence-k4-v1",
            "table-selected-evidence-k7-v1",
        ):
            from proofops.application.tagging.pb2_table_evidence import (
                OBSERVED_POLICY,
                POLICY,
                ROW_UNIT_POLICY,
                prepare_element,
            )

            if data["table_evidence_policy"] not in (
                POLICY,
                ROW_UNIT_POLICY,
                OBSERVED_POLICY,
            ):
                raise DomainValidationError("table evidence policy mismatch")
            element, table_selected = prepare_element(
                element,
                claim,
                original,
                tenant_id=tenant_id,
                policy=data["table_evidence_policy"],
            )
        if contextual_policy is not None and not table_selected:
            from proofops.application.tagging.qt2_context import prepare_table

            element, table_selected = prepare_table(element, claim, original, tenant_id=tenant_id)
        if qt1_tuples:
            from proofops.application.tagging.qt1_tuples import (
                prepare_element as qt1_prepare,
            )

            selected_element, qt1_table_selected = qt1_prepare(model_element, qt1_tuples)
            if qt1_table_selected:
                element = selected_element
            table_selected |= qt1_table_selected
        if qt1_links:
            from proofops.application.tagging.qt1_baseline import (
                prepare_element as baseline_prepare,
            )

            element, baseline_selected = baseline_prepare(element, qt1_links)
        if tb1_bundles:
            from proofops.application.tagging.tb1_table_bundles import (
                prepare_element as tb1_prepare,
            )

            selected_element, tb1_selected = tb1_prepare(model_element, tb1_bundles)
            if tb1_selected:
                element = selected_element
            table_selected |= tb1_selected
        state = element.state
        if tb1_bundles and state == "present" and not tb1_selected:
            from proofops.application.tagging.tb1_table_bundles import ELEMENTS, bundle_refs

            tb1_ids = {item["table_id"] for item in tb1_bundles} | {
                r["source_id"] for item in tb1_bundles for r in bundle_refs(item)
            }
            if element.element_id in ELEMENTS and any(
                r.source_id in tb1_ids for r in model_element.evidence_refs
            ):
                # A rejected bundle cannot bypass its row/column gates
                # through a legacy local-span or single-cell binding.
                state = "unknown"
        binding_reasons: list[str] = []
        if implementation_binding is not None and element.element_id == "G4" and state == "present":
            from proofops.application.tagging.k9_contract import g4_complete

            if not g4_complete(element, context, original, policy=implementation_binding):
                state = "unknown"
        scope_reason = service.scope_rejection_reason(
            element.element_id,
            element.evidence_refs,
            rulepack=rulepack,
            original=original,
            policy=element.reason_code,
        )
        if state == "present" and scope_reason:
            state = "unknown"
        refs = []
        scope_set = set()
        if state == "present":
            for source in element.evidence_refs:
                if implementation_binding is not None and element.element_id != "G4":
                    from proofops.application.tagging.k9_contract import (
                        scope_definition_refs,
                    )

                    if any(
                        r.source_id == source.source_id
                        and r.char_start <= source.char_start < source.char_end <= r.char_end
                        for r in scope_definition_refs(claim, original)
                    ):
                        state = "unknown"
                        break
                candidate = source_candidates.get(source.source_id)
                contained = any(
                    s.source_id == source.source_id
                    and s.char_start <= source.char_start < source.char_end <= s.char_end
                    for s in approved_refs
                )
                if (
                    not candidate
                    or not contained
                    or element.element_id not in candidate["allowed_elements"]
                    or candidate["source_scope"]
                    not in definitions[element.element_id]["source_scopes"]
                    and not (baseline_selected or qt1_table_selected or tb1_selected)
                ):
                    state = "unknown"
                    if r12_quality:
                        binding_reasons.append("evidence_catalog_rejected")
                    break
                verified = service.verify_source_ref(source, original, tenant_id=tenant_id)
                if verified.verification_state != "verified":
                    state = "unknown"
                    if r12_quality:
                        binding_reasons.append("source_unverified")
                    break
                if (
                    not table_selected
                    and not baseline_selected
                    and not (
                        contextual_policy is not None
                        and cast(ContextAdmission, accepts_context)(
                            context,
                            verified,
                            original,
                            tenant_id=tenant_id,
                            element_id=element.element_id,
                            relation_tags=service.relation_tags_for(verified, relation_tags),
                        )
                    )
                    and not (
                        v3_policy is not None
                        and cast(ContextAdmission, accepts_v3)(
                            context,
                            verified,
                            original,
                            tenant_id=tenant_id,
                            element_id=element.element_id,
                            relation_tags=service.relation_tags_for(verified, relation_tags),
                        )
                    )
                    and service.accept_binding(
                        context,
                        verified,
                        service.relation_tags_for(verified, relation_tags),
                        original=original,
                        tenant_id=tenant_id,
                        rulepack=rulepack,
                        element_id=element.element_id,
                        local_value_identity=local_recovery is not None,
                        local_binding_policy=implementation_binding,
                        structural_policy=structural_policy,
                        allow_edge_whitespace=allow_edge_whitespace,
                        diagnostics=binding_reasons if r12_quality else None,
                    )
                    != "accepted"
                ):
                    state = "unknown"
                    break
                refs.append(verified)
                if baseline_selected:
                    from proofops.domain.rules.qt1_baseline import SOURCE_SCOPE

                    scope_set.add(SOURCE_SCOPE)
                else:
                    scope_set.add(
                        "same_table"
                        if qt1_table_selected or tb1_selected
                        else candidate["source_scope"]
                    )
            if local_recovery is not None and state == "present":
                from proofops.application.tagging.k2_recovery import recover_value

                element, refs = recover_value(element, refs, claim, original, tenant_id=tenant_id)
            if data.get("selected_quantity_policy") is not None and state == "present":
                from proofops.application.tagging.k4_contract import (
                    VALUE_POLICY,
                    recover_selected_quantities,
                )

                if data["selected_quantity_policy"] != VALUE_POLICY:
                    raise DomainValidationError("K4_VALUE_POLICY_MISMATCH")
                element, refs = recover_selected_quantities(
                    element, refs, claim, original, tenant_id=tenant_id
                )
            if element.normalized_value is None and element.element_id in (
                "G1",
                "G2",
                "G3",
                "G5",
                "P1",
                "P2",
            ):
                state = "unknown"
            if element.normalized_value is not None and not any(
                " ".join(service.normalize("NFC", element.normalized_value).split())
                == " ".join(service.normalize("NFC", source.quote).split())
                for source in refs
            ):
                state = "unknown"
            if element.credited_from is not None and element.credited_from not in {
                ref.source_id for ref in refs
            }:
                state = "unknown"
            # These are outputs of dedicated deterministic services, never LLM votes.
            if element.element_id in ("P4", "P6") or not refs:
                state = "unknown"
        elif state in ("absent", "not_applicable"):
            state = "unknown"
        semantic_reason = None
        if semantic_policy is not None and state == "present":
            from proofops.application.tagging.semantic_admission import guard_element

            admitted = guard_element(
                service.replace(element, evidence_refs=tuple(refs)),
                policy=semantic_policy,
                claim_quote=claim.quote,
            )
            if admitted.state != "present":
                state, semantic_reason = admitted.state, admitted.reason_code
        if contextual_policy is not None and state == "present":
            from proofops.application.tagging.qt2_context import guard as contextual_guard

            admitted = contextual_guard(service.replace(element, evidence_refs=tuple(refs)))
            if admitted.state != "present":
                state, semantic_reason = admitted.state, admitted.reason_code
        if structural_policy == qa2_policy and state == "present":
            from proofops.application.tagging.q1_contract import (
                future_implementation_guard,
            )

            admitted = future_implementation_guard(
                service.replace(element, evidence_refs=tuple(refs)),
                claim_quote=claim.quote,
            )
            if admitted.state != "present":
                state, semantic_reason = admitted.state, admitted.reason_code
        if v3_policy is not None and state == "present":
            from proofops.application.tagging.v3_dec92 import guard as v3_guard

            admitted = v3_guard(
                service.replace(element, evidence_refs=tuple(refs)), claim_quote=claim.quote
            )
            if admitted.state != "present":
                state, semantic_reason = admitted.state, admitted.reason_code
        if element.element_id == "P6" and element.state in ("present", "conflict"):
            # Both agreement AND contradiction require the numeric service.
            # Retain the raw vote and citations for review, never a model verdict.
            state = "unknown"
            errors.append("DETERMINISTIC_CHECK_REQUIRED:P6")
        if state in ("unknown", "conflict"):
            errors.append(f"UNRESOLVED:{element.element_id}")
            errors.extend(f"UNRESOLVED:{element.element_id}:{reason}" for reason in binding_reasons)
            if scope_reason:
                errors.append(f"{scope_reason}:{element.element_id}")
        scope = next(
            (
                scope
                for scope in (
                    "qt1_maintenance_baseline_v1",
                    "global_bound",
                    "same_table",
                    "local_claim",
                )
                if scope in scope_set
            ),
            "local_claim",
        )
        scopes.append((element.element_id, scope))
        bindings.append(
            (
                element.element_id,
                service.canonical_hash(
                    {
                        key: source.quote if source else None
                        for key, source in context.dimensions.items()
                    }
                ),
            )
        )
        elements.append(
            service.replace(
                element,
                state=state,
                evidence_refs=tuple(refs) if state == "present" else element.evidence_refs,
                normalized_value=element.normalized_value if state == "present" else None,
                credited_from=element.credited_from if state == "present" else None,
                reason_code=semantic_reason or scope_reason or binding_reasons[0]
                if (semantic_reason or scope_reason or binding_reasons) and state == "unknown"
                else element.reason_code,
            )
        )
    guarded_tags = service.replace(raw_tags, elements=tuple(elements))
    return service.replace(
        run,
        guarded=guarded_tags,
        status="needs_review" if errors else "succeeded",
        errors=tuple(errors),
        source_scopes=tuple(scopes),
        binding_hashes=tuple(bindings),
    )
