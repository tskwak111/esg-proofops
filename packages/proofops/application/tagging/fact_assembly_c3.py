"""DEC-43/R8 opt-in publication. C2 remains an immutable, disabled reader."""

import re
from dataclasses import asdict

from proofops.application.tagging import fact_assembly_c2 as c2
from proofops.application.tagging.consensus import ConsensusResult
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import ConfirmedFact, ConfirmedTags, RuleContext, evaluate
from proofops.domain.values import LlmElement, SourceRef

PROFILE = "management-direct-certification-c3-v1"
REVIEWED_IDENTITY = dict(
    tenant_id="d1b9e025-a759-4d28-8713-cbb5940ec89b",
    original_sha256="c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde",
    claim_id="462b9bbb-48ba-54d9-9be2-2e30ad14d220",
    claim_sha256="b507d17b108a07c7e6bdbf171efb310fec3bcbc48024fc9d5b57146523c8139d",
    packet_sha256="2156b41834775fada9a4a689125fb17b6080b0fa678cdcb4c8e4a06b2e013587",
    graph_sha256="263c735be11e1f6c4337eb588475b57c464b9f20aaf883bddd1e45b4df9754e6",
    rulepack_sha256="fd659d03b1fb32ec8f9f95457dedd0a75621dcaedb0146bc93f0d86914fd8e04",
)
POLICY = c2.POLICY | dict(
    profile=PROFILE,
    enabled=True,
    approval="DEC-43; R8 bounded LG EMS semantic approval",
    reviewed_identity=REVIEWED_IDENTITY,
    guard="affirmative_same_system; complete_scope; no_validity_inference; no_conflict-v1",
    generalization="candidate_only_until_semantic_review",
)
POLICY_HASH = canonical_hash(POLICY)
DISPLAY = (
    "자동 확정 E3 · SUBSTANTIATED — 프로젝트 루브릭상 공시 내 입증요소 충족. "
    "EMS의 ISO 14001 직접 인증과 적용범위(국내 전 생산 사업장, 글로벌 17개 중 15개)를 "
    "p36에서 확인. 보고서 문맥: 2025; 인증 유효기간: 미기재."
)


def safety_reasons(claim_quote, raw):
    """Fail closed on source attribution; never turn a blocked fact into absent."""
    reasons = []
    evidence = raw["elements"]["M3"].get("evidence")
    quote = evidence["quote"] if evidence else ""
    # An affirmative certification predicate is required, not mere ISO naming.
    if not re.search(r"인증(?:을 통해 제3자 검증을 받고|을 완료|을 취득|을 획득|을 유지)", quote):
        reasons.append("CERTIFICATION_POSSESSION_UNRESOLVED")
    if re.search(r"부합|예정|미취득|미인증|철회|취소|진행 중|계획", quote):
        reasons.append("CERTIFICATION_NONPOSSESSION_OR_PLAN")
    if "환경경영시스템" not in quote:
        reasons.append("CERTIFICATION_SYSTEM_NOT_DIRECTLY_NAMED")
    if re.search(r"유효기간|만료|유효하|유효한", claim_quote):
        reasons.append("CERTIFICATION_VALIDITY_NOT_ESTABLISHED")
    if re.search(r"미취득|미인증|철회|취소", claim_quote):
        reasons.append("CLAIM_CERTIFICATION_SCOPE_CONFLICT")
    m2 = raw["elements"]["M2"].get("evidence")
    if m2:
        counts = re.search(r"총\s*(\d+)개 생산 사업장 중\s*(\d+)개 사업장", m2["quote"])
        if (
            counts
            and int(counts[2]) < int(counts[1])
            and re.search(
                r"(?:글로벌|모든|전 세계|국내외).{0,12}(?:전|전체|모든)\s*(?:생산\s*)?사업장",
                claim_quote,
            )
        ):
            reasons.append("PARTIAL_SCOPE_EXPANDED")
    return sorted(set(reasons))


def assemble(votes, **inputs):
    result = c2.assemble(votes, **inputs).to_dict()
    reasons = sorted(
        {r for v in votes for r in safety_reasons(inputs["context"].claim.quote, v["raw"])}
    )
    result.pop("receipt_sha256")
    result.update(policy=POLICY, policy_sha256=POLICY_HASH)
    by_replica = {v["replicate_id"]: v for v in votes}
    for derived in result["derived_results"]:
        derived["matcher_policy_sha256"] = POLICY_HASH
        own_reasons = safety_reasons(
            inputs["context"].claim.quote, by_replica[derived["replicate_id"]]["raw"]
        )
        if own_reasons:
            normalized = derived["result"]
            normalized["reasons"] = sorted(set(normalized["reasons"] + own_reasons))
            normalized["elements"]["M3"].update(
                state="unknown", binding="undetermined", source_refs=[]
            )
            derived["agreement_value"]["states"]["M3"] = "unknown"
            derived["output_sha256"] = canonical_hash(normalized)
            derived["agreement_sha256"] = canonical_hash(derived["agreement_value"])
    if reasons:
        result.update(
            engine_decision=None,
            candidate_auto_confirmed=False,
            resolved_3_of_3=False,
            unresolved=sorted(set(result["unresolved"] + reasons)),
        )
    approved = all(result["identity"].get(k) == v for k, v in REVIEWED_IDENTITY.items())
    result["public_auto_confirmed"] = bool(
        result["candidate_auto_confirmed"]
        and approved
        and not result["simulated"]
        and inputs["rulepack"].status == "active"
        and inputs["rulepack"].approved_by
        and inputs["rulepack"].approved_at
    )
    return c2._receipt(result)


