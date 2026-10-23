"""Verified relation packet selection and validation, independent of the dispatch ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, cast

from proofops.application.claims import Claim
from proofops.application.evidence.retrieval import EvidencePacket
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.contracts import TaggingSettings
from proofops.application.tagging.relations import (
    OCCURRENCE_V3_PROFILE,
    relation_request,
    validate_relations,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.values import SourceRef, _source_ref_from_dict

if TYPE_CHECKING:
    from proofops_worker.live_tagging import LiveTaggingRuntime


@dataclass(frozen=True)
class RelationPacket:
    sources: tuple[SourceRef, ...]
    selected: dict[str, SourceRef]
    global_elements: dict[str, set[str]]
    rulepack: RulePackSnapshot | None
    refused: dict[str, dict[str, SourceRef | None]]
    refusals: list[dict[str, Any]]
    anchors: dict[str, Any]
    selection_args: dict[str, Any]
    envelope: dict[str, Any] | None


def build_relation_packet(
    self: LiveTaggingRuntime, claim: Claim, packet: EvidencePacket
) -> RelationPacket:
    # Read runtime attributes at their original guard/branch, not at the call site.
    data = packet.to_dict()
    expected = dict(
        tenant_id=self.auth.tenant_id,
        run_id=self.snapshot["run_id"],
        claim_id=claim.claim_id,
        document_version_id=self.graph.document_version_id,
        parse_manifest_id=self.graph.parse_manifest_id,
        source_sha256=self.graph.source_sha256,
        graph_sha256=canonical_hash(asdict(self.graph)),
        status="candidate",
    )
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("RELATION_PACKET_MISMATCH")
    if (
        claim.tenant_id,
        claim.document_version_id,
        claim.parse_manifest_id,
        claim.source_sha256,
    ) != (
        self.auth.tenant_id,
        self.graph.document_version_id,
        self.graph.parse_manifest_id,
        self.graph.source_sha256,
    ):
        raise ValueError("RELATION_CLAIM_MISMATCH")
    local = {ref.source_id for ref in claim.source_refs}
    if (
        self.snapshot.get("analysis_profile_policy", {}).get("table_cell_relations")
        == "attested-p1-p2-cells-pb2-v1"
    ):
        from proofops.application.tagging.pb2_table_evidence import structural_relation_ids

        local.update(
            structural_relation_ids(data, claim, self.graph, tenant_id=self.auth.tenant_id)
        )
    blocks = {block.source_id: block for block in self.graph.blocks}
    selected = {}
    global_elements: dict[str, set[str]] = {}
    rulepack = None
    if self.attribution_policy is not None and self.snapshot.get("rulepack"):
        from proofops.domain.rulepacks import RulePackSnapshot

        rulepack = RulePackSnapshot(**self.snapshot["rulepack"])
    refused: dict[str, dict[str, SourceRef | None]] = {}
    refusals: list[dict[str, Any]] = []
    for candidate in data["evidence_candidates"]:
        for raw in candidate["source_refs"]:
            if candidate.get("source_scope") == "global_bound":
                global_elements.setdefault(raw["source_id"], set()).update(
                    candidate.get("allowed_elements", ())
                )
            ref = _source_ref_from_dict(raw)
            if ref.source_id in local:
                continue
            source = verify_source_ref(ref, self.graph, tenant_id=self.auth.tenant_id)
            block = blocks.get(ref.source_id)
            if source.verification_state != "verified" or block is None:
                continue
            canonical = verify_source_ref(
                block.source_ref(), self.graph, tenant_id=self.auth.tenant_id
            )
            if source != canonical or source.quote != ref.quote:
                continue  # Never widen a selected substring to its parent paragraph.
            if self.attribution_policy is not None:
                from proofops.application.evidence.relation_attribution import (
                    relation_source_rejection,
                )

                reason = relation_source_rejection(
                    claim,
                    source,
                    self.graph,
                    tenant_id=self.auth.tenant_id,
                    policy=self.attribution_policy,
                    rulepack=rulepack,
                    global_elements=global_elements.get(ref.source_id, ()),
                )
                if reason is not None:
                    refused[ref.source_id] = dict(entity=None, metric=None, reporting_period=None)
                    if not any(r["source_id"] == ref.source_id for r in refusals):
                        refusals.append(
                            dict(
                                source_id=ref.source_id,
                                status="attribution_rejected",
                                state="unknown",
                                attribution_policy_sha256=canonical_hash(self.attribution_policy),
                                stable_reason=dict(category="attribution_guard", error_code=reason),
                            )
                        )
                    continue
            selected[ref.source_id] = source
    sources = tuple(selected.values())
    if not sources:
        return RelationPacket(
            sources, selected, global_elements, rulepack, refused, refusals, {}, {}, None
        )
    anchors = {}
    if cast(TaggingSettings, self.relation_settings).model_profile in (
        OCCURRENCE_V3_PROFILE,
        "relation-decision-gate-v1",
    ):
        values = [
            r["values"]["dimensions"]
            for r in self.preliminary_records.get(claim.claim_id, [])
            if r.get("status") == "validated_candidate"
        ]
        if len(values) == 3 and all(v == values[0] for v in values):
            anchors = {k: v["quote"] if v else None for k, v in values[0].items()}
    selection_args: dict[str, Any] = (
        {"claim_text": claim.quote, "dimensions": anchors}
        if cast(TaggingSettings, self.relation_settings).model_profile
        in (OCCURRENCE_V3_PROFILE, "relation-decision-gate-v1")
        else {}
    )
    if self.attribution_policy is not None:
        selection_args["attribution_guard"] = True
    envelope = relation_request(
        sources,
        self.graph,
        tenant_id=self.auth.tenant_id,
        profile=cast(TaggingSettings, self.relation_settings).model_profile,
        **selection_args,
    ) | {
        "claim_id": claim.claim_id,
        "retrieval_packet_sha256": packet.packet_sha256,
    }
    return RelationPacket(
        sources,
        selected,
        global_elements,
        rulepack,
        refused,
        refusals,
        anchors,
        selection_args,
        envelope,
    )


def validate_relation_response(
    self: LiveTaggingRuntime, raw: dict[str, Any], *, claim: Claim, plan: RelationPacket
) -> tuple[dict[str, dict[str, SourceRef | None]], dict[str, Any]]:
    sources, selection_args = plan.sources, plan.selection_args
    selected, rulepack, global_elements = plan.selected, plan.rulepack, plan.global_elements
    roles = validate_relations(
        sources,
        self.graph,
        raw,
        tenant_id=self.auth.tenant_id,
        profile=cast(TaggingSettings, self.relation_settings).model_profile,
        **selection_args,
    )
    if self.attribution_policy is not None:
        from proofops.application.evidence.relation_attribution import (
            filter_evidence_dimensions,
        )

        roles = {
            sid: filter_evidence_dimensions(
                claim,
                selected[sid],
                values,
                self.graph,
                tenant_id=self.auth.tenant_id,
                policy=self.attribution_policy,
                rulepack=rulepack,
                global_elements=global_elements.get(sid, ()),
            )[0]
            for sid, values in roles.items()
        }
    values = {
        sid: {name: asdict(ref) if ref else None for name, ref in dimensions.items()}
        for sid, dimensions in roles.items()
    }
    return roles, values
