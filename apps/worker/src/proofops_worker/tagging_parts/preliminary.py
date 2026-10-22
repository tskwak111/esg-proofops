"""Preliminary packet and validator, followed by its distinct consensus orchestration."""

from dataclasses import asdict, dataclass, replace

from proofops.application.tagging.preliminary import (
    SENTENCE_CONTEXT_PROFILE,
    SENTENCE_FALLBACK_BASE_PROMPT,
    SENTENCE_FALLBACK_PROFILE,
    SENTENCE_FALLBACK_SYSTEM_PROMPT,
    sentence_context_ready,
    validate_preliminary,
    validate_preliminary_table_sources,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json


@dataclass(frozen=True)
class PreliminaryPacket:
    packet: dict
    context_receipt: dict
    unattended: bool
    table: bool
    pb1: bool
    decision: bool
    cf5: bool
    display_catalog: object


def build_preliminary_packet(self, claim, graph, *, preliminary_request, preliminary_table_request):
    # Preserve conditional runtime reads while keeping packet construction separate.
    unattended = self.snapshot.get("pipeline_profile") in (
        "unattended-v1",
        "finals-unattended-v1",
        "finals-unattended-v2",
        "finals-unattended-j3-v1",
        "finals-unattended-j7-v1",
        "finals-unattended-j8-v1",
    )
    from proofops.application.tagging import cf5_context

    cf5 = cf5_context.enabled(self.snapshot.get("analysis_profile_policy", {}))
    if cf5 and self.preliminary_settings.system_prompt != cf5_context.PRELIMINARY:
        raise ValueError("CF5_CONTEXT_PROMPT_MISMATCH")
    profile = self.preliminary_settings.model_profile
    from proofops.application.tagging.preliminary import CONTEXT_POSITION_ORDER

    position_order = profile in (
        "upstage-preliminary-source-quotes-table-role-v1-position-v1",
        "upstage-preliminary-source-quotes-table-role-v2-p2-position-v1",
    )
    if position_order and self.snapshot.get("position_context_order") != CONTEXT_POSITION_ORDER:
        raise ValueError("PRELIMINARY_CONTEXT_ORDER_MISMATCH")
    p2 = profile in (
        "upstage-preliminary-source-quotes-table-role-v2-p2",
        "upstage-preliminary-source-quotes-table-role-v2-p2-position-v1",
    )
    decision = profile == "preliminary-decision-v1"
    fallback = profile == SENTENCE_FALLBACK_PROFILE
    sentence_context = profile == SENTENCE_CONTEXT_PROFILE or fallback
    compact_pb1 = profile == "upstage-preliminary-source-quotes-pb1-compact-v1"
    pb1 = profile == "upstage-preliminary-source-quotes-actor-role-v3-pb1" or compact_pb1
    actor_role_v2 = profile == "upstage-preliminary-source-quotes-actor-role-v2" or decision or pb1
    actor_role = profile == "upstage-preliminary-source-quotes-actor-role-v1" or actor_role_v2
    goal_role = profile == "upstage-preliminary-source-quotes-goal-role-v1" or actor_role
    role_table = (
        profile
        in (
            "upstage-preliminary-source-quotes-table-role-v1",
            "upstage-preliminary-source-quotes-table-role-v1-position-v1",
        )
        or goal_role
        or p2
    )
    table = (
        profile == "upstage-preliminary-source-quotes-table-v1" or role_table or sentence_context
    )
    if table:
        packet = preliminary_table_request(
            claim,
            graph,
            tenant_id=self.auth.tenant_id,
            sentence_context=sentence_context,
            role_resolution=role_table,
            goal_role=goal_role,
            actor_role=actor_role,
            period_role=actor_role_v2,
            p2=p2,
            position_order=position_order,
            allow_unverified=unattended,
        )
    else:
        packet = preliminary_request(
            claim,
            graph,
            tenant_id=self.auth.tenant_id,
            include_context=profile == "upstage-preliminary-source-quotes-context-v1",
            allow_unverified=unattended,
        )

    if pb1:
        from proofops_agent.upstage_preliminary import PB1_SYSTEM_PROMPT

        if compact_pb1:
            from proofops.application.tagging.pb1_classification import COMPACT_PROMPT

            packet["prompt_sha256"] = canonical_hash(COMPACT_PROMPT)
            from proofops.application.tagging.finals_i4 import K4_PRELIMINARY
            from proofops.application.tagging.k1_semantics import GUIDANCE
            from proofops.application.tagging.k9_contract import PRELIMINARY as K9_PRELIMINARY
            from proofops.application.tagging.q1_contract import PRELIMINARY as Q1_PRELIMINARY
            from proofops.application.tagging.v3_dec92 import PRELIMINARY as V3_PRELIMINARY

            if self.preliminary_settings.system_prompt in (
                COMPACT_PROMPT + "\n" + GUIDANCE,
                K4_PRELIMINARY,
                K9_PRELIMINARY,
                Q1_PRELIMINARY,
                V3_PRELIMINARY,
                cf5_context.PRELIMINARY,
            ):
                packet["prompt_sha256"] = canonical_hash(self.preliminary_settings.system_prompt)
        else:
            packet["prompt_sha256"] = canonical_hash(PB1_SYSTEM_PROMPT)
    if fallback:
        packet["prompt_sha256"] = canonical_hash(SENTENCE_FALLBACK_SYSTEM_PROMPT)
        data = packet["untrusted_document_data"]
        verified_context = []
        for entry in data["context_blocks"]:
            if (
                entry["quality"] == "verified"
                and entry["source_ref"].get("verification_state") == "verified"
            ):
                verified_context.append(entry | {"context_index": len(verified_context)})
            elif entry["source_id"] not in data["omitted_source_ids"]:
                data["omitted_source_ids"].append(entry["source_id"])
        data["context_blocks"] = verified_context
    if self.snapshot.get("analysis_profile_policy", {}).get("sentence_context_policy"):
        from proofops.application.ingest.k5_context import (
            configured_context,
            preliminary_context,
        )

        complete = configured_context(claim, graph, self.snapshot["analysis_profile_policy"])
        packet = preliminary_context(packet, complete)
    response_policy = self.snapshot.get("analysis_profile_policy", {}).get(
        "preliminary_response_policy"
    )
    if response_policy is not None:
        from proofops.application.tagging.k4_contract import RESPONSE_POLICY

        if response_policy != RESPONSE_POLICY:
            raise ValueError("K4_RESPONSE_POLICY_MISMATCH")
        packet["preliminary_response_policy"] = response_policy
    context_receipt = {}
    if cf5:
        packet = cf5_context.preserve_context(packet, claim, graph, receipt=context_receipt)
    packet = self.preliminary_transport.bound_context(packet)
    if not cf5 and self.snapshot.get("analysis_profile_policy", {}).get("sentence_context_policy"):
        from copy import deepcopy

        from proofops.application.ingest.k5_context import POLICY as K5_POLICY

        if complete and complete["policy"] == K5_POLICY:
            expected = preliminary_context(deepcopy(packet), complete)
            if (
                packet["untrusted_document_data"]["context_blocks"]
                != expected["untrusted_document_data"]["context_blocks"]
            ):
                raise ValueError("K5_SENTENCE_CONTEXT_WIRE_OMITTED")
    if sentence_context and not sentence_context_ready(claim, packet):
        if not fallback:
            return None
        # Retain E2E3's verified numbered table sources and classifier.
        # Omit all sentence interpretation input when the guard fails.
        packet = preliminary_table_request(
            claim, graph, tenant_id=self.auth.tenant_id, role_resolution=True
        )
        data = packet["untrusted_document_data"]
        for entry in data["context_blocks"]:
            if entry["source_id"] not in data["omitted_source_ids"]:
                data["omitted_source_ids"].append(entry["source_id"])
        data["context_blocks"] = []
        packet["prompt_sha256"] = canonical_hash(SENTENCE_FALLBACK_BASE_PROMPT)
    display_catalog = getattr(self, "display_catalog", None)
    if display_catalog is not None:
        from proofops.application.tagging.preliminary import _sources
        from proofops.application.tagging.table_sources import table_structural_sources

        sources = _sources(claim, graph, self.auth.tenant_id, allow_unverified=unattended)
        if table:
            structural = table_structural_sources(graph, sources, tenant_id=self.auth.tenant_id)
            sources = (*sources, *(item.ref for item in structural.verified))
        packet["display_text"] = display_catalog.preliminary_pins(packet, sources)
        recovery = self.snapshot.get("analysis_profile_policy", {}).get("hold_recovery_policy")
        if recovery is not None:
            from proofops.application.tagging.k2_recovery import validate_policy

            validate_policy(recovery)
            if self.snapshot["analysis_profile_policy"].get(
                "hold_recovery_policy_sha256"
            ) != canonical_hash(recovery):
                raise ValueError("K2_RECOVERY_POLICY_PIN_MISMATCH")
            packet["preliminary_recovery_policy"] = recovery

    from proofops.application.tagging.k9_contract import BINDING_POLICY, BINDING_V4_POLICY

    if self.snapshot.get("analysis_profile_policy", {}).get(
        "local_implementation_binding_policy"
    ) in (BINDING_POLICY, BINDING_V4_POLICY):
        packet["k9_targeted_wire_policy"] = self.snapshot["analysis_profile_policy"][
            "local_implementation_binding_policy"
        ]

    quality_policy = self.snapshot.get("analysis_profile_policy", {}).get(
        "structural_quality_policy"
    )
    from proofops.application.tagging.q1_contract import QUALITY_POLICIES

    if quality_policy in QUALITY_POLICIES:
        packet["structural_quality_policy"] = quality_policy
    return PreliminaryPacket(
        packet, context_receipt, unattended, table, pb1, decision, cf5, display_catalog
    )


def validate_preliminary_response(self, raw, *, claim, graph, plan):
    packet, unattended, table, pb1 = plan.packet, plan.unattended, plan.table, plan.pb1
    display_catalog = plan.display_catalog
    restoration = {}
    if display_catalog is not None:
        raw = display_catalog.restore_preliminary(raw, packet)
        restoration = raw.pop("dimension_restore_errors", {})
    auxiliary = None
    from proofops.application.tagging.pb2_preliminary import enabled as pb2_enabled

    if pb2_enabled(claim, graph, self.snapshot.get("analysis_profile_policy", {})):
        from proofops.application.tagging.pb2_preliminary import (
            validate_preliminary as validate_pb2,
        )

        result, auxiliary = validate_pb2(
            claim, graph, raw, tenant_id=self.auth.tenant_id, allow_unverified=unattended
        )
    # The table profile recomputes its own quotable source tuple from
    # claim+graph; the legacy validator stays the only path for the two
    # older profiles, so stored responses replay unchanged. The
    # role-resolution profile and the goal-role profile differ only
    # in their prompt, so they reuse this same validator without a new
    # schema or a new source rule.
    result = (
        result
        if auxiliary is not None
        else (
            validate_preliminary_table_sources(
                claim,
                graph,
                raw,
                tenant_id=self.auth.tenant_id,
                allow_unverified=unattended,
            )
            if table
            else validate_preliminary(
                claim,
                graph,
                raw,
                tenant_id=self.auth.tenant_id,
                allow_unverified=unattended,
            )
        )
    )
    from proofops.application.tagging.k1_semantics import POLICY as K1_POLICY
    from proofops.application.tagging.k1_semantics import track_requires_review
    from proofops.application.tagging.k4_contract import SEMANTIC_POLICY, estimate_evidence

    semantic = self.snapshot.get("analysis_profile_policy", {}).get("semantic_admission")
    from proofops.application.tagging.k10_contract import SEMANTIC_POLICY as K10_POLICY
    from proofops.application.tagging.k10_contract import (
        SEMANTIC_V2_POLICY as K10_V2_POLICY,
    )
    from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_POLICY

    v3_policy = self.snapshot.get("analysis_profile_policy", {}).get("v3_dec92_policy")
    if v3_policy is not None:
        from proofops.application.tagging.v3_dec92 import validate_classification
        from proofops.application.tagging.v3_dec92 import validate_policy as validate_v3

        validate_v3(v3_policy)
        if self.snapshot["analysis_profile_policy"].get("v3_dec92_policy_sha256") != canonical_hash(
            v3_policy
        ):
            raise ValueError("V3_DEC92_POLICY_PIN_MISMATCH")
        result = validate_classification(result, claim, graph)
    if v3_policy is None and semantic in (Q1_POLICY, K10_POLICY, K10_V2_POLICY):
        from proofops.application.tagging.q1_contract import forecast_quote

        if forecast_quote(claim.quote) and result.safe_harbor_category != "forward_looking":
            raise ValueError("Q1_FORWARD_LOOKING_CATEGORY_REVIEW")
    risk_policy = self.snapshot.get("analysis_profile_policy", {}).get("risk_classification_policy")
    if risk_policy is not None:
        from proofops.application.tagging.k6_citations import (
            RISK_POLICY,
            risk_without_commitment,
        )

        if risk_policy != RISK_POLICY or self.snapshot["analysis_profile_policy"].get(
            "risk_classification_policy_sha256"
        ) != canonical_hash(RISK_POLICY):
            raise ValueError("K6_RISK_POLICY_MISMATCH")
        if result.track and result.track.track == "goal" and risk_without_commitment(claim.quote):
            raise ValueError("K6_RISK_WITHOUT_COMPANY_COMMITMENT")
    if (
        semantic in (SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY)
        and result.track
        and result.track.track == "goal"
    ):
        from proofops.application.ingest.j7_split import goal_requires_retag

        if goal_requires_retag(claim, graph):
            raise ValueError("K4_CONNECTIVE_GOAL_RETAG_REQUIRED")
    if (
        semantic in (SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY)
        and result.safe_harbor_category == "emissions_estimate"
    ):
        sources = dict(
            tenant_id=graph.tenant_id,
            document_version_id=graph.document_version_id,
            claim_source_refs=[asdict(r) for r in claim.source_refs],
            safe_harbor_category=result.safe_harbor_category,
        )
        if not estimate_evidence(sources, graph):
            result = replace(
                result,
                safe_harbor_category=None,
                track=replace(result.track, safe_harbor_category=None) if result.track else None,
            )

    if (
        semantic in (K1_POLICY, SEMANTIC_POLICY, Q1_POLICY, K10_POLICY, K10_V2_POLICY)
        and result.track is not None
        and track_requires_review(claim.quote, result.track.track)
    ):
        raise ValueError("K1_PUE_PERFORMANCE_RETAG_REQUIRED")
    if (
        pb1
        and v3_policy is None
        and result.safe_harbor_category == "forward_looking"
        and not (semantic in (Q1_POLICY, K10_POLICY, K10_V2_POLICY) and forecast_quote(claim.quote))
    ):
        from proofops.application.tagging.pb1_classification import forward_candidate

        category, reason = forward_candidate(claim.quote)
        if reason == "forecast_context_requires_review":
            raise ValueError("PB1_FORECAST_CONTEXT_REQUIRES_REVIEW")
        result = replace(result, safe_harbor_category=category)
    attribution = {}
    if self.attribution_policy is not None:
        from proofops.application.evidence.binding import ClaimContext
        from proofops.application.evidence.relation_attribution import filter_dimensions

        dimensions, rejected = filter_dimensions(
            claim, result.context.dimensions, graph, tenant_id=self.auth.tenant_id
        )
        result = replace(result, context=ClaimContext(claim, dimensions))
        attribution = dict(
            attribution_rejections=rejected,
            attribution_policy_sha256=canonical_hash(self.attribution_policy),
        )
    return result, dict(
        **({"auxiliary_fact_selections": auxiliary} if auxiliary is not None else {}),
        track=asdict(result.track) if result.track else None,
        dimensions={
            key: asdict(value) if value else None
            for key, value in result.context.dimensions.items()
        },
        safe_harbor_category=result.safe_harbor_category,
        **attribution,
        **({"dimension_restore_errors": restoration} if restoration else {}),
    )


def preliminary_agreement(self, claim_id):
    """Field-level replica agreement for review only; never a tag, state or grade.

    Reads the replica records this run already stored and compares each
    asserted field on its own, because the replica signature covers the whole
    classification: one differing field otherwise hides what every replica
    did agree on. A field is agreed only when all three validated replicas
    returned the identical literal value, conflict when validated values
    differ, and unresolved when a replica is missing or did not report that
    axis. A null category against a non-null one is a conflict: it is never
    reported as null or not applicable, so an unagreed safe-harbor category
    cannot reach the rule engine as a fact.
    """
    if claim_id in getattr(self, "decision_records", {}):
        decision = self.decision_records[claim_id]
        if "fields" in decision:
            fields = decision["fields"]
            return dict(
                schema="preliminary_decision_agreement_v1",
                claim_id=claim_id,
                fields={
                    "track": fields["track"],
                    "safe_harbor_category": decision["safe_harbor_category"],
                },
                dimensions={k: v for k, v in fields.items() if k != "track"},
                decision_receipts=decision["receipts"],
                safe_harbor_category=decision.get("safe_harbor_category"),
                policy_sha256=decision["policy_sha256"],
            )
    records = self.preliminary_records.get(claim_id, [])
    validated = [
        record["values"] for record in records if record["status"] == "validated_candidate"
    ]

    def state(reported):
        distinct = {canonical_json(value) for value in reported}
        return dict(
            state="unresolved"
            if len(validated) != 3 or len(reported) != len(validated)
            else "agreed"
            if len(distinct) == 1
            else "conflict",
            replicate_values=reported,
            distinct_count=len(distinct),
        )

    axes = sorted({axis for values in validated for axis in values["dimensions"]})
    return dict(
        schema="preliminary_field_agreement_v1",
        claim_id=claim_id,
        replicates=len(records),
        validated_replicates=len(validated),
        fields=dict(
            # The literal asserted track, separate from the category candidate.
            track=state(
                [values["track"]["track"] if values["track"] else None for values in validated]
            ),
            safe_harbor_category=state([values["safe_harbor_category"] for values in validated]),
        ),
        dimensions={
            axis: state(
                [values["dimensions"][axis] for values in validated if axis in values["dimensions"]]
            )
            for axis in axes
        },
    )