def replay(receipt, **inputs):
    if receipt.get("policy_sha256") != POLICY_HASH:
        raise ValueError("C3_POLICY_MISMATCH")
    result = assemble(receipt["raw_receipts"], **inputs)
    if result.to_dict() != receipt:
        raise ValueError("C3_ASSEMBLY_REPLAY_MISMATCH")
    return result


def publication_policy_for(profile, *, pinned_hash=None):
    if profile != PROFILE or pinned_hash not in (None, POLICY_HASH):
        raise ValueError("C3_PUBLICATION_PROFILE_MISMATCH")
    return dict(POLICY)


def publication_values(
    receipt, *, rulepack, tag_revision, require_public=True, local_synthetic=False
):
    """Reconstruct Python facts from the individually guarded matcher outputs."""
    if type(local_synthetic) is not bool:
        raise ValueError("C3_LOCAL_SYNTHETIC_FLAG_INVALID")
    if require_public and not receipt["public_auto_confirmed"]:
        raise ValueError("C3_PUBLICATION_NOT_ELIGIBLE")
    identity = receipt["identity"]
    first = receipt["raw_receipts"][0]
    derived = receipt["derived_results"][0]["result"]
    facts, elements = [], []
    for eid, item in derived["elements"].items():
        refs = tuple(SourceRef(**r) for r in item["source_refs"])
        facts.append(
            ConfirmedFact(item["primitive"], "present", refs, identity["tenant_id"], True, True)
        )
        elements.append(LlmElement(eid, "present", refs, None, None, None))
    claim_refs = tuple(SourceRef(**r) for r in receipt["statement_boundary"])
    for name in c2.TRIGGERS:
        facts.append(
            ConfirmedFact(
                name,
                "absent",
                claim_refs,
                identity["tenant_id"],
                True,
                True,
                search_coverage_verified=True,
            )
        )
    elements.extend(LlmElement(eid, "unknown", (), None, None, None) for eid in ("M5", "M6"))
    hashes = tuple(v["vote_sha256"] for v in receipt["raw_receipts"])
    tags = ConfirmedTags(
        identity["tenant_id"],
        identity["document_version_id"],
        identity["claim_id"],
        "management",
        tuple(facts),
        tag_revision,
        identity["packet_sha256"],
        first["model_sha256"],
        first["prompt_sha256"],
        hashes,
        rulepack.ontology_version,
    )
    consensus = ConsensusResult(
        tuple(elements),
        tuple((f"M{i}", 3) for i in range(1, 5)),
        "auto_confirmed",
        tags,
        (),
        hashes,
    )
    decision = evaluate(
        tags,
        RuleContext(
            identity["tenant_id"],
            identity["document_version_id"],
            identity["claim_id"],
            identity["packet_sha256"],
            local_synthetic=local_synthetic,
        ),
        rulepack,
    )
    if canonical_hash(asdict(decision)) != canonical_hash(receipt["engine_decision"]):
        raise ValueError("C3_PYTHON_DECISION_REPLAY_MISMATCH")
    return consensus, decision


def validate_publication(inputs):
    if inputs.fact_assembly_receipt is None:
        raise ValueError("C3_PUBLICATION_RECEIPT_REQUIRED")
    receipt = replay(
        inputs.fact_assembly_receipt.to_dict(),
        context=inputs.context,
        graph=inputs.original,
        packet=inputs.packet,
        rulepack=inputs.rulepack,
        tag_revision=inputs.tag_revision,
    ).to_dict()
    consensus, decision = publication_values(
        receipt, rulepack=inputs.rulepack, tag_revision=inputs.tag_revision
    )
    if (
        inputs.consensus != consensus
        or inputs.decision != decision
        or inputs.tag_runs
        or inputs.rule_context.local_synthetic
        or inputs.fact_assembly_profile != PROFILE
        or inputs.rule_context.packet_sha256 != inputs.packet.packet_sha256
        or inputs.run_id != inputs.packet.to_dict()["run_id"]
        or inputs.packet.to_dict()["retrieval_packet_sha256"]
        != inputs.original_packet.packet_sha256
    ):
        raise ValueError("C3_PUBLICATION_INPUT_MISMATCH")
    from proofops.domain.rules.engine import evaluate

    if asdict(evaluate(consensus.confirmed_tags, inputs.rule_context, inputs.rulepack)) != asdict(
        decision
    ):
        raise ValueError("C3_PUBLICATION_DECISION_MISMATCH")
