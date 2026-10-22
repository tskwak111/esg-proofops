"""Context and element guards run inside the store callback on pinned inputs."""

from __future__ import annotations

from dataclasses import asdict, replace
from functools import partial
from unicodedata import normalize

from proofops.application.evidence.binding import accept_binding, relation_tags_for
from proofops.application.evidence.report_level import POLICIES as REPORT_LEVEL_POLICIES
from proofops.application.evidence.report_level import check_report_level, scope_rejection_reason
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import (
    MAPPINGS,
    ConfirmedFact,
)
from proofops.domain.values import (
    _source_ref_from_dict,
)

from .contracts import ReviewRejected


def validate_context_review(
    inputs,
    body,
    initial,
    *,
    context_review,
    reopen,
    prior_provenance,
    verify_context_sources,
    pinned_run_snapshot,
):
    """Revalidate a supplied or carried context without replacing a numeric result."""
    original_refs = {}
    prior_context = initial.get("claim_context_review") if reopen else None
    context_request = (
        context_review
        if context_review is not None
        else (prior_context.get("request") if isinstance(prior_context, dict) else None)
    )
    context_receipt = None
    if context_request is not None:
        from proofops.application.claim_context_review import review_facility_context

        if body["track"] != "performance":
            raise ReviewRejected("CONTEXT_TRACK_MISMATCH")
        prior_p6 = next((e for e in initial["elements"] if e["element_id"] == "P6"), None)
        frozen_model_conflict = any(
            e.element_id == "P6" and e.state == "conflict"
            for run in inputs.tag_runs
            if run.guarded
            for e in run.guarded.elements
        )
        if prior_p6 and (
            prior_p6["state"] == "present"
            or (prior_p6["state"] == "conflict" and not frozen_model_conflict)
        ):
            raise ReviewRejected("CONTEXT_CANNOT_OVERRIDE_NUMERIC_RESULT")
        try:
            context_receipt = review_facility_context(
                inputs,
                context_request,
                partial(verify_context_sources, pinned_run_snapshot=pinned_run_snapshot)
                if pinned_run_snapshot is not None
                else verify_context_sources,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ReviewRejected("CONTEXT_REVIEW_REJECTED") from exc
        original_refs = {
            canonical_hash(asdict(ref)): ref
            for run in inputs.tag_runs
            if run.guarded
            for e in run.guarded.elements
            if e.element_id == "P6"
            for ref in e.evidence_refs
        }
        if prior_p6 and any(
            canonical_hash(ref) not in original_refs for ref in prior_p6["evidence_refs"]
        ):
            raise ReviewRejected("CONTEXT_CANNOT_OVERRIDE_NUMERIC_RESULT")
        if context_review is None and prior_context is not None:
            if canonical_hash(context_receipt["source_receipt"]) != canonical_hash(
                prior_context["source_receipt"]
            ):
                raise ReviewRejected("CONTEXT_SOURCE_REPLAY_MISMATCH", 409)
            context_receipt["carried_from"] = prior_context.get("carried_from", prior_provenance)
    return context_receipt, original_refs


def validate_elements(
    inputs,
    actor,
    body,
    elements,
    initial,
    *,
    facts,
    definitions,
    context_receipt,
    original_refs,
    verify_context_sources,
    verifier_parameters,
    pinned_run_snapshot,
    verify_source_ref,
):
    """Validate sources/bindings and retain report-level replay receipts."""
    new_facts = []
    checked_elements = []
    report_level_receipts = []
    prior_report_level = {
        item["element_id"]: item for item in initial.get("report_level_review", ())
    }
    page_texts: dict[int, list[str]] | None = None
    for element in elements:
        if element.element_id == "P6" and context_receipt is not None:
            # The caller cannot choose the computed state. No accepted
            # table binding -> unknown, with every old citation retained.
            element = replace(
                element,
                state="unknown",
                normalized_value=None,
                evidence_refs=tuple(original_refs.values()),
                credited_from=None,
                reason_code="NUMERIC_BINDING_REQUIRED",
            )
        names = MAPPINGS[body["track"]][element.element_id]
        previous = [facts.get(name) for name in names]
        scope_reason = scope_rejection_reason(
            element.element_id,
            element.evidence_refs,
            rulepack=inputs.rulepack,
            original=inputs.original,
            policy=element.reason_code,
        )
        if element.state == "present" and scope_reason:
            # Invalid present request cannot change the prior unknown revision.
            raise ReviewRejected(scope_reason)
        report_level = (
            element.state == "present"
            and element.reason_code is not None
            and REPORT_LEVEL_POLICIES.get(element.element_id) == element.reason_code
        )
        graph = inputs.original
        source_receipt = None
        if report_level:
            if verify_context_sources is None:
                raise ReviewRejected("REPORT_LEVEL_SOURCE_REJECTED")
            attestation_refs = element.evidence_refs
            prior = prior_report_level.get(element.element_id)
            prior_element = next(
                (item for item in initial["elements"] if item["element_id"] == element.element_id),
                None,
            )
            carried = (
                prior is not None
                and prior_element is not None
                and prior_element["state"] == element.state
                and prior_element["reason_code"] == element.reason_code
                and prior_element["credited_from"] == element.credited_from
                and tuple(
                    replace(_source_ref_from_dict(ref), verification_state="candidate")
                    for ref in prior_element["evidence_refs"]
                )
                == tuple(
                    replace(ref, verification_state="candidate") for ref in element.evidence_refs
                )
            )
            if carried:
                try:
                    prior_refs = tuple(_source_ref_from_dict(ref) for ref in prior["refs"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ReviewRejected("REPORT_LEVEL_SOURCE_REPLAY_MISMATCH", 409) from exc
                if (
                    prior.get("policy") != element.reason_code
                    or prior.get("credited_from") != element.credited_from
                    or tuple(replace(ref, verification_state="candidate") for ref in prior_refs)
                    != tuple(
                        replace(ref, verification_state="candidate")
                        for ref in element.evidence_refs
                    )
                ):
                    raise ReviewRejected("REPORT_LEVEL_SOURCE_REPLAY_MISMATCH", 409)
                attestation_refs = prior_refs
            try:
                replay = {}
                if carried and "replay_receipt" in verifier_parameters:
                    replay["replay_receipt"] = prior["source_receipt"]
                if carried and "published_tag" in verifier_parameters:
                    replay["published_tag"] = initial
                if pinned_run_snapshot is not None:
                    replay["pinned_run_snapshot"] = pinned_run_snapshot
                graph, source_receipt = verify_context_sources(inputs, attestation_refs, **replay)
            except (ValueError, KeyError, TypeError) as exc:
                raise ReviewRejected("REPORT_LEVEL_SOURCE_REJECTED") from exc
        refs = tuple(
            verify_source_ref(ref, graph, tenant_id=actor.tenant_id)
            for ref in element.evidence_refs
        )
        if any(ref.verification_state != "verified" for ref in refs):
            raise ReviewRejected("SOURCE_REJECTED")
        if report_level:
            receipt = dict(
                element_id=element.element_id,
                policy=element.reason_code,
                refs=[asdict(ref) for ref in attestation_refs],
                credited_from=element.credited_from,
                source_receipt=source_receipt,
            )
            if carried and canonical_hash(prior.get("source_receipt")) != canonical_hash(
                source_receipt
            ):
                raise ReviewRejected("REPORT_LEVEL_SOURCE_REPLAY_MISMATCH", 409)
            report_level_receipts.append(receipt)
        if element.state in ("absent", "not_applicable"):
            if not all(
                f
                and f.state == element.state
                and (element.state != "absent" or f.search_coverage_verified)
                for f in previous
            ):
                raise ReviewRejected("COVERAGE_OR_APPLICABILITY_REQUIRED")
        scope = "local_claim"
        if element.state == "present":
            if element.element_id in ("P4", "P6"):
                # Dedicated assurance/numeric results cannot be typed into existence.
                if not all(
                    f
                    and f.state == "present"
                    and f.evidence_refs == refs
                    and f.normalized_value == element.normalized_value
                    for f in previous
                ):
                    raise ReviewRejected("DETERMINISTIC_CHECK_REQUIRED")
                scope = previous[0].source_scope
            elif (
                element.reason_code is not None
                and REPORT_LEVEL_POLICIES.get(element.element_id) == element.reason_code
            ):
                # User-approved report-level chain (§6 2-4); literal checks only.
                if page_texts is None:
                    page_texts = {}
                    for block in inputs.original.blocks:
                        page_texts.setdefault(block.page_num, []).append(block.raw_text)
                if not check_report_level(
                    element.element_id,
                    element.reason_code,
                    refs,
                    claim_refs=tuple(
                        verify_source_ref(ref, inputs.original, tenant_id=actor.tenant_id)
                        for ref in inputs.context.claim.source_refs
                    ),
                    claim_quote=inputs.context.claim.quote,
                    page_texts=page_texts,
                    credited_from=element.credited_from,
                ):
                    raise ReviewRejected("REPORT_LEVEL_BINDING_REJECTED")
                scope = "global_bound"
            else:
                scopes = []
                for ref in refs:
                    if (
                        accept_binding(
                            inputs.context,
                            ref,
                            relation_tags_for(ref, inputs.relation_tags),
                            original=inputs.original,
                            tenant_id=actor.tenant_id,
                            rulepack=inputs.rulepack,
                            element_id=element.element_id,
                        )
                        != "accepted"
                    ):
                        raise ReviewRejected("BINDING_REJECTED")
                    local = any(
                        s.source_id == ref.source_id
                        and s.char_start <= ref.char_start
                        and ref.char_end <= s.char_end
                        for s in inputs.context.claim.source_refs
                    )
                    scopes.append(
                        "local_claim"
                        if local
                        else (
                            "global_bound"
                            if "global_bound" in definitions[element.element_id]["source_scopes"]
                            else "same_table"
                        )
                    )
                scope = (
                    "global_bound"
                    if "global_bound" in scopes
                    else ("same_table" if "same_table" in scopes else "local_claim")
                )
                value = element.normalized_value
                if element.element_id in ("G1", "G2", "G3", "G5", "P1", "P2") and value is None:
                    raise ReviewRejected("SOURCE_VALUE_REQUIRED")
                if value is not None and not any(
                    " ".join(normalize("NFC", value).split())
                    == " ".join(normalize("NFC", ref.quote).split())
                    for ref in refs
                ):
                    raise ReviewRejected("SOURCE_VALUE_MISMATCH")
            if element.credited_from is not None and element.credited_from not in {
                r.source_id for r in refs
            }:
                raise ReviewRejected("CREDITED_SOURCE_MISMATCH")
        new_facts.extend(
            ConfirmedFact(
                name,
                element.state,
                refs,
                actor.tenant_id,
                element.state == "present",
                element.state == "present",
                element.state == "absent",
                scope,
                element.normalized_value,
            )
            for name in names
        )
        checked_elements.append(asdict(replace(element, evidence_refs=refs)))
    return new_facts, checked_elements, report_level_receipts
