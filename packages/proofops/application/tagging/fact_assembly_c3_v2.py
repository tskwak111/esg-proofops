"""DEC-68 C3 continuity by exact, source-stable fingerprint for the reviewed LG claim."""

import unicodedata
from dataclasses import asdict

from proofops.application.tagging import fact_assembly_c2 as c2
from proofops.application.tagging import fact_assembly_c3 as c3
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import evaluate

PROFILE = "management-direct-certification-c3-v2"
DISPLAY = c3.DISPLAY
_PREVIOUS_POLICY = {key: value for key, value in c3.POLICY.items() if key != "reviewed_identity"}


def _normalize(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def _span_identity(ref):
    if ref.get("verification_state") != "verified":
        raise ValueError("C3_SOURCE_FINGERPRINT_UNVERIFIED")
    page = ref.get("page_num")
    start, end = ref.get("char_start"), ref.get("char_end")
    bbox = ref.get("bbox")
    if type(page) is not int or not ref.get("quote"):
        raise ValueError("C3_SOURCE_FINGERPRINT_LOCATION_REQUIRED")
    if (start is None or end is None) and bbox is None:
        raise ValueError("C3_SOURCE_FINGERPRINT_LOCATION_REQUIRED")
    if start is not None and (type(start) is not int or type(end) is not int or end <= start):
        raise ValueError("C3_SOURCE_FINGERPRINT_OFFSET_INVALID")
    return dict(
        page_num=page,
        char_start=start,
        char_end=end,
        bbox=list(bbox) if bbox is not None else None,
        normalized_exact_span=_normalize(ref["quote"]),
    )


def source_fingerprint_payload(assembly):
    """Build continuity identity without run, packet, graph, or claim UUID pins."""
    identity = assembly["identity"]
    statement = sorted(
        (_span_identity(ref) for ref in assembly["statement_boundary"]),
        key=lambda item: (item["page_num"], item["char_start"] or -1, item["char_end"] or -1),
    )
    if not statement:
        raise ValueError("C3_SOURCE_FINGERPRINT_STATEMENT_REQUIRED")
    derived = assembly["derived_results"]
    if len(derived) != 3:
        raise ValueError("C3_SOURCE_FINGERPRINT_REPLICAS_REQUIRED")
    replica_payloads = []
    for replica in derived:
        elements = replica["result"]["elements"]
        evidence = {}
        for element_id in ("M1", "M2", "M3", "M4"):
            item = elements[element_id]
            if item.get("state") != "present" or item.get("binding") != "accepted":
                raise ValueError("C3_SOURCE_FINGERPRINT_FACT_UNRESOLVED")
            refs = sorted(
                (_span_identity(ref) for ref in item["source_refs"]),
                key=lambda value: (
                    value["page_num"],
                    value["char_start"] or -1,
                    value["char_end"] or -1,
                ),
            )
            if not refs:
                raise ValueError("C3_SOURCE_FINGERPRINT_EVIDENCE_REQUIRED")
            evidence[element_id] = refs
        replica_payloads.append(evidence)
    if any(value != replica_payloads[0] for value in replica_payloads[1:]):
        raise ValueError("C3_SOURCE_FINGERPRINT_REPLICA_DISAGREEMENT")
    return dict(
        tenant_id=identity["tenant_id"],
        original_sha256=identity["original_sha256"],
        statement_spans=statement,
        normalized_exact_claim=" ".join(ref["normalized_exact_span"] for ref in statement),
        element_evidence_refs=replica_payloads[0],
        rulepack_sha256=identity["rulepack_sha256"],
    )


_BBOX = [38.438, 469.9369999999999, 803.816, 543.8219999999999]
_CLAIM = (
    "LG화학의 환경경영시스템(Environmental Management System, EMS)은 ISO 14001 인증을 통해 "
    "제3자 검증을 받고 있으며, 내부 감사를 통해 운영 적정성을 정기적으로 점검하고 있습니다. "
    "ISO 14001 인증은 국내 전 생산 사업장에 적용되고 있으며, 글로벌 사업장의 경우 총 17개 "
    "생산 사업장 중 15개 사업장에서 인증을 완료하였습니다."
)
_DIRECT = (
    "LG화학의 환경경영시스템(Environmental Management System, EMS)은 ISO 14001 인증을 통해 "
    "제3자 검증을 받고 있으며, 내부 감사를 통해 운영 적정성을 정기적으로 점검하고 있습니다."
)
_SCOPE = (
    "ISO 14001 인증은 국내 전 생산 사업장에 적용되고 있으며, 글로벌 사업장의 경우 총 17개 "
    "생산 사업장 중 15개 사업장에서 인증을 완료하였습니다."
)


def _reviewed_ref(start, end, quote):
    return dict(
        page_num=36,
        char_start=start,
        char_end=end,
        bbox=_BBOX,
        quote=quote,
        verification_state="verified",
    )


REVIEWED_SOURCE_IDENTITY = dict(
    tenant_id="d1b9e025-a759-4d28-8713-cbb5940ec89b",
    original_sha256="c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde",
    statement_spans=[_span_identity(_reviewed_ref(169, 376, _CLAIM))],
    normalized_exact_claim=_normalize(_CLAIM),
    element_evidence_refs={
        "M1": [_span_identity(_reviewed_ref(169, 289, _DIRECT))],
        "M2": [_span_identity(_reviewed_ref(290, 376, _SCOPE))],
        "M3": [_span_identity(_reviewed_ref(169, 289, _DIRECT))],
        "M4": [_span_identity(_reviewed_ref(290, 376, _SCOPE))],
    },
    rulepack_sha256="fd659d03b1fb32ec8f9f95457dedd0a75621dcaedb0146bc93f0d86914fd8e04",
)
REVIEWED_SOURCE_FINGERPRINT_SHA256 = canonical_hash(REVIEWED_SOURCE_IDENTITY)
POLICY = _PREVIOUS_POLICY | dict(
    profile=PROFILE,
    approval="DEC-68; DEC-43 bounded LG EMS source continuity",
    identity_strategy=(
        "tenant_original_sha_page_offsets_or_glyph_box_normalized_exact_claim_span_"
        "element_evidence_refs_rulepack_hash"
    ),
    reviewed_source_fingerprint_sha256=REVIEWED_SOURCE_FINGERPRINT_SHA256,
    generalization="one_exact_source_statement_only",
)
POLICY_HASH = canonical_hash(POLICY)


def assemble(votes, **inputs):
    """Rebind saved/current raw responses to this run, then recompute source and grade."""
    result = c3.assemble(votes, **inputs).to_dict()
    result.pop("receipt_sha256")
    result.update(policy=POLICY, policy_sha256=POLICY_HASH)
    for derived in result["derived_results"]:
        derived["matcher_policy_sha256"] = POLICY_HASH
    try:
        fingerprint = source_fingerprint_payload(result)
    except (KeyError, TypeError, ValueError):
        fingerprint = None
    fingerprint_sha256 = canonical_hash(fingerprint) if fingerprint is not None else None
    result["source_fingerprint"] = fingerprint
    result["source_fingerprint_sha256"] = fingerprint_sha256
    if fingerprint_sha256 != REVIEWED_SOURCE_FINGERPRINT_SHA256:
        result.update(
            engine_decision=None,
            candidate_auto_confirmed=False,
            resolved_3_of_3=False,
            unresolved=sorted(set(result["unresolved"] + ["SOURCE_FINGERPRINT_NOT_APPROVED"])),
        )
    identity = result["identity"]
    approved_pack = (
        inputs["rulepack"].status == "active"
        and inputs["rulepack"].approved_by
        and inputs["rulepack"].approved_at
    )
    result["public_auto_confirmed"] = bool(
        result["candidate_auto_confirmed"]
        and fingerprint_sha256 == REVIEWED_SOURCE_FINGERPRINT_SHA256
        and not result["simulated"]
        and approved_pack
        and identity["tenant_id"] == REVIEWED_SOURCE_IDENTITY["tenant_id"]
        and identity["original_sha256"] == REVIEWED_SOURCE_IDENTITY["original_sha256"]
        and identity["rulepack_sha256"] == REVIEWED_SOURCE_IDENTITY["rulepack_sha256"]
    )
    return c2._receipt(result)


def replay(receipt, **inputs):
    if receipt.get("policy_sha256") != POLICY_HASH:
        raise ValueError("C3_V2_POLICY_MISMATCH")
    result = assemble(receipt["raw_receipts"], **inputs)
    if result.to_dict() != receipt:
        raise ValueError("C3_V2_ASSEMBLY_REPLAY_MISMATCH")
    return result


def publication_policy_for(profile, *, pinned_hash=None):
    if profile != PROFILE or pinned_hash not in (None, POLICY_HASH):
        raise ValueError("C3_V2_PUBLICATION_PROFILE_MISMATCH")
    return dict(POLICY)


def publication_values(receipt, *, rulepack, tag_revision, require_public=True):
    if receipt.get("policy_sha256") != POLICY_HASH:
        raise ValueError("C3_V2_POLICY_MISMATCH")
    return c3.publication_values(
        receipt,
        rulepack=rulepack,
        tag_revision=tag_revision,
        require_public=require_public,
        local_synthetic=receipt["simulated"],
    )


def validate_publication(inputs):
    if inputs.fact_assembly_receipt is None:
        raise ValueError("C3_V2_PUBLICATION_RECEIPT_REQUIRED")
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
        raise ValueError("C3_V2_PUBLICATION_INPUT_MISMATCH")
    if asdict(evaluate(consensus.confirmed_tags, inputs.rule_context, inputs.rulepack)) != asdict(
        decision
    ):
        raise ValueError("C3_V2_PUBLICATION_DECISION_MISMATCH")
