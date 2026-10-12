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


def project_decision(decision, *, elements=(), profile=None):
    """A reachable floor is a lower bound with open elements, not an absence vote."""
    result = decision.to_api_dict()
    grade = decision.evidence_grade or decision.grade_floor
    projection = dict(
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

    if profile in ("hf1-v1", "dec24-v1", "k2-v1"):
        projection["gap_ids"] = list(decision.gap_ids)
    return projection


def provisional_result(
    runs,
    packet,
    rulepack,
    context,
    *,
    range_profile=False,
    profile=None,
    semantic_policy=None,
    original=None,
):
    if semantic_policy is not None:
        from proofops.application.tagging.semantic_admission import guard_runs, validate_policy

        validate_policy(semantic_policy)
        runs = guard_runs(
            runs,
            policy=semantic_policy,
            claim_quote=" ".join(r["quote"] for r in packet.to_dict()["claim_source_refs"]),
        )
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
    from proofops.application.tagging.k10_contract import SEMANTIC_POLICY as K10_POLICY
    from proofops.application.tagging.k10_contract import SEMANTIC_V2_POLICY as K10_V2_POLICY
    from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_POLICY

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
    estimate_evidence = []
    if semantic_policy is not None:
        from proofops.application.tagging.semantic_admission import estimate_refs

        estimate_evidence = estimate_refs(data, original, policy=semantic_policy)
    from proofops.application.tagging.k4_contract import SEMANTIC_POLICY, scope3_evidence

    scope3_refs = (
        scope3_evidence(data, original)
        if semantic_policy in (SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY)
        else []
    )
    if semantic_policy in (Q1_POLICY, K10_POLICY, K10_V2_POLICY):
        from proofops.application.tagging.q1_contract import forecast_evidence

        forecast_refs = forecast_evidence(data, original)
        if forecast_refs:
            from proofops.domain.provenance import canonical_hash

            return empty_provisional("Q1_FORWARD_LOOKING_CATEGORY_REVIEW") | dict(
                elements=elements,
                grade_range=None,
                grade_basis="retag_required",
                display_type="hold",
                display="미래 전망 · 가정·시나리오 검토 필요",
                hold_reasons=[
                    "미래 전망의 일반 성과등급 보류",
                    "세이프하버 범주·가정·한계 확인 필요",
                ],
                track=data["track"],
                safe_harbor_category=data.get("safe_harbor_category"),
                safe_harbor_candidate="forward_looking",
                gap_ids=["GAP-001", "GAP-002"],
                forecast_evidence_refs=forecast_refs,
                semantic_policy_sha256=canonical_hash(semantic_policy),
                semantic_hash=canonical_hash(
                    dict(packet=packet.packet_sha256, policy=semantic_policy, refs=forecast_refs)
                ),
            )
    headers = Counter(
        run.guarded.superlative_quote for run in ordered if run.guarded is not None
    ).most_common(1)
    if not headers or headers[0][1] < 2:
        reason = "SUPERLATIVE_UNRESOLVED"
        if (
            profile in ("hf1-v1", "dec24-v1", "k2-v1")
            and sum(run.guarded is not None for run in ordered) < 2
        ):
            reason = (
                "CITATION_REPLICAS_UNRESOLVED"
                if any(
                    any(e.startswith("TAGGING_EVIDENCE_ID_") for e in run.errors) for run in ordered
                )
                else "REPLICA_HEADER_UNRESOLVED"
            )
        early = empty_provisional(reason) | dict(elements=elements)
        if scope3_refs:
            early.update(
                display_type="hold",
                display="판정 보류",
                hold_reasons=["Scope 3 · 산정 근거 확인 필요", "태깅 불일치"],
                grade_basis="scope3_calculation_hold",
                grade_range=None,
                scope3_evidence_refs=scope3_refs,
            )
        return early
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
        "emissions_estimate" if estimate_evidence else data.get("safe_harbor_category"),
        headers[0][0],
        first.product_variant,
    )
    result = project_decision(evaluate(tags, context, rulepack), elements=elements, profile=profile)
    if semantic_policy is not None:
        from proofops.domain.provenance import canonical_hash

        result = result | dict(
            semantic_policy_sha256=canonical_hash(semantic_policy),
            semantic_hash=canonical_hash(
                dict(
                    decision=result["semantic_hash"],
                    policy=semantic_policy,
                    estimate_evidence=estimate_evidence,
                )
            ),
        )
        if estimate_evidence:
            result.update(
                evidence_grade=None,
                label=None,
                grade_range=None,
                grade_basis="estimate_hold",
                display_type="hold",
                display="추정치 · 산정 근거 확인 필요",
                reason="DEC24_EMISSIONS_ESTIMATE_REVIEW",
                gap_ids=["GAP-001"],
                hold_reasons=["추정치 · 산정 근거 확인 필요"],
                estimate_evidence_refs=estimate_evidence,
            )
        elif scope3_refs:
            result.update(
                evidence_grade=None,
                label=None,
                grade_range=None,
                grade_basis="scope3_calculation_hold",
                display_type="hold",
                display="판정 보류",
                reason="K4_SCOPE3_CALCULATION_REVIEW",
                hold_reasons=["Scope 3 · 산정 근거 확인 필요"],
                scope3_evidence_refs=scope3_refs,
            )
        from proofops.application.tagging.k1_semantics import POLICY as K1_POLICY
        from proofops.application.tagging.k1_semantics import track_requires_review

        claim_quote = " ".join(r["quote"] for r in data["claim_source_refs"])
        if (
            semantic_policy in (SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY)
            and data["track"] == "goal"
            and original
        ):
            from types import SimpleNamespace

            from proofops.application.ingest.j7_split import goal_requires_retag
            from proofops.domain.values import SourceRef

            claim_view = SimpleNamespace(
                tenant_id=data["tenant_id"],
                source_refs=tuple(SourceRef(**r) for r in data["claim_source_refs"]),
            )
            if goal_requires_retag(claim_view, original):
                result.update(
                    evidence_grade=None,
                    label=None,
                    grade_range=None,
                    grade_basis="retag_required",
                    display_type="hold",
                    display="판정 보류",
                    reason="K4_CONNECTIVE_GOAL_RETAG_REQUIRED",
                    hold_reasons=["이행 문장의 접속절 · 트랙 재태깅 필요"],
                )
        from proofops.application.tagging.k1_semantics import masked_pue

        if semantic_policy in (
            K1_POLICY,
            SEMANTIC_POLICY,
            Q1_POLICY,
            K10_POLICY,
            K10_V2_POLICY,
        ) and (track_requires_review(claim_quote, data["track"]) or masked_pue(claim_quote)):
            wrong_track = track_requires_review(claim_quote, data["track"])
            result.update(
                evidence_grade=None,
                label=None,
                grade_range=None,
                grade_basis="retag_required",
                display_type="hold",
                display="성과지표 · 트랙·범위값 재태깅 필요"
                if wrong_track
                else "PUE 범위값 · 해석 확인 필요",
                reason="K1_PUE_PERFORMANCE_RETAG_REQUIRED"
                if wrong_track
                else "K1_PUE_MASKED_VALUE_REVIEW",
                hold_reasons=[
                    "성과지표 · 트랙·범위값 재태깅 필요"
                    if wrong_track
                    else "PUE 범위값 · 해석 확인 필요"
                ],
            )
    return ensure_range(result, rulepack, tags=tags, context=context) if range_profile else result


def ensure_range(result, rulepack, *, tags=None, context=None):
    """Only the integrated profile fills an empty display slot; confirmed data stays null."""
    if result.get("grade_basis") in {"estimate_hold", "retag_required", "scope3_calculation_hold"}:
        return result
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
