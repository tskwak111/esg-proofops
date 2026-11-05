"""Request parsing and policy-specific correction validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import (
    MAPPINGS,
    ConfirmedFact,
)
from proofops.domain.rules.safe_harbor import CHECKLIST_POLICY_V1
from proofops.domain.values import (
    LlmElement,
    _element_from_dict,
    _source_ref_from_dict,
)

from .contracts import CATEGORY_POLICY_V1, ReviewRejected, SourceVerifier
from .inputs import ReviewInputs


def parse_resolution(body: Any) -> tuple[LlmElement, ...]:
    if not isinstance(body, dict) or set(body) != {
        "base_tag_revision",
        "track",
        "elements",
        "reason",
    }:
        raise ReviewRejected("VALIDATION_ERROR")
    if (
        type(body["base_tag_revision"]) is not int
        or body["base_tag_revision"] < 1
        or not isinstance(body["track"], str)
        or body["track"] not in MAPPINGS
        or not isinstance(body["reason"], str)
        or not 5 <= len(body["reason"].strip()) <= 1000
        or not isinstance(body["elements"], list)
    ):
        raise ReviewRejected("VALIDATION_ERROR")
    elements = tuple(_element_from_dict(e) for e in body["elements"])
    identifiers = [e.element_id for e in elements]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(
        MAPPINGS[body["track"]]
    ):
        raise ReviewRejected("COMPLETE_TRACK_ELEMENTS_REQUIRED")
    return elements


def _review_applicability(
    inputs: ReviewInputs,
    track: str,
    review: Any,
    *,
    verify_source_ref: SourceVerifier = verify_source_ref,
) -> tuple[list[ConfirmedFact], dict[str, Any]]:
    """Verify complete atomic-claim coverage, never report-wide search absence."""
    if not isinstance(review, dict) or set(review) != {
        "policy",
        "input_snapshot_sha256",
        "track",
        "claim_source_refs",
        "source_authority",
        "triggers",
    }:
        raise ReviewRejected("APPLICABILITY_REVIEW_INVALID")
    if (
        review["policy"] != "local_claim_applicability_v1"
        or review["track"] != track
        or review["input_snapshot_sha256"] != canonical_hash(inputs.snapshot())
        or not isinstance(review["source_authority"], str)
        or not 5 <= len(review["source_authority"].strip()) <= 1000
        or not isinstance(review["triggers"], list)
        or not review["triggers"]
    ):
        raise ReviewRejected("APPLICABILITY_REVIEW_INVALID")
    claim = inputs.context.claim
    # Exact complete refs from the replayed loader, not caller-selected subquotes.
    if not claim.source_refs or canonical_hash(review["claim_source_refs"]) != canonical_hash(
        [asdict(ref) for ref in claim.source_refs]
    ):
        raise ReviewRejected("WHOLE_CLAIM_REQUIRED")
    refs = tuple(
        verify_source_ref(ref, inputs.original, tenant_id=claim.tenant_id)
        for ref in claim.source_refs
    )
    if any(ref.verification_state != "verified" for ref in refs):
        raise ReviewRejected("SOURCE_REJECTED")
    allowed = {
        element["trigger"]
        for element in inputs.rulepack.file_content("rubric/elements.yaml")["elements"]
        if element["id"] in MAPPINGS[track]
        and element.get("requirement") == "conditional"
        and element.get("trigger")
        in {
            "offset_or_carbon_neutral_claim",
            "science_based_claim",
            "reduction_or_improvement_claim",
            "governance_claim",
            "compensation_link_claim",
        }
    }
    # The management §4.4 E0 branch ("의지 표현만") is also a whole-claim judgment;
    # accept it only where the pinned track ladder actually uses it.
    branches = inputs.rulepack.file_content(f"rubric/{track}.yaml")["branches"]
    if any("willingness_only" in branch.get("when", {}) for branch in branches):
        allowed.add("willingness_only")
    facts, seen = [], set()
    for trigger in review["triggers"]:
        if not isinstance(trigger, dict) or set(trigger) != {"name", "value", "reason"}:
            raise ReviewRejected("APPLICABILITY_REVIEW_INVALID")
        name, value = trigger["name"], trigger["value"]
        if (
            not isinstance(name, str)
            or name not in allowed
            or name in seen
            or (value is not None and type(value) is not bool)
            or not isinstance(trigger["reason"], str)
            or not 5 <= len(trigger["reason"].strip()) <= 1000
        ):
            raise ReviewRejected("APPLICABILITY_REVIEW_INVALID")
        seen.add(name)
        facts.append(
            ConfirmedFact(
                name=name,
                state="unknown" if value is None else ("present" if value else "absent"),
                evidence_refs=refs,
                source_tenant_id=claim.tenant_id,
                citation_verified=True,
                binding_accepted=True,
                search_coverage_verified=value is False,
                source_scope="local_claim",
            )
        )
    receipt = dict(
        request=review,
        identity=dict(
            tenant_id=claim.tenant_id,
            document_version_id=claim.document_version_id,
            claim_id=claim.claim_id,
            run_id=inputs.run_id,
            parse_manifest_id=inputs.original.parse_manifest_id,
            source_sha256=inputs.original.source_sha256,
            graph_sha256=canonical_hash(asdict(inputs.original)),
            claim_sha256=canonical_hash(asdict(claim)),
            packet_sha256=inputs.packet.packet_sha256,
            original_packet_sha256=inputs.original_packet.packet_sha256,
            rulepack_sha256=inputs.rulepack.sha256,
            input_snapshot_sha256=canonical_hash(inputs.snapshot()),
        ),
        verified_claim_source_refs=[asdict(ref) for ref in refs],
        coverage_scope="local_claim",
    )
    return facts, receipt


def _review_safe_harbor(
    inputs: ReviewInputs, review: Any, *, verify_source_ref: SourceVerifier = verify_source_ref
) -> tuple[list[ConfirmedFact], dict[str, Any]]:
    """Create only explicit checklist facts from replayed packet references."""
    if not isinstance(review, dict) or set(review) != {
        "policy",
        "input_snapshot_sha256",
        "category",
        "source_authority",
        "facts",
    }:
        raise ReviewRejected("SAFE_HARBOR_REVIEW_INVALID")
    config = inputs.rulepack.file_content("regulatory/safe_harbor.yaml")
    category = review["category"]
    try:
        expected = tuple(config["category_checklists"][category])
    except (KeyError, TypeError):
        raise ReviewRejected("SAFE_HARBOR_REVIEW_INVALID") from None
    packet = inputs.packet.to_dict()
    headers = {
        run.guarded.safe_harbor_category for run in inputs.tag_runs if run.guarded is not None
    }
    if (
        review["policy"] != CHECKLIST_POLICY_V1
        or config.get("reasonable_basis_boolean_mapping") != CHECKLIST_POLICY_V1
        or review["input_snapshot_sha256"] != canonical_hash(inputs.snapshot())
        or not isinstance(category, str)
        or not expected
        or headers != {category}
        or packet.get("safe_harbor_category") != category
        or not isinstance(review["source_authority"], str)
        or not 5 <= len(review["source_authority"].strip()) <= 1000
        or not isinstance(review["facts"], list)
        or len(review["facts"]) != len(expected)
    ):
        raise ReviewRejected("SAFE_HARBOR_REVIEW_INVALID")

    packet_refs = _packet_ref_index(packet)

    facts, seen, verified_refs = [], set(), []
    for item in review["facts"]:
        if not isinstance(item, dict) or set(item) != {
            "name",
            "state",
            "evidence_refs",
            "search_coverage_verified",
            "reason",
        }:
            raise ReviewRejected("SAFE_HARBOR_REVIEW_INVALID")
        name, state = item["name"], item["state"]
        if (
            name not in expected
            or name in seen
            or state not in ("present", "absent", "unknown", "conflict")
            or not isinstance(item["evidence_refs"], list)
            or type(item["search_coverage_verified"]) is not bool
            or item["search_coverage_verified"] != (state == "absent")
            or not isinstance(item["reason"], str)
            or not 5 <= len(item["reason"].strip()) <= 1000
            or (state in ("present", "absent", "conflict") and not item["evidence_refs"])
        ):
            raise ReviewRejected("SAFE_HARBOR_REVIEW_INVALID")
        seen.add(name)
        refs, scopes = [], set()
        for raw in item["evidence_refs"]:
            match = packet_refs.get(canonical_hash(raw)) if isinstance(raw, dict) else None
            if match is None or match[1] not in ("local_claim", "same_table"):
                raise ReviewRejected("SAFE_HARBOR_SOURCE_REJECTED")
            checked = verify_source_ref(
                _source_ref_from_dict(raw),
                inputs.original,
                tenant_id=inputs.context.claim.tenant_id,
            )
            if checked.verification_state != "verified":
                raise ReviewRejected("SAFE_HARBOR_SOURCE_REJECTED")
            refs.append(checked)
            scopes.add(match[1])
            verified_refs.append(asdict(checked))
        facts.append(
            ConfirmedFact(
                name=name,
                state=state,
                evidence_refs=tuple(refs),
                source_tenant_id=inputs.context.claim.tenant_id if refs else None,
                citation_verified=bool(refs),
                binding_accepted=bool(refs),
                search_coverage_verified=item["search_coverage_verified"],
                source_scope="same_table" if "same_table" in scopes else "local_claim",
            )
        )
    if seen != set(expected):
        raise ReviewRejected("SAFE_HARBOR_REVIEW_INVALID")
    receipt: dict[str, Any] = {
        "request": review,
        "identity": {
            "tenant_id": inputs.context.claim.tenant_id,
            "document_version_id": inputs.context.claim.document_version_id,
            "claim_id": inputs.context.claim.claim_id,
            "run_id": inputs.run_id,
            "parse_manifest_id": inputs.original.parse_manifest_id,
            "source_sha256": inputs.original.source_sha256,
            "graph_sha256": canonical_hash(asdict(inputs.original)),
            "packet_sha256": inputs.packet.packet_sha256,
            "rulepack_sha256": inputs.rulepack.sha256,
            "input_snapshot_sha256": canonical_hash(inputs.snapshot()),
        },
        "verified_packet_source_refs": verified_refs,
    }
    return facts, receipt


def _packet_ref_index(packet: Mapping[str, Any]) -> dict[str, tuple[dict[str, Any], str]]:
    """Index the immutable packet's own references by canonical hash and scope."""
    packet_refs: dict[str, tuple[dict[str, Any], str]] = {}
    for raw in packet.get("claim_source_refs", []):
        packet_refs[canonical_hash(raw)] = (raw, "local_claim")
    for candidate in packet.get("evidence_candidates", []):
        scope = candidate.get("source_scope")
        for raw in candidate.get("source_refs", []):
            packet_refs.setdefault(canonical_hash(raw), (raw, scope))
    return packet_refs


