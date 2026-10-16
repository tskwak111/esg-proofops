"""DEC-125/127 opt-in agreement and publication. Historical projections are immutable.

Inputs are source/binding guarded TagRuns, never public or model-owned receipts.
The adapter authenticates current responses; stored checkpoints replay this gate.
"""

import json
from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.consensus import form_consensus
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.cf6_scope import POLICY as SCOPE_POLICY
from proofops.domain.rules.cf6_scope import POLICY_V1 as SCOPE_POLICY_V1
from proofops.domain.rules.cf6_scope import evaluate_scope, gap_details, resolve_exception_facts
from proofops.domain.rules.engine import MAPPINGS, ConfirmedFact, ConfirmedTags, evaluate


def policy(required=2, *, version=2):
    if type(required) is not int or required not in (2, 3):
        raise ValueError("CF6_THRESHOLD_INVALID")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("CF6_VERSION_INVALID")
    return dict(
        profile=f"cf6_dec125_dec127_confirmation_v{version}",
        required_votes=required,
        replicas=3,
        track_votes=3,
        present="verified_source_same_value_binding_scope",
        absent="unknown_after_three_completed_replicas_is_absent_in_scope_DEC127",
        scope_rules=SCOPE_POLICY if version == 2 else SCOPE_POLICY_V1,
        dissent="verified_opposite_or_any_conflict_preserved; unknown_allowed",
        unreadable="hold",
        publication="all_ladder_elements_resolved_python_decided_current_authenticated_responses",
        historical="replay_only_under_original_policy",
    )


POLICY = policy()
POLICY_V1 = policy(version=1)
POLICY_HASH = canonical_hash(POLICY)
LADDER = dict(
    management=("M1", "M2", "M3"),
    performance=("P1", "P2", "P3", "P4"),
    goal=("G1", "G2", "G3", "G4", "G5", "G6"),
)


def selected_policy(analysis_policy):
    selected = analysis_policy.get("cf6_confirmation")
    if selected is not None and selected not in (
        policy(selected.get("required_votes"), version=1),
        policy(selected.get("required_votes")),
    ):
        raise ValueError("CF6_POLICY_MISMATCH")
    return selected


def resolve_votes(votes, required=2):
    """Trusted guarded agreement; DEC-127 non-observation is a separate scoped step."""
    policy(required)
    states = [v["state"] for v in votes]
    if "conflict" in states:
        return "conflict", []
    if len(votes) != 3 or any(s in ("unreadable", "missing") for s in states):
        return "unknown", []
    valid = [v for v in votes if v["state"] in ("present", "absent") and v.get("verified")]
    keys = {(v["state"], v.get("value"), v.get("binding"), v.get("scope")) for v in valid}
    if len(keys) > 1:
        return "conflict", []
    if len(valid) >= required and len(keys) == 1:
        return valid[0]["state"], valid
    return "unknown", []


def response_bound(run, analysis_policy):
    """Replay the adapter-owned receipt; a digest alone is not transport authority."""
    try:
        response = json.loads(run.provider_response_json or "{}")
        receipt = response.pop("cf6_transport_receipt", {})
        binding = receipt.get("binding", {})
        return bool(
            not run.synthetic
            and receipt.get("schema") == "cf6-authenticated-transport-v1"
            and receipt.get("authenticated") is True
            and receipt.get("fresh_model_call") is True
            and receipt.get("replay") is False
            and receipt.get("response_sha256") == canonical_hash(response)
            and receipt.get("expanded_sha256") == canonical_hash(run.raw_response_json)
            and receipt.get("provider_request_id") == run.usage.provider_request_id
            and response.get("provider_request_id") == run.usage.provider_request_id
            and response.get("request_id") == run.request.request_id
            and response.get("simulated", False) is False
            and "response_reuse" not in response
            and "saved_response_origin" not in response
            and binding
            == dict(
                request_id=run.request.request_id,
                request_signature=run.request.request_signature,
                tenant_id=run.tenant_id,
                packet_sha256=run.packet_sha256,
                replica=run.replicate_id,
                model_sha256=run.model_sha256,
                prompt_sha256=run.prompt_sha256,
                analysis_policy_sha256=canonical_hash(analysis_policy),
            )
        )
    except (ValueError, TypeError, AttributeError):
        return False


