"""Pinned, source-specific delegated reviews for the parser lab only.

No HTTP input can create a review. Changed extraction/evidence needs a new review.
The independent evaluation baseline is never loaded here.
"""

import json
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from proofops.domain.rulepacks import RulePackSnapshot, canonical_json
from proofops.domain.rules.engine import (
    ConfirmedFact,
    ConfirmedTags,
    EvidenceReview,
    RuleContext,
    evaluate,
)
from proofops.domain.values import SourceRef

ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = ROOT / ".local/final-review/review-v4.json"
# Updated only by the explicitly supervised source-review operation.
REVIEW_SHA256 = "6b7e5d6b7c64a7537f9218a42e1e6760afb5d6a763d94198fdaf0e0eebcf2eec"


def digest(value):
    return sha256(canonical_json(value).encode("ascii")).hexdigest()


def candidate(claim):
    def normalize_numbers(value):
        # Browser JSON serializes 1.0 as 1. Do not confuse that with a changed box.
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {k: normalize_numbers(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [normalize_numbers(v) for v in value]
        return value

    return normalize_numbers(
        {k: claim[k] for k in ("quote", "page", "track", "parser_source", "normalized", "elements")}
    )


def load_review():
    if not REVIEW_PATH.exists():
        return None
    raw = REVIEW_PATH.read_bytes()
    if sha256(raw).hexdigest() != REVIEW_SHA256:
        return None
    data = json.loads(raw)
    if data["rulepack"]["tenant_id"] != data["source_tenant_id"]:
        return None
    return data


def apply_review(claim, source_sha256, manifest_sha256):
    review = load_review()
    if not review or (source_sha256, manifest_sha256) != (
        review["source_sha256"],
        review["manifest_sha256"],
    ):
        return False
    packet_hash = digest(candidate(claim))
    entry = review["claims"].get(packet_hash)
    if entry is None or not claim.get("source_verified"):
        return False
    pack = RulePackSnapshot(**review["rulepack"])
    identity = review["identity"]
    claim_id = str(uuid5(NAMESPACE_URL, source_sha256 + packet_hash))
    fact_refs = {}
    facts = []
    for name in entry["accepted_facts"]:
        evidence = entry["fact_sources"][name]
        fact_ref = SourceRef(**evidence["ref"])
        fact_refs[name] = fact_ref
        facts.append(
            ConfirmedFact(
                name=name,
                state="present",
                evidence_refs=(fact_ref,),
                source_tenant_id=pack.tenant_id,
                citation_verified=True,
                binding_accepted=True,
                source_scope=evidence["scope"],
                normalized_value=evidence.get("normalized_value"),
            )
        )
    tags = ConfirmedTags(
        tenant_id=pack.tenant_id,
        document_version_id=identity["document_version_id"],
        claim_id=claim_id,
        track=claim["track"],
        facts=facts,
        tag_revision=1,
        packet_sha256=packet_hash,
        model_sha256=digest("retained single model candidate"),
        prompt_sha256=digest("source visual review, not replicated model tagging"),
        replicate_hashes=(),
        ontology_version=pack.ontology_version,
        evidence_review=EvidenceReview(
            reviewer=review["reviewer"],
            reviewed_at=review["reviewed_at"],
            source_authority=review["source_authority"],
            packet_sha256=packet_hash,
            record_sha256=REVIEW_SHA256,
        ),
    )
    decision = evaluate(
        tags,
        RuleContext(
            tenant_id=pack.tenant_id,
            document_version_id=identity["document_version_id"],
            claim_id=claim_id,
            packet_sha256=packet_hash,
        ),
        pack,
    )
    claim["decision"] = decision.to_api_dict()
    claim["decision"]["gate_reasons"] = (
        ["규칙 승인·명시 근거 검토 완료; 상위 등급 요소의 근거 또는 부재 확인 필요"]
        if decision.evidence_grade is None
        else []
    )
    claim["review"] = dict(
        status="reviewed",
        origin="ai_project_interpretation",
        expert_gold=False,
        record_sha256=REVIEW_SHA256,
        candidate_sha256=packet_hash,
        notes=entry["notes"],
        accepted_facts=entry["accepted_facts"],
        scope="해당 인용·표 셀의 명시 근거; 문서 전체의 요소 부재를 확인한 것은 아님",
    )
    claim["crosscheck"]["review_status"] = "source_reviewed"
    # Preserve the original independent parser disagreement, never rename it consensus.
    claim["blocked_reason"] = " · ".join(claim["decision"]["gate_reasons"])
    for element in claim["elements"]:
        if element["name"] in entry["accepted_facts"]:
            element.update(
                state="present",
                binding_status="reviewed",
                source_verified=True,
                review_source=asdict(fact_refs[element["name"]]),
                page=fact_refs[element["name"]].page_num,
                quote=fact_refs[element["name"]].quote,
            )
        elif element.get("candidate_state") == "present":
            element["binding_status"] = "not_accepted_by_review"
    for name in entry["accepted_facts"]:
        if not any(e["name"] == name for e in claim["elements"]):
            raise ValueError("reviewed fact missing from element catalog")
    for field, value in entry.get("normalized_changes", {}).items():
        previous = deepcopy(claim["normalized"].get(field))
        claim["normalized"][field] = dict(
            value=value,
            status="reviewed",
            previous_candidate=previous,
            review_record_sha256=REVIEW_SHA256,
        )
    return True


def review_chart(vision, source_sha256):
    review = load_review()
    if not review or source_sha256 != review["source_sha256"]:
        return
    # Exact full vision result binding prevents this correction leaking to other charts.
    if digest(chart_candidates(vision)) != review["vision_sha256"]:
        return

    def visit(value):
        if isinstance(value, dict):
            if value.get("series") == "실제 집약도":
                value["original_series"] = value["series"]
                value["series"] = "실질 집약도"
                value["label_review"] = "원문 범례 직접 확인"
            if value.get("role") in ("target", "actual", "achievement") and "value" in value:
                value["review_status"] = "source_reviewed"
            for child in list(value.values()):
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(vision)
    vision["review_record_sha256"] = REVIEW_SHA256


def chart_candidates(vision):
    return [
        dict(page=p["page"], points=p.get("chart_bindings", {}).get("points", []))
        for p in vision.get("pages", [])
    ]
