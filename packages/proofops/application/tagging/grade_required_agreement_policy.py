"""Opt-in R18 agreement gate; existing profiles and publication defaults are unchanged.

Call AFTER source verification, subject/activity/period binding and authenticated
current-request validation. ``context_sha256`` binds tenant, document version,
claim, packet, rule/model/prompt hashes and analysis run; ``binding_sha256`` binds
the fact's subject, activity, period, scope and normalized value. These are trusted
guard outputs, never fields to accept directly from an LLM or a public request.

This gate selects positive grade facts. It does not authorize publication, turn
unknown into absence, issue SC1 search certificates, or replace the Python engine.
SC1's independent 3/3 scope search remains mandatory at every positive threshold.
"""

from dataclasses import dataclass

from proofops.domain.provenance import canonical_hash


@dataclass(frozen=True, slots=True)
class GradeRequiredAgreementPolicy:
    minimum_present_replicas: int = 3

    def __post_init__(self):
        if type(self.minimum_present_replicas) is not int or self.minimum_present_replicas not in (
            1,
            2,
            3,
        ):
            raise ValueError("minimum_present_replicas must be 1, 2, or 3")

    def to_dict(self):
        return dict(
            profile="grade-required-present-agreement-r18-v1",
            minimum_present_replicas=self.minimum_present_replicas,
            total_independent_replicas=3,
            other_votes="unknown_only; missing_and_unreadable_block",
            contrary_votes="any_absent_or_conflict_blocks",
            positive_evidence="all_present_votes_verified_and_accepted_bound",
            agreement="same_normalized_value_and_fact_binding",
            freshness="three_independent_authenticated_current_responses",
            context="same_tenant_document_claim_packet_run_rule_model_prompt",
            scope_absence="separate_SC1_scope_search_3_of_3_required",
            publication="separate_python_engine_and_publication_guards_required",
        )

    @property
    def sha256(self):
        return canonical_hash(self.to_dict())


DEFAULT_POLICY = GradeRequiredAgreementPolicy()


def _sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def assess_grade_required_facts(
    replicas,
    *,
    required_element_ids,
    claim_source_verified,
    policy=DEFAULT_POLICY,
):
    """Return a deterministic, non-publishing receipt from trusted guarded facts.

    No caller may interpret ``grade_facts_satisfied`` as a confirmed grade. In
    particular a lower grade still needs a valid higher-element scope certificate.
    """
    if not isinstance(policy, GradeRequiredAgreementPolicy):
        raise ValueError("explicit GradeRequiredAgreementPolicy required")
    required = tuple(sorted(set(required_element_ids)))
    if not required:
        raise ValueError("at least one grade-required element is required")
    reasons = []
    if claim_source_verified is not True:
        reasons.append("CLAIM_SOURCE_UNVERIFIED")
    complete = (
        len(replicas) == 3
        and all(type(r.get("replicate_id")) is int for r in replicas)
        and {r.get("replicate_id") for r in replicas} == {1, 2, 3}
    )
    if not complete:
        reasons.append("THREE_REPLICA_RECORDS_REQUIRED")
    for key in ("request_id", "provider_request_id"):
        values = [r.get(key) for r in replicas]
        if not all(isinstance(v, str) and v for v in values) or len(set(values)) != 3:
            reasons.append(f"INDEPENDENT_{key.upper()}_REQUIRED")
    contexts = [r.get("context_sha256") for r in replicas]
    if not all(_sha256(v) for v in contexts) or len(set(contexts)) != 1:
        reasons.append("CURRENT_CONTEXT_MISMATCH")
    if not all(r.get("current_response_bound") is True for r in replicas):
        reasons.append("CURRENT_FRESH_RESPONSES_REQUIRED")
    admissions = {}
    for element_id in required:
        votes = [r.get("elements", {}).get(element_id, {}) for r in replicas]
        states = [v.get("state", "missing") for v in votes]
        present = [v for v in votes if v.get("state") == "present"]
        admitted = (
            complete
            and all(s in ("present", "unknown") for s in states)
            and len(present) >= policy.minimum_present_replicas
            and all(
                v.get("binding") == "accepted"
                and _sha256(v.get("binding_sha256"))
                and v.get("source_refs")
                and all(ref.get("verification_state") == "verified" for ref in v["source_refs"])
                for v in present
            )
            and len({v.get("binding_sha256") for v in present}) == 1
            and len({canonical_hash(v.get("normalized_value")) for v in present}) == 1
        )
        admissions[element_id] = dict(
            positive_votes=len(present),
            states=states,
            admitted=bool(admitted),
        )
        if not admitted:
            reasons.append(f"GRADE_FACT_UNRESOLVED:{element_id}")
    result = dict(
        policy=policy.to_dict(),
        policy_sha256=policy.sha256,
        minimum_present_replicas=policy.minimum_present_replicas,
        grade_facts_satisfied=not reasons,
        public_auto_confirmed=False,
        elements=admissions,
        reasons=sorted(set(reasons)),
        guarded_inputs_sha256=canonical_hash(replicas),
    )
    return result | dict(receipt_sha256=canonical_hash(result))
