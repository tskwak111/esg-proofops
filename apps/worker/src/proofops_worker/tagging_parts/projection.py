"""Attach retained context and scoped confirmation to a completed claim record."""


def project_claim(context, claim, record):
    rb1, snapshot = context.rb1, context.snapshot
    facility_dimensions, graph = context.facility_dimensions, context.graph
    sc1_policy, sc1_index = context.sc1_policy, context.sc1_index
    rulepack, live = context.rulepack, context.live
    if rb1.active and "rb1_input_hold" in record:
        return record
    if snapshot.get("analysis_profile_policy", {}).get("facility_dimensions"):
        record["source_dimensions"] = facility_dimensions.get(
            claim.claim_id, dict(facility=dict(state="unresolved", value=None))
        )
    if snapshot.get("analysis_profile_policy", {}).get("sentence_context_policy"):
        from proofops.application.ingest.k5_context import configured_context

        record["sentence_context"] = configured_context(
            claim, graph, snapshot["analysis_profile_policy"]
        )
    if sc1_policy is not None:
        record["sc1_confirmation"] = None
        record["sc1_hold_reason"] = "SC1_INVENTORY_UNAVAILABLE"
        if sc1_index is not None and record.get("tag_runs") and "sc1_dimensions" in record:
            from proofops.application.tagging.analysis_scope import analyze_record
            from proofops.application.tagging.v1_activity_links import policy_from_profile

            receipt = analyze_record(
                record,
                claim,
                graph,
                rulepack,
                sc1_index,
                required_present_votes=sc1_policy["agreement"]["required_present_votes"],
                local_synthetic=live is None,
                grade_agreement_policy=snapshot.get("analysis_profile_policy", {}).get(
                    "grade_required_agreement_policy"
                ),
                v1_activity_policy=policy_from_profile(snapshot.get("analysis_profile_policy", {})),
            )
            record["sc1_scope_receipt"] = receipt
            record["sc1_confirmation"] = receipt["sc1_confirmation"]
            record["sc1_elements"] = receipt["sc1_elements"]
            record["sc1_hold_reason"] = ",".join(receipt["reasons"]) or None
    if snapshot.get("analysis_profile_policy", {}).get("cf6_confirmation") is not None:
        record["cf6_confirmation"] = None
        if record.get("tag_runs") and record.get("frozen_packet"):
            from proofops.application.tagging.cf6_confirmation import analyze_record

            receipt = analyze_record(
                record,
                claim,
                graph,
                rulepack,
                snapshot["analysis_profile_policy"],
            )
            record["cf6_receipt"] = receipt
            record["cf6_confirmation"] = receipt["cf6_confirmation"]
    return record