def confirmation_result(
    runs,
    packet,
    rulepack,
    rule_context,
    *,
    claim,
    graph,
    analysis_policy,
    prior_projection,
    hold_reason=None,
):
    selected = selected_policy(analysis_policy)
    if selected is None:
        raise ValueError("CF6_POLICY_REQUIRED")
    required = selected["required_votes"]
    revised = selected["scope_rules"] == SCOPE_POLICY
    data = packet.to_dict()
    baseline = form_consensus(
        runs,
        packet=packet,
        rulepack=rulepack,
        tenant_id=rule_context.tenant_id,
        tag_revision=1,
        profile="grade-relevant-unanimity-v3",
    )
    ordered = sorted(runs, key=lambda r: r.replicate_id)
    reasons = []
    completed = not any(
        r.guarded is None
        or r.usage is None
        or r.usage.status != "succeeded"
        or any(
            not e.startswith("UNRESOLVED:") and e != "DETERMINISTIC_CHECK_REQUIRED:P6"
            for e in r.errors
        )
        for r in ordered
    )
    if not completed:
        reasons.append("CF6_REPLICAS_UNRESOLVED")
    if not all(response_bound(r, analysis_policy) for r in ordered):
        reasons.append("CF6_CURRENT_RESPONSES_REQUIRED")
    headers = [
        (r.guarded.track, r.guarded.safe_harbor_category, r.guarded.superlative_quote)
        for r in ordered
        if r.guarded
    ]
    if (
        len(headers) != 3
        or len(set(headers)) != 1
        or headers[0][:2] != (data["track"], data.get("safe_harbor_category"))
    ):
        reasons.append("CF6_TRACK_CATEGORY_UNANIMITY_REQUIRED")
    if (
        claim.claim_id != data["claim_id"]
        or claim.document_version_id != data["document_version_id"]
        or claim.tenant_id != data["tenant_id"]
        or canonical_hash(asdict(graph)) != data["graph_sha256"]
    ):
        raise ValueError("CF6_SOURCE_IDENTITY_MISMATCH")
    if (
        not claim.source_refs
        or claim.source_quality != "verified"
        or any(
            verify_source_ref(r, graph, tenant_id=claim.tenant_id).verification_state != "verified"
            for r in claim.source_refs
        )
    ):
        reasons.append("CF6_CLAIM_SOURCE_UNVERIFIED")
    if (
        data.get("cf6_analysis_policy_sha256") != canonical_hash(analysis_policy)
        or data.get("cf6_confirmation") != selected
    ):
        reasons.append("CF6_PACKET_POLICY_MISMATCH")
    pages = data.get("cf6_selected_pages", [])
    valid_scope = bool(
        pages
        and pages == sorted(set(pages))
        and all(type(p) is int and p > 0 for p in pages)
        and all(ref.page_num in pages for ref in claim.source_refs)
    )
    if not valid_scope:
        reasons.append("CF6_SELECTED_SCOPE_REQUIRED")
    scope = dict(
        run_id=data["run_id"],
        tenant_id=data["tenant_id"],
        document_version_id=data["document_version_id"],
        graph_sha256=data["graph_sha256"],
        selected_pages=pages,
        absence_basis="system_not_found_or_not_linked_after_three_replicas",
        rule_policy_sha256=canonical_hash(selected["scope_rules"]),
    )
    # GAP-005 retains an already-decided E grade with sublabel=null (domain §31).
    # Grade-blocking GAPs remain held; no new label mapping is invented here.
    if set(prior_projection.get("gap_ids", [])) - {"GAP-005"} or hold_reason == "blocked_rule_gap":
        reasons.append("CF6_RULE_GAP")
    if hold_reason and "TIME_BUDGET" in hold_reason:
        reasons.append("CF6_TIME_BUDGET")
    if prior_projection.get("grade_basis") in {
        "estimate_hold",
        "retag_required",
        "scope3_calculation_hold",
    }:
        reasons.append("CF6_EXISTING_SAFETY_HOLD")
    if not revised and (
        any(h[1] or h[2] for h in headers) or any(r.product_variant for r in ordered)
    ):
        reasons.append("CF6_EXCEPTION_REVIEW_REQUIRED")
    providers = [r.usage.provider_request_id for r in ordered if r.usage]
    if len(set(providers)) != 3 or not all(providers):
        reasons.append("CF6_PROVIDER_REPLAY")
    facts, elements = [], []
    for eid, names in MAPPINGS[data["track"]].items():
        votes = []
        for run in ordered:
            element = (
                next((e for e in run.guarded.elements if e.element_id == eid), None)
                if run.guarded
                else None
            )
            refs = element.evidence_refs if element else ()
            binding = dict(run.binding_hashes).get(eid)
            verified = bool(
                refs
                and binding
                and all(
                    r.verification_state == "verified"
                    and verify_source_ref(r, graph, tenant_id=claim.tenant_id).verification_state
                    == "verified"
                    for r in refs
                )
            )
            state = element.state if element else "missing"
            negative_source = False
            # Raw opposite evidence survives guard downgrades; it can veto but never
            # establish a positive/negative fact on its own.
            try:
                raw = next(
                    e
                    for e in json.loads(run.raw_response_json)["elements"]
                    if e["element_id"] == eid
                )
                if raw["state"] == "conflict":
                    state = "conflict"
                elif raw["state"] == "absent" and raw.get("evidence_refs"):
                    from proofops.domain.values import SourceRef

                    opposite = tuple(SourceRef(**ref) for ref in raw["evidence_refs"])
                    if all(
                        verify_source_ref(ref, graph, tenant_id=claim.tenant_id).verification_state
                        == "verified"
                        and any(
                            c.source_id == ref.source_id
                            and c.char_start <= ref.char_start
                            and ref.char_end <= c.char_end
                            for c in claim.source_refs
                        )
                        for ref in opposite
                    ):
                        negative_source = True
            except (ValueError, TypeError, KeyError, StopIteration):
                state = "missing"
            votes.append(
                dict(
                    state=state,
                    verified=verified if state == "present" else False,
                    negative_source=negative_source,
                    value=element.normalized_value if element and state == "present" else None,
                    binding=binding if state == "present" else None,
                    scope=dict(run.source_scopes).get(eid, "local_claim"),
                    refs=refs,
                    replica=run.replicate_id,
                )
            )
        state, winners = resolve_votes(votes, required)
        if any(v["negative_source"] for v in votes) and any(
            v["state"] == "present" and v["verified"] for v in votes
        ):
            state, winners = "conflict", []
        # DEC-127 supersedes the exhaustive-search requirement only inside the
        # pinned selected scope, after all three tagging replicas completed.
        if (
            state == "unknown"
            and completed
            and valid_scope
            and all(v["state"] not in ("missing", "unreadable") for v in votes)
        ):
            state = "absent_in_scope"
        refs = (
            tuple(dict.fromkeys(ref for v in winners for ref in v.get("refs", ())))
            if state == "present"
            else ()
        )
        elements.append(
            dict(
                element_id=eid,
                state=state,
                votes=len(winners),
                replicate_ids=[v["replica"] for v in winners],
                evidence_refs=[asdict(r) for r in refs],
                absence_basis="DEC127_SYSTEM_NON_OBSERVATION"
                if state == "absent_in_scope"
                else None,
            )
        )
        if eid in LADDER[data["track"]] and state not in ("present", "absent_in_scope"):
            reasons.append("CF6_LADDER_UNRESOLVED:" + eid)
        if state == "conflict":
            reasons.append("CF6_CONFLICT:" + eid)
        for name in names:
            facts.append(
                ConfirmedFact(
                    name,
                    state,
                    refs,
                    claim.tenant_id if refs else None,
                    bool(refs),
                    bool(refs),
                    state == "absent",
                    winners[0].get("scope", "local_claim") if winners else "local_claim",
                    winners[0].get("value") if state == "present" else None,
                )
            )
    if baseline.confirmed_tags:
        known = {f.name for f in facts}
        facts.extend(f for f in baseline.confirmed_tags.facts if f.name not in known)
    first = ordered[0]
    tags = ConfirmedTags(
        claim.tenant_id,
        claim.document_version_id,
        claim.claim_id,
        data["track"],
        tuple(facts),
        1,
        packet.packet_sha256,
        first.model_sha256,
        first.prompt_sha256,
        tuple(r.semantic_hash for r in ordered),
        rulepack.ontology_version,
        data.get("safe_harbor_category"),
        headers[0][2] if headers else None,
        first.product_variant,
    )
    if revised and completed and valid_scope:
        tags = resolve_exception_facts(
            tags,
            claim_source_refs=claim.source_refs
            if "CF6_CLAIM_SOURCE_UNVERIFIED" not in reasons
            else (),
        )
        facts = list(tags.facts)
        reasons.extend("CF6_CONFLICT:" + f.name for f in facts if f.state == "conflict")
    absent = [f.name for f in facts if f.state == "absent_in_scope"]
    if absent and any(f.state == "conflict" for f in facts):
        # Keep the conflict and the scoped non-observation, without asking the
        # scoped evaluator to accept an expressly forbidden conflicted input.
        decision = evaluate(
            replace(
                tags,
                facts=tuple(
                    replace(f, state="unknown") if f.state == "absent_in_scope" else f
                    for f in facts
                ),
            ),
            rule_context,
            rulepack,
        )
    elif absent:
        decision = evaluate_scope(
            tags,
            rule_context,
            rulepack,
            scope=scope,
            policy_sha256=canonical_hash(selected),
            receipt_sha256=canonical_hash(dict(scope=scope, elements=elements)),
        )
    else:
        decision = evaluate(tags, rule_context, rulepack)
    if decision.decision_status != "decided":
        reasons.append("CF6_ENGINE:" + decision.decision_status)
    body = dict(
        policy=selected,
        policy_sha256=canonical_hash(selected),
        analysis_policy_sha256=canonical_hash(analysis_policy),
        packet_sha256=packet.packet_sha256,
        claim_id=claim.claim_id,
        replicate_hashes=[r.semantic_hash for r in ordered],
        elements=elements,
        reasons=sorted(set(reasons)),
        engine_decision=decision.to_api_dict(),
        confirmation_scope=scope,
        rule_pack_sha256=rulepack.sha256,
        model_sha256=first.model_sha256,
        prompt_sha256=first.prompt_sha256,
        prior_projection_sha256=canonical_hash(prior_projection),
    )
    if revised:
        body.update(
            rule_gap_details=gap_details(tags, rulepack, decision),
            auxiliary_facts=[
                asdict(f)
                for f in tags.facts
                if f.name not in {n for ns in MAPPINGS[data["track"]].values() for n in ns}
            ],
        )
    receipt_hash = canonical_hash(body)
    confirmed = (
        None
        if reasons
        else decision.to_api_dict()
        | dict(
            confirmation_display="확정",
            confirmation_basis="cf6_element_agreement",
            confirmation_policy_sha256=canonical_hash(selected),
            cf6_receipt_sha256=receipt_hash,
            confirmation_scope=scope,
            model_sha256=first.model_sha256,
            prompt_sha256=first.prompt_sha256,
            analysis_policy_sha256=canonical_hash(analysis_policy),
            review_status="auto_confirmed",
        )
    )
    return body | dict(receipt_sha256=receipt_hash, cf6_confirmation=confirmed)


def analyze_record(record, claim, graph, rulepack, analysis_policy):
    from proofops.application.evidence.retrieval import freeze_packet
    from proofops.application.tagging.analysis_scope import read_runs
    from proofops.domain.rules.engine import RuleContext

    packet = freeze_packet(
        {k: v for k, v in record["frozen_packet"].items() if k != "packet_sha256"}
    )
    runs = read_runs(record["tag_runs"])
    return confirmation_result(
        runs,
        packet,
        rulepack,
        RuleContext(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            local_synthetic=any(run.synthetic for run in runs),
        ),
        claim=claim,
        graph=graph,
        analysis_policy=analysis_policy,
        prior_projection=record["provisional_grade"],
        hold_reason=record.get("reason"),
    )
