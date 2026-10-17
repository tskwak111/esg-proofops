"""Opt-in scheduling contract; no changes to votes, source checks or admission."""

POLICY = dict(
    profile="spt_claim_pipeline_v1",
    ready_claims_per_http_slot=2,
    priority="s2-source-and-budget-class-then-longest-quote-first",
    stages="per-claim-preliminary-consensus-relation-elements",
    replicas="existing-serial-three-with-original-stop-semantics",
    http_admission="existing-shared-role-priority-pacing-and-guards",
    result_order="original-claim-order",
)


def configured(policy):
    if "spt_claim_pipeline" not in policy:
        return False
    if policy["spt_claim_pipeline"] != POLICY:
        raise ValueError("SPT_PIPELINE_POLICY_MISMATCH")
    from proofops.application.provider_resilience import SCHEDULER_C24_POLICY, SCHEDULER_POLICY

    if policy.get("provider_scheduler") not in (SCHEDULER_POLICY, SCHEDULER_C24_POLICY):
        raise ValueError("SPT_SHARED_HTTP_SCHEDULER_REQUIRED")
    return True
