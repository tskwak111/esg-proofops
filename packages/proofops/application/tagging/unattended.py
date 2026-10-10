"""Read-only PT1 projections. These inputs never become a confirmed revision."""

from collections import Counter
from dataclasses import asdict

from proofops.application.tagging.consensus import form_consensus
from proofops.domain.rules.engine import MAPPINGS, ConfirmedFact, ConfirmedTags, evaluate

PROFILE = "unattended-v1"


def source_status(claim):
    verified = claim.source_quality == "verified"
    return dict(
        status="verified" if verified else "unverified",
        reason=None if verified else "SOURCE_VALIDATION_REQUIRED:" + claim.source_quality,
        display="원문 확인" if verified else "원문 확인 필요",
    )


def empty_provisional(reason):
    return dict(
        evidence_grade=None,
        label=None,
        decision_status="provisional",
        display="잠정·미확정",
        reason=reason,
        elements=[],
        grade_basis=None,
    )


def project_decision(decision, *, elements=()):
    """A reachable floor is a lower bound with open elements, not an absence vote."""
    result = decision.to_api_dict()
    grade = decision.evidence_grade or decision.grade_floor
    return dict(
        evidence_grade=grade,
        label=decision.label if decision.evidence_grade else None,
        decision_status="provisional",
        display="잠정·미확정",
        grade_basis="rule_result"
        if decision.evidence_grade
        else "reachable_floor"
        if grade
        else None,
        grade_range=result["grade_range"],
        reason=decision.decision_status,
        elements=list(elements),
        unresolved_elements=list(decision.unresolved_elements),
        rule_pack_sha256=decision.rule_pack_sha256,
        semantic_hash=decision.semantic_hash,
    )


def provisional_result(runs, packet, rulepack, context, *, range_profile=False):
    # Reuse the strict provenance/independent-replica validation, never its confirmation.
    form_consensus(
        runs,
        packet=packet,
        rulepack=rulepack,
        tenant_id=context.tenant_id,
        tag_revision=1,
        profile="partial-facts-v2",
    )
    provider_ids = [
        run.usage.provider_request_id for run in runs if run.usage and run.usage.provider_request_id
    ]
    if len(provider_ids) != len(set(provider_ids)):
        return empty_provisional("PROVIDER_RESPONSE_REPLAY")
    data = packet.to_dict()
    ordered = sorted(runs, key=lambda run: run.replicate_id)
    facts, elements = [], []
    for eid in data["allowed_elements"]:
        votes = []
        for run in ordered:
            if (
                run.usage is None
                or run.usage.status != "succeeded"
                or (not run.synthetic and not run.usage.provider_request_id)
            ):
                continue
            if run.guarded is None or any(
                not error.startswith("UNRESOLVED:") and error != "DETERMINISTIC_CHECK_REQUIRED:P6"
                for error in run.errors
            ):
                continue
            if (run.guarded.track, run.guarded.safe_harbor_category) != (
                data["track"],
                data.get("safe_harbor_category"),
            ):
                continue
            element = next((e for e in run.guarded.elements if e.element_id == eid), None)
            if element is None:
                continue
            state = element.state
            binding = dict(run.binding_hashes).get(eid)
            if state == "present" and not (
                element.evidence_refs
                and binding
                and all(ref.verification_state == "verified" for ref in element.evidence_refs)
            ):
                state = "unknown"
            if state in ("absent", "not_applicable"):
                state = "unknown"  # bounded model search has no absence authority
            key = (
                state,
                element.normalized_value if state == "present" else None,
                binding if state == "present" else None,
                dict(run.source_scopes).get(eid, "local_claim"),
            )
            votes.append((key, element, run.replicate_id))
        common = Counter(key for key, _, _ in votes).most_common(1)
        key, count = common[0] if common else (("unknown", None, None, "local_claim"), 0)
        state = (
            key[0] if count >= 2 else "conflict" if len(set(v[0] for v in votes)) > 1 else "unknown"
        )
        winners = [(e, replica) for vote, e, replica in votes if vote == key]
        refs = (
            tuple(dict.fromkeys(ref for e, _ in winners for ref in e.evidence_refs))
            if state == "present"
            else ()
        )
        elements.append(
            dict(
                element_id=eid,
                state=state,
                votes=count,
                total_replicas=3,
                provisional=True,
                majority=count == 2,
                replicate_ids=[replica for _, replica in winners],
                evidence_refs=[asdict(ref) for ref in refs],
            )
        )
        for name in MAPPINGS[data["track"]][eid]:
            facts.append(
                ConfirmedFact(
                    name,
                    "present",
                    refs,
                    context.tenant_id,
                    True,
                    True,
                    source_scope=key[3],
                    normalized_value=key[1],
                )
                if state == "present"
                else ConfirmedFact(name, state)
            )
    first = ordered[0]
    headers = Counter(
        run.guarded.superlative_quote for run in ordered if run.guarded is not None
    ).most_common(1)
    if not headers or headers[0][1] < 2:
        return empty_provisional("SUPERLATIVE_UNRESOLVED") | dict(elements=elements)
    tags = ConfirmedTags(
        context.tenant_id,
        data["document_version_id"],
        data["claim_id"],
        data["track"],
        tuple(facts),
        1,
        packet.packet_sha256,
        first.model_sha256,
        first.prompt_sha256,
        tuple(run.semantic_hash for run in ordered),
        rulepack.ontology_version,
        data.get("safe_harbor_category"),
        headers[0][0],
        first.product_variant,
    )
    result = project_decision(evaluate(tags, context, rulepack), elements=elements)
    return ensure_range(result, rulepack, tags=tags, context=context) if range_profile else result


def ensure_range(result, rulepack, *, tags=None, context=None):
    """Only the integrated profile fills an empty display slot; confirmed data stays null."""
    if result.get("evidence_grade"):
        return result | dict(display_type="numeric")
    if (
        result.get("grade_basis") == "counterfactual_range"
        and (result.get("grade_range") or {}).get("rule_pack_sha256") == rulepack.sha256
    ):
        return result
    from proofops.domain.rules.engine import display_grade_range

    grade_range = display_grade_range(rulepack, tags=tags, context=context)
    return result | dict(
        grade_range=grade_range,
        display_type="range",
        display="잠정·범위",
        grade_basis="counterfactual_range",
        label=None,
        reason=result.get("reason") or "UNRESOLVED_EVIDENCE_OR_RULE",
    )
