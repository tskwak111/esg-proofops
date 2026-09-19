"""Human tag revisions; source guards and pure rules are the only grading path."""

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
from proofops.domain.values import SourceRef, _element_from_dict, _require_uuid


class ReviewRejected(ValueError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class ReviewInputs:
    """Trusted loader boundary; retain complete packets, graph and actual tag receipts.

    A missing consensus is a valid initial revision. No model call is made here.
    Existing confirmed facts are the only absence/applicability/computation
    attestations; the HTTP body cannot create those attestations.
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
            new_facts = [f for n, f in facts.items() if n not in previous_names]
            checked_elements = []
            definitions = {
                e["id"]: e for e in inputs.rulepack.file_content("rubric/elements.yaml")["elements"]
            }
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
            # Preserve the engine semantic hash exactly; human status is provenance metadata.
            api = decision.to_api_dict() | {"review_status": "human_confirmed"}
            tag = dict(
                tag_revision=confirmed.tag_revision,
                confirmed_tags=asdict(confirmed),
                elements=checked_elements,
                origin="human",
                reviewer_sub=actor.user_sub,
                review_reason=body["reason"],
                input_snapshot_sha256=canonical_hash(initial["inputs"]),
            )
            return tag, dict(
                decision_revision=decision_revision, decision=asdict(decision), api=api
            )

        try:
            return self.store.resolve(
                actor, review_id, body, int(if_match[1:-1]), idempotency_key, build
            )
        except KeyError:
            raise ReviewRejected("REVIEW_INPUT_UNAVAILABLE", 409) from None
        except AuditConflict:
            raise ReviewRejected("REVIEW_CONFLICT", 409) from None
        except DomainValidationError:
            raise ReviewRejected("VALIDATION_ERROR") from None