def _review_category(
    inputs: ReviewInputs,
    track: str,
    review: Any,
    *,
    verify_source_ref: SourceVerifier = verify_source_ref,
) -> tuple[None, dict[str, Any], tuple[str, ...]]:
    """Validate an explicit removal of a wrong safe-harbor category; create no fact.

    The request must PIN what the models and the frozen packet actually said:
    the observed category is checked against every guarded tag-run header and
    against the packet value, so this is not an override that ignores those
    checks. Nothing here rewrites a header, a packet or a replica hash, and no
    ``ConfirmedFact`` is produced -- a category is a classification header, not
    an observed fact. Returns ``(corrected_category, receipt, superseded_names)``.
    """
    if not isinstance(review, dict) or set(review) != {
        "policy",
        "input_snapshot_sha256",
        "track",
        "observed_category",
        "corrected_category",
        "claim_source_refs",
        "basis_refs",
        "source_authority",
        "reason",
    }:
        raise ReviewRejected("CATEGORY_REVIEW_INVALID")
    config = inputs.rulepack.file_content("regulatory/safe_harbor.yaml")
    checklists = config.get("category_checklists") or {}
    observed = review["observed_category"]
    if (
        review["policy"] != CATEGORY_POLICY_V1
        or review["track"] != track
        or review["input_snapshot_sha256"] != canonical_hash(inputs.snapshot())
        # Only a category this pinned regulatory config defines can be removed;
        # an unknown name is escalated instead of silently dropped.
        or not isinstance(observed, str)
        or observed not in checklists
        or not isinstance(review["claim_source_refs"], list)
        or not isinstance(review["basis_refs"], list)
        or not review["basis_refs"]
        or any(
            not isinstance(text, str) or not 5 <= len(text.strip()) <= 1000
            for text in (review["source_authority"], review["reason"])
        )
    ):
        raise ReviewRejected("CATEGORY_REVIEW_INVALID")
    if review["corrected_category"] is not None:
        raise ReviewRejected("CATEGORY_CORRECTION_UNSUPPORTED")
    packet = inputs.packet.to_dict()
    headers = {
        run.guarded.safe_harbor_category for run in inputs.tag_runs if run.guarded is not None
    }
    if headers != {observed} or packet.get("safe_harbor_category") != observed:
        raise ReviewRejected("CATEGORY_REVIEW_OBSERVED_MISMATCH", 409)
    claim = inputs.context.claim
    # A category is a property of the whole atomic claim, so the replayed loader
    # refs must match exactly; caller-selected subquotes are refused.
    if not claim.source_refs or canonical_hash(review["claim_source_refs"]) != canonical_hash(
        [asdict(ref) for ref in claim.source_refs]
    ):
        raise ReviewRejected("WHOLE_CLAIM_REQUIRED")
    claim_refs = tuple(
        verify_source_ref(ref, inputs.original, tenant_id=claim.tenant_id)
        for ref in claim.source_refs
    )
    if any(ref.verification_state != "verified" for ref in claim_refs):
        raise ReviewRejected("CATEGORY_SOURCE_REJECTED")
    packet_refs = _packet_ref_index(packet)
    basis_refs = []
    for raw in review["basis_refs"]:
        match = packet_refs.get(canonical_hash(raw)) if isinstance(raw, dict) else None
        if match is None or match[1] not in ("local_claim", "same_table"):
            raise ReviewRejected("CATEGORY_SOURCE_REJECTED")
        checked = verify_source_ref(
            _source_ref_from_dict(raw), inputs.original, tenant_id=claim.tenant_id
        )
        if checked.verification_state != "verified":
            raise ReviewRejected("CATEGORY_SOURCE_REJECTED")
        basis_refs.append(asdict(checked))
    receipt: dict[str, Any] = {
        "request": review,
        "identity": {
            "tenant_id": claim.tenant_id,
            "document_version_id": claim.document_version_id,
            "claim_id": claim.claim_id,
            "run_id": inputs.run_id,
            "parse_manifest_id": inputs.original.parse_manifest_id,
            "source_sha256": inputs.original.source_sha256,
            "graph_sha256": canonical_hash(asdict(inputs.original)),
            "claim_sha256": canonical_hash(asdict(claim)),
            "packet_sha256": inputs.packet.packet_sha256,
            "original_packet_sha256": inputs.original_packet.packet_sha256,
            "rulepack_sha256": inputs.rulepack.sha256,
            "input_snapshot_sha256": canonical_hash(inputs.snapshot()),
        },
        "observed_category": observed,
        "corrected_category": None,
        # The models' own words stay recorded next to the correction.
        "observed_tag_run_headers": [
            run.guarded.safe_harbor_category for run in inputs.tag_runs if run.guarded is not None
        ],
        "observed_packet_safe_harbor_category": packet.get("safe_harbor_category"),
        "superseded_checklist_items": [
            name for name in checklists.get(observed, ()) if isinstance(name, str)
        ],
        "verified_claim_source_refs": [asdict(ref) for ref in claim_refs],
        "verified_basis_refs": basis_refs,
    }
    return None, receipt, tuple(receipt["superseded_checklist_items"])
