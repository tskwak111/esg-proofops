"""Immutable review input snapshots, replay and initial review metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import EvidencePacket
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.tagging.consensus import (
    PARTIAL_FACTS_PROFILES,
    ConsensusResult,
)
from proofops.application.tagging.fact_assembly_c2 import FactAssemblyReceiptV1
from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE
from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE
from proofops.application.tagging.report_level_link import replay_report_level_link, strict_fallback
from proofops.application.tagging.service import TagRun
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import (
    ConfirmedTags,
    Decision,
    RuleContext,
)
from proofops.domain.values import (
    SourceRef,
    _require_uuid,
)

from .contracts import ReviewRejected


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
    fact_assembly_profile: str = "strict-v1"
    report_level_link: dict[str, Any] | None = None
    report_level_review: tuple[dict[str, Any], ...] = ()
    fact_assembly_receipt: FactAssemblyReceiptV1 | None = None

    def snapshot(self) -> dict[str, Any]:
        snapshot = dict(
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
        if self.fact_assembly_profile in PARTIAL_FACTS_PROFILES:
            snapshot["fact_assembly"] = {
                "profile": self.fact_assembly_profile,
                "sha256": PARTIAL_FACTS_PROFILES[self.fact_assembly_profile],
            }
        if self.report_level_link is not None:
            snapshot["report_level_link"] = self.report_level_link
            snapshot["report_level_review"] = list(self.report_level_review)
        if self.fact_assembly_receipt is not None:
            snapshot["fact_assembly_receipt"] = cast(
                "Callable[[], dict[str, Any]]", self.fact_assembly_receipt.to_dict
            )()
            from proofops.application.tagging.fact_assembly_c3 import POLICY_HASH, PROFILE

            if self.fact_assembly_profile == PROFILE:
                snapshot["fact_assembly"] = dict(profile=PROFILE, sha256=POLICY_HASH)
        if self.fact_assembly_profile == C4_PROFILE and self.fact_assembly_receipt is not None:
            from proofops.application.tagging.fact_assembly_c4 import POLICY_HASH as C4_HASH

            snapshot["fact_assembly"] = dict(profile=C4_PROFILE, sha256=C4_HASH)
        if self.fact_assembly_profile == C3_V2_PROFILE and self.fact_assembly_receipt is not None:
            snapshot["fact_assembly"] = dict(
                profile=C3_V2_PROFILE,
                sha256=cast("Callable[[], dict[str, Any]]", self.fact_assembly_receipt.to_dict)()[
                    "policy_sha256"
                ],
            )
        return snapshot

    def validate(self) -> None:
        claim, data = self.context.claim, self.packet.to_dict()
        from proofops.application.tagging.fact_assembly_c3 import PROFILE, validate_publication

        if self.fact_assembly_profile == C4_PROFILE:
            from proofops.application.tagging.fact_assembly_c4 import (
                validate_publication as c4_validate,
            )

            try:
                cast("Callable[..., object]", c4_validate)(self)
            except (ValueError, KeyError, TypeError) as exc:
                raise ReviewRejected("C4_PUBLICATION_REPLAY_MISMATCH", 409) from exc
            return
        if self.fact_assembly_profile == PROFILE:
            try:
                cast("Callable[..., object]", validate_publication)(self)
            except (ValueError, KeyError, TypeError) as exc:
                raise ReviewRejected("C3_PUBLICATION_REPLAY_MISMATCH", 409) from exc
            return
        if self.fact_assembly_profile == C3_V2_PROFILE:
            from proofops.application.tagging.fact_assembly_c3_v2 import (
                validate_publication as c3_v2_validate,
            )

            try:
                cast("Callable[..., object]", c3_v2_validate)(self)
            except (ValueError, KeyError, TypeError) as exc:
                raise ReviewRejected("C3_V2_PUBLICATION_REPLAY_MISMATCH", 409) from exc
            return
        if self.fact_assembly_receipt is not None:
            from proofops.application.tagging.fact_assembly_c2 import replay

            try:
                cast("Callable[..., object]", replay)(
                    cast("Callable[[], dict[str, Any]]", self.fact_assembly_receipt.to_dict)(),
                    context=self.context,
                    graph=self.original,
                    packet=self.packet,
                    rulepack=self.rulepack,
                    tag_revision=self.tag_revision,
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ReviewRejected("FACT_ASSEMBLY_REPLAY_MISMATCH", 409) from exc
            if self.decision is not None:
                raise ReviewRejected("C2_PUBLICATION_DISABLED", 409)
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
        # Preserve the public replay hook used by existing trusted callers.
        # Resolve it at call time; importing the facade here avoids an import-time cycle.
        from proofops.application.reviews import evaluate, form_consensus

        result = form_consensus(
            self.tag_runs,
            packet=self.packet,
            rulepack=self.rulepack,
            tenant_id=claim.tenant_id,
            tag_revision=self.tag_revision,
            profile=self.fact_assembly_profile,
        )
        if self.report_level_link is not None:
            try:
                result = cast("Callable[..., ConsensusResult]", replay_report_level_link)(
                    result,
                    config=self.report_level_link,
                    context=self.context,
                    graph=self.original,
                    receipts=self.report_level_review,
                    fallback_tags=cast("Callable[..., ConfirmedTags | None]", strict_fallback)(
                        self.tag_runs,
                        self.packet,
                        self.rulepack,
                        claim.tenant_id,
                        self.tag_revision,
                        self.fact_assembly_profile,
                    ),
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ReviewRejected("REPORT_LEVEL_LINK_REPLAY_MISMATCH", 409) from exc
        elif self.report_level_review:
            raise ReviewRejected("REPORT_LEVEL_LINK_REPLAY_MISMATCH", 409)
        if self.report_level_link is not None and (
            result.candidate_elements != self.consensus.candidate_elements
            or result.confirmed_tags != self.consensus.confirmed_tags
            or result.reasons != self.consensus.reasons
            or result.review_status != self.consensus.review_status
        ):
            raise ReviewRejected("REPORT_LEVEL_LINK_REPLAY_MISMATCH", 409)
        if result.replicate_hashes != self.consensus.replicate_hashes:
            raise ReviewRejected("REVIEW_RECEIPT_MISMATCH", 409)
        if self.consensus.confirmed_tags is not None and (
            self.consensus.confirmed_tags != result.confirmed_tags
        ):
            raise ReviewRejected("REVIEW_CONFIRMATION_MISMATCH", 409)
        if (
            self.decision is not None
            and self.decision.decision_status == "decided"
            and (
                self.fact_assembly_profile in PARTIAL_FACTS_PROFILES
                or self.consensus.review_status != "auto_confirmed"
            )
        ):
            raise ReviewRejected("PARTIAL_FACTS_REVIEW_REQUIRED", 409)
        if self.decision is not None and (
            self.consensus.confirmed_tags is None
            or evaluate(self.consensus.confirmed_tags, self.rule_context, self.rulepack)
            != self.decision
        ):
            raise ReviewRejected("REVIEW_DECISION_MISMATCH", 409)


def build_open_review(inputs: ReviewInputs, review_id: str | None = None) -> dict[str, Any]:
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
