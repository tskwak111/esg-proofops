"""Human tag revisions; source guards and pure rules are the only grading path.

An additive, explicitly-delegated AI review route exists for a trusted local
operator (``ReviewService.resolve_ai_delegated_review``). It reuses the exact
same source/binding/If-Match/engine guards as the human route and records an
honest ``ai_delegated`` origin -- it never writes ``human`` provenance for
machine-driven work. The HTTP body can never self-assert provenance: both
routes accept only the fixed 4-key correction body, and the AI origin is
supplied by backend constructor arguments, never by caller JSON.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any, Protocol
from unicodedata import normalize
from uuid import NAMESPACE_URL, uuid5

from proofops.application.authorization import AuthContext
from proofops.application.evidence.binding import ClaimContext, accept_binding, relation_tags_for
from proofops.application.evidence.retrieval import EvidencePacket
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.tagging.consensus import ConsensusResult, form_consensus
from proofops.application.tagging.service import TagRun
from proofops.domain.audit import AuditConflict
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import (
    MAPPINGS,
    ConfirmedFact,
    ConfirmedTags,
    Decision,
    RuleContext,
    evaluate,
)
from proofops.domain.rules.safe_harbor import CHECKLIST_POLICY_V1
from proofops.domain.values import (
    SourceRef,
    _element_from_dict,
    _require_uuid,
    _source_ref_from_dict,
)


class ReviewRejected(ValueError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code, self.status = code, status


# Honest provenance labels for the additive AI-delegated route. Reuses the
# rulepack-activation prefix pattern (``ai-delegated-review:<operator>``) so a
# machine-driven revision can never be mistaken for an independent human
# confirmation. Old ``human``/``consensus`` rows stay valid and immutable.
AI_DELEGATED_ORIGIN = "ai_delegated"
AI_DELEGATED_REVIEW_STATUS = "ai_delegated_confirmed"
AI_DELEGATED_REVIEWER_PREFIX = "ai-delegated-review:"
AI_DELEGATED_REVIEW_ORIGIN = "ai_project_interpretation"
HUMAN_ORIGIN = "human"
HUMAN_REVIEW_STATUS = "human_confirmed"


@dataclass(frozen=True)
class ReviewInputs:
    """Trusted loader boundary; retain complete packets, graph and actual tag receipts.

    A missing consensus is a valid initial revision. No model call is made here.
    Existing confirmed facts are the only ordinary element absence/computation
    attestations. Only the trusted AI route can review local claim triggers or
    policy-pinned safe-harbor facts; the HTTP body cannot create those attestations.
    """

    run_id: str
    context: ClaimContext
    original: CanonicalDocumentGraph
    rulepack: RulePackSnapshot
    rule_context: RuleContext
    packet: EvidencePacket
    original_packet: EvidencePacket
    tag_runs: tuple[TagRun, ...]
    consensus: ConsensusResult
    relation_tags: Mapping[str, Mapping[str, SourceRef | None]]
    tag_revision: int = 1
    decision: Decision | None = None

    def snapshot(self) -> dict:
        return dict(
            schema="review_inputs_v1",
            run_id=self.run_id,
            claim=asdict(self.context.claim),
            dimensions={k: asdict(v) if v else None for k, v in self.context.dimensions.items()},
            original=dict(
                graph_sha256=canonical_hash(asdict(self.original)),
                tenant_id=self.original.tenant_id,
                document_version_id=self.original.document_version_id,
                parse_manifest_id=self.original.parse_manifest_id,
                source_sha256=self.original.source_sha256,
            ),
            rulepack=asdict(self.rulepack),
            rule_context=asdict(self.rule_context),
            packet=self.packet.to_dict(),
            packet_sha256=self.packet.packet_sha256,
            original_packet=self.original_packet.to_dict(),
            original_packet_sha256=self.original_packet.packet_sha256,
            tag_runs=[asdict(r) for r in self.tag_runs],
            consensus=asdict(self.consensus),
            relation_tags={
                key: {k: asdict(v) if v else None for k, v in value.items()}
                for key, value in self.relation_tags.items()
            },
            tag_revision=self.tag_revision,
            decision=asdict(self.decision) if self.decision else None,
            execution_profile="local-synthetic-only"
            if self.rule_context.local_synthetic
            else "live",
        )

    def validate(self) -> None:
        claim, data = self.context.claim, self.packet.to_dict()
        if (
            (claim.tenant_id, self.original.tenant_id, self.rulepack.tenant_id)
            != (self.rule_context.tenant_id,) * 3
            or (claim.document_version_id, claim.claim_id, self.packet.packet_sha256)
            != (
                self.rule_context.document_version_id,
                self.rule_context.claim_id,
                self.rule_context.packet_sha256,
            )
            or data["run_id"] != self.run_id
            or data["graph_sha256"] != canonical_hash(asdict(self.original))
            or data.get("retrieval_packet_sha256") != self.original_packet.packet_sha256
            or type(self.tag_revision) is not int
            or self.tag_revision < 1
        ):
            raise ReviewRejected("REVIEW_INPUT_MISMATCH", 409)
        result = form_consensus(
            self.tag_runs,
            packet=self.packet,
            rulepack=self.rulepack,
            tenant_id=claim.tenant_id,
            tag_revision=self.tag_revision,
        )
        if result.replicate_hashes != self.consensus.replicate_hashes:
            raise ReviewRejected("REVIEW_RECEIPT_MISMATCH", 409)
        if self.consensus.confirmed_tags is not None and (
            self.consensus.confirmed_tags != result.confirmed_tags
        ):
            raise ReviewRejected("REVIEW_CONFIRMATION_MISMATCH", 409)
        if self.decision is not None and (
            self.consensus.confirmed_tags is None
            or evaluate(self.consensus.confirmed_tags, self.rule_context, self.rulepack)
            != self.decision
        ):
            raise ReviewRejected("REVIEW_DECISION_MISMATCH", 409)


class ReviewStore(Protocol):
    def publish(self, inputs: ReviewInputs, review: dict) -> dict: ...
    def publish_transaction(self, db, inputs: ReviewInputs, review: dict) -> dict: ...
    def get(self, tenant_id: str, review_id: str) -> dict: ...
    def resolve(
        self,
        actor: AuthContext,
        review_id: str,
        body: dict,
        expected: int,
        key: str,
        build: Callable,
    ) -> dict: ...


def parse_resolution(body: Any):
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


def _review_applicability(inputs: ReviewInputs, track: str, review: Any):
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


def _review_safe_harbor(inputs: ReviewInputs, review: Any):
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

    packet_refs: dict[str, tuple[dict, str]] = {}
    for raw in packet.get("claim_source_refs", []):
        packet_refs[canonical_hash(raw)] = (raw, "local_claim")
    for candidate in packet.get("evidence_candidates", []):
        scope = candidate.get("source_scope")
        for raw in candidate.get("source_refs", []):
            packet_refs.setdefault(canonical_hash(raw), (raw, scope))

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
    receipt = {
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


class ReviewService:
    def __init__(self, store: ReviewStore, *, load_inputs: Callable[[str, str, str], ReviewInputs]):
        self.store, self.load_inputs = store, load_inputs

    def _review(self, inputs: ReviewInputs, review_id: str | None = None) -> dict:
        inputs.validate()
        claim = inputs.context.claim
        review_id = review_id or str(uuid5(NAMESPACE_URL, canonical_hash(inputs.snapshot())))
        _require_uuid("review_id", review_id)
        review = dict(
            review_id=review_id,
            run_id=inputs.run_id,
            claim_id=claim.claim_id,
            status="open",
            revision=1,
            base_tag_revision=inputs.tag_revision,
            reason_codes=list(inputs.consensus.reasons)
            + (
                []
                if inputs.rule_context.local_synthetic
                or (
                    inputs.rulepack.status == "active"
                    and inputs.rulepack.approved_by
                    and inputs.rulepack.approved_at
                )
                else ["RULEPACK_APPROVAL_REQUIRED"]
            ),
        )
        return review

    def publish(self, inputs: ReviewInputs, review_id: str | None = None) -> dict:
        return self.store.publish(inputs, self._review(inputs, review_id))

    def publish_transaction(self, connection, inputs: ReviewInputs, review_id: str | None = None):
        return self.store.publish_transaction(connection, inputs, self._review(inputs, review_id))

    def resolve_review(self, actor, review_id, body, if_match, idempotency_key):
        """Default human route: provenance is always human, never caller-chosen."""
        return self._resolve_with_provenance(
            actor,
            review_id,
            body,
            if_match,
            idempotency_key,
            origin=HUMAN_ORIGIN,
            review_status=HUMAN_REVIEW_STATUS,
            reviewer_sub=None,
            extra_tag=None,
        )

    def resolve_ai_delegated_review(
        self,
        actor,
        review_id,
        body,
        if_match,
        idempotency_key,
        *,
        delegated_reviewer: str,
        delegation_authority: str,
        applicability_review: dict | None = None,
        safe_harbor_review: dict | None = None,
    ):
        """Trusted backend-only operation for explicit user-delegated AI review.

        Not reachable from HTTP: ``delegated_reviewer`` and
        ``delegation_authority`` are constructor arguments supplied by local
        operator code (the CLI), never parsed from the correction body, so a
        remote caller cannot self-assert trusted provenance. All factual
        guards (source/binding/If-Match/engine) also apply here. Optional
        applicability and safe-harbor reviews are separately pinned and cannot
        authorize ordinary element absence or a caller-supplied grade.
        """
        if not isinstance(delegated_reviewer, str) or not delegated_reviewer.strip():
            raise ReviewRejected("VALIDATION_ERROR")
        if not isinstance(delegation_authority, str) or not delegation_authority.strip():
            raise ReviewRejected("VALIDATION_ERROR")
        reviewer = delegated_reviewer.strip()
        if len(reviewer) > 320 or "\n" in reviewer:
            raise ReviewRejected("VALIDATION_ERROR")
        return self._resolve_with_provenance(
            actor,
            review_id,
            body,
            if_match,
            idempotency_key,
            origin=AI_DELEGATED_ORIGIN,
            review_status=AI_DELEGATED_REVIEW_STATUS,
            reviewer_sub=f"{AI_DELEGATED_REVIEWER_PREFIX}{reviewer}",
            extra_tag={
                "review_origin": AI_DELEGATED_REVIEW_ORIGIN,
                "delegation_authority": delegation_authority.strip(),
                "delegated_reviewer": reviewer,
            },
            applicability_review=applicability_review,
            safe_harbor_review=safe_harbor_review,
        )

    def _resolve_with_provenance(
        self,
        actor,
        review_id,
        body,
        if_match,
        idempotency_key,
        *,
        origin,
        review_status,
        reviewer_sub,
        extra_tag,
        applicability_review=None,
        safe_harbor_review=None,
    ):
        if not isinstance(actor, AuthContext) or not actor.has_capability("reviewer"):
            raise ReviewRejected("FORBIDDEN", 403)
        _require_uuid("review_id", review_id)
        if not isinstance(if_match, str) or not re.fullmatch(r'"[1-9][0-9]*"', if_match):
            raise ReviewRejected("IF_MATCH_REQUIRED", 400)
        if not isinstance(idempotency_key, str) or not 16 <= len(idempotency_key) <= 128:
            raise ReviewRejected("IDEMPOTENCY_KEY_INVALID", 400)
        elements = parse_resolution(body)

        # Existing local read adapters open transactions too. Load the immutable
        # inputs before the writer lock; the transaction still compares pins and
        # both heads before publishing anything.
        target = self.store.get(actor.tenant_id, review_id)
        try:
            inputs = self.load_inputs(actor.tenant_id, target["run_id"], target["claim_id"])
        except KeyError:
            raise ReviewRejected("REVIEW_INPUT_UNAVAILABLE", 409) from None
        if not inputs.rule_context.local_synthetic and not (
            inputs.rulepack.status == "active"
            and inputs.rulepack.approved_by
            and inputs.rulepack.approved_at
        ):
            raise ReviewRejected("RULEPACK_APPROVAL_REQUIRED", 409)

        def build(review, initial, decision_revision):
            inputs.validate()
            if canonical_hash(inputs.snapshot()) != canonical_hash(initial["inputs"]):
                raise ReviewRejected("REVIEW_INPUT_MISMATCH", 409)
            base = inputs.consensus.confirmed_tags
            facts = {f.name: f for f in base.facts} if base else {}
            previous_names = {
                n for names in MAPPINGS[inputs.packet.to_dict()["track"]].values() for n in names
            }
            definitions = {
                e["id"]: e for e in inputs.rulepack.file_content("rubric/elements.yaml")["elements"]
            }
            trigger_names = {e["trigger"] for e in definitions.values() if e.get("trigger")}
            # A changed track requires fresh applicability, never inherited trigger tags.
            if body["track"] != inputs.packet.to_dict()["track"]:
                previous_names |= trigger_names
            reviewed_facts, applicability_receipt = ([], None)
            if applicability_review is not None:
                reviewed_facts, applicability_receipt = _review_applicability(
                    inputs, body["track"], applicability_review
                )
                previous_names |= {f.name for f in reviewed_facts}
            safe_harbor_facts, safe_harbor_receipt = ([], None)
            if safe_harbor_review is not None:
                safe_harbor_facts, safe_harbor_receipt = _review_safe_harbor(
                    inputs, safe_harbor_review
                )
                previous_names |= {f.name for f in safe_harbor_facts}
            new_facts = [f for n, f in facts.items() if n not in previous_names] + reviewed_facts
            new_facts += safe_harbor_facts
            checked_elements = []
            for element in elements:
                names = MAPPINGS[body["track"]][element.element_id]
                previous = [facts.get(name) for name in names]
                refs = tuple(
                    verify_source_ref(ref, inputs.original, tenant_id=actor.tenant_id)
                    for ref in element.evidence_refs
                )
                if any(ref.verification_state != "verified" for ref in refs):
                    raise ReviewRejected("SOURCE_REJECTED")
                if element.state in ("absent", "not_applicable"):
                    if not all(
                        f
                        and f.state == element.state
                        and (element.state != "absent" or f.search_coverage_verified)
                        for f in previous
                    ):
                        raise ReviewRejected("COVERAGE_OR_APPLICABILITY_REQUIRED")
                scope = "local_claim"
                if element.state == "present":
                    if element.element_id in ("P4", "P6"):
                        # Dedicated assurance/numeric results cannot be typed into existence.
                        if not all(
                            f
                            and f.state == "present"
                            and f.evidence_refs == refs
                            and f.normalized_value == element.normalized_value
                            for f in previous
                        ):
                            raise ReviewRejected("DETERMINISTIC_CHECK_REQUIRED")
                        scope = previous[0].source_scope
                    else:
                        scopes = []
                        for ref in refs:
                            if (
                                accept_binding(
                                    inputs.context,
                                    ref,
                                    relation_tags_for(ref, inputs.relation_tags),
                                    original=inputs.original,
                                    tenant_id=actor.tenant_id,
                                    rulepack=inputs.rulepack,
                                    element_id=element.element_id,
                                )
                                != "accepted"
                            ):
                                raise ReviewRejected("BINDING_REJECTED")
                            local = any(
                                s.source_id == ref.source_id
                                and s.char_start <= ref.char_start
                                and ref.char_end <= s.char_end
                                for s in inputs.context.claim.source_refs
                            )
                            scopes.append(
                                "local_claim"
                                if local
                                else (
                                    "global_bound"
                                    if "global_bound"
                                    in definitions[element.element_id]["source_scopes"]
                                    else "same_table"
                                )
                            )
                        scope = (
                            "global_bound"
                            if "global_bound" in scopes
                            else ("same_table" if "same_table" in scopes else "local_claim")
                        )
                        value = element.normalized_value
                        if (
                            element.element_id in ("G1", "G2", "G3", "G5", "P1", "P2")
                            and value is None
                        ):
                            raise ReviewRejected("SOURCE_VALUE_REQUIRED")
                        if value is not None and not any(
                            " ".join(normalize("NFC", value).split())
                            == " ".join(normalize("NFC", ref.quote).split())
                            for ref in refs
                        ):
                            raise ReviewRejected("SOURCE_VALUE_MISMATCH")
                    if element.credited_from is not None and element.credited_from not in {
                        r.source_id for r in refs
                    }:
                        raise ReviewRejected("CREDITED_SOURCE_MISMATCH")
                new_facts.extend(
                    ConfirmedFact(
                        name,
                        element.state,
                        refs,
                        actor.tenant_id,
                        element.state == "present",
                        element.state == "present",
                        element.state == "absent",
                        scope,
                        element.normalized_value,
                    )
                    for name in names
                )
                checked_elements.append(asdict(replace(element, evidence_refs=refs)))
            headers = {
                (r.guarded.safe_harbor_category, r.guarded.superlative_quote)
                for r in inputs.tag_runs
                if r.guarded
            }
            if len(headers) != 1:
                raise ReviewRejected("CATEGORY_REVIEW_REQUIRED", 409)
            category, superlative = next(iter(headers))
            first = inputs.tag_runs[0]
            confirmed = ConfirmedTags(
                actor.tenant_id,
                inputs.original.document_version_id,
                review["claim_id"],
                body["track"],
                tuple(new_facts),
                body["base_tag_revision"] + 1,
                inputs.packet.packet_sha256,
                first.model_sha256,
                first.prompt_sha256,
                inputs.consensus.replicate_hashes,
                inputs.rulepack.ontology_version,
                category,
                superlative,
                first.product_variant,
            )
            decision = evaluate(
                confirmed,
                replace(inputs.rule_context, decision_revision=decision_revision),
                inputs.rulepack,
            )
            # Preserve the engine semantic hash exactly; review status is provenance metadata.
            api = decision.to_api_dict() | {"review_status": review_status}
            tag = dict(
                tag_revision=confirmed.tag_revision,
                confirmed_tags=asdict(confirmed),
                elements=checked_elements,
                origin=origin,
                reviewer_sub=reviewer_sub if reviewer_sub is not None else actor.user_sub,
                review_reason=body["reason"],
                input_snapshot_sha256=canonical_hash(initial["inputs"]),
            )
            if applicability_receipt is not None:
                tag["applicability_review"] = applicability_receipt
            if safe_harbor_receipt is not None:
                tag["safe_harbor_review"] = safe_harbor_receipt
            if extra_tag:
                tag.update(extra_tag)
            return tag, dict(
                decision_revision=decision_revision, decision=asdict(decision), api=api
            )

        try:
            trusted_options = {}
            if applicability_review is not None:
                trusted_options["applicability_review"] = applicability_review
            if safe_harbor_review is not None:
                trusted_options["safe_harbor_review"] = safe_harbor_review
            return self.store.resolve(
                actor,
                review_id,
                # Include trusted options in retry identity after strict HTTP parsing.
                body | {"_trusted_ai_review": dict(**extra_tag, **trusted_options)}
                if extra_tag and trusted_options
                else body,
                int(if_match[1:-1]),
                idempotency_key,
                build,
            )
        except KeyError:
            raise ReviewRejected("REVIEW_INPUT_UNAVAILABLE", 409) from None
        except AuditConflict:
            raise ReviewRejected("REVIEW_CONFLICT", 409) from None
        except DomainValidationError:
            raise ReviewRejected("VALIDATION_ERROR") from None
