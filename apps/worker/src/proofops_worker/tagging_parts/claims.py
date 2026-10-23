"""One claim through source, preliminary, evidence, elements and review inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid5

from proofops.adapters.local.evidence_search import (
    LocalEvidenceSearch,
    collect_raw_candidate_review,
)
from proofops.adapters.local.gri_routing import LocalGRIRouting
from proofops.application.claims import Claim
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.citations import _normalized
from proofops.application.evidence.retrieval import (
    EvidencePacket,
    EvidenceSearchPort,
    freeze_track_packet,
    unattended_packet,
)
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.ports.jobs import JobLease, LeaseLost
from proofops.application.rb1_input_isolation import InputIsolation
from proofops.application.reviews import ReviewInputs
from proofops.application.tagging.analysis_scope import InventoryIndex
from proofops.application.tagging.consensus import (
    ConsensusResult,
    reviewable_checkpoint,
)
from proofops.application.tagging.consensus import (
    reviewable_decision as _review_decision,
)
from proofops.application.tagging.contracts import TaggingSettings, TagRun
from proofops.application.tagging.report_level_link import apply_report_level_link, strict_fallback
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import (
    empty_provisional,
    provisional_result,
    source_status,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import RuleContext, evaluate
from proofops.domain.values import SourceRef

from proofops_worker.consumer import LeaseHeartbeatState
from proofops_worker.tag_recovery import TagRecovery
from proofops_worker.tag_reprocess import TagReprocess
from proofops_worker.tagging_parts.contracts import PreliminarySupplier, RelationRoles, TagTransport

if TYPE_CHECKING:
    from proofops_worker.live_tagging import LiveTaggingRuntime
    from proofops_worker.tag_runner import LocalTagRunner


def _unexpected_error_code(stage: str, error: BaseException) -> str:
    name = type(error).__name__
    if not name.isascii() or not name.isidentifier() or len(name) > 64:
        name = "Exception"
    return f"{stage.upper()}_UNEXPECTED_{name}"


def _candidate_tokens(text: str) -> int:
    """Retrieval size bound for blocked claims when no tagging runtime is wired.

    Deterministic byte length only; it never selects or contacts a model.
    """
    return len(text.encode("utf-8"))


def _consensus_review_reason(consensus: ConsensusResult) -> str:
    return (
        "PARTIAL_FACTS_REVIEW_REQUIRED"
        if "PARTIAL_FACTS_REVIEW_REQUIRED" in consensus.reasons
        else "CONSENSUS_UNRESOLVED"
    )


def _prior_claim_record(
    claim_id: str,
    prior: ReviewInputs,
    rulepack_unapproved: bool,
    *,
    pinned_profile: str | None = None,
) -> dict[str, Any]:
    decision, candidate_grade = _review_decision(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
        prior.decision, prior.fact_assembly_profile, prior.consensus.review_status
    )
    if rulepack_unapproved:
        reason = "DOMAIN_RULEPACK_UNAPPROVED"
    elif candidate_grade is not None or prior.consensus.confirmed_tags is None:
        reason = _consensus_review_reason(prior.consensus)
    elif decision and decision.decision_status != "decided":
        reason = decision.decision_status
    else:
        reason = None
    result: dict[str, Any] = reviewable_checkpoint(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
        dict(
            claim_id=claim_id,
            status=(
                "completed"
                if decision and decision.decision_status == "decided"
                else "needs_review"
            ),
            reason=reason,
            tag_runs=[asdict(result) for result in prior.tag_runs],
            decision=asdict(decision) if decision else None,
            candidate_grade=candidate_grade,
            review_inputs=prior.snapshot(),
        ),
        pinned_profile=pinned_profile,
    )
    return result


def _source_traceable(claim: Claim, graph: CanonicalDocumentGraph) -> bool:
    """Does every claim ref still point at the pinned parsed text of its block?

    This is the precondition for letting a blocked claim reach local candidate
    retrieval, not a verification: source-quality attestation is exactly the gate
    such a claim is waiting on, so quality is deliberately not required here.
    A ref whose page, label, box, raw-text digest, offsets or literal quote
    disagrees with the winner candidate is not a traceable source, so its
    untrusted text never reaches search, GRI routing, a packet or any model.
    Verification (verify_source_ref) still decides everything downstream.
    """
    blocks = {block.source_id: block for block in graph.blocks}
    pinned = (
        "document_version_id",
        "parse_manifest_id",
        "page_num",
        "printed_page_label",
        "bbox",
        "raw_text_sha256",
    )
    for ref in claim.source_refs:
        block = blocks.get(ref.source_id)
        if block is None or block.winner is None or ref.location_quality != "located":
            return False
        canonical = block.source_ref()
        if (
            any(getattr(ref, name) != getattr(canonical, name) for name in pinned)
            or not 0 <= ref.char_start < ref.char_end <= len(block.raw_text)
            or _normalized(ref.quote) != _normalized(block.raw_text[ref.char_start : ref.char_end])
        ):
            return False
    return bool(claim.source_refs)


def _atomic_v3_binding_enabled(snapshot: dict[str, Any], claim: Claim) -> bool:
    """Use the narrow source-edge rule only for the frozen atomic-v3 prompt."""
    profile = snapshot.get("extraction_profile")
    if not isinstance(profile, dict) or profile != asdict(claim.receipt.profile):
        return False
    from proofops_agent.upstage_extraction import ATOMIC_V3_SYSTEM_PROMPT

    return (
        profile.get("prompt_sha256") == canonical_hash(ATOMIC_V3_SYSTEM_PROMPT)
        or snapshot.get("analysis_profile_policy", {}).get("extraction_candidate_profile")
        == "extraction-atomic-v3"
    )


@dataclass(frozen=True)
class ClaimProcessingContext:
    """Run-scoped inputs shared by claims; scheduling and publication stay in the runner."""

    runner: LocalTagRunner
    heartbeat_state: LeaseHeartbeatState | None
    lease: JobLease
    run: dict[str, Any]
    recovery: TagRecovery | None
    reprocess: TagReprocess | None
    snapshot: dict[str, Any]
    raw_search: LocalEvidenceSearch | None
    graph: CanonicalDocumentGraph
    unattended: bool
    settings: TaggingSettings | None
    transport: TagTransport | None
    preliminary_supplier: PreliminarySupplier | None
    progress: dict[str, dict[str, Any]]
    report_stage: Callable[[Claim, str], None]
    live: LiveTaggingRuntime | None
    rulepack: RulePackSnapshot
    gri: LocalGRIRouting | None
    search: EvidenceSearchPort
    generation: str
    sc1_index: InventoryIndex | None
    facility_candidates: str | None
    facility_dimensions: dict[str, Any]
    semantic_policy: dict[str, Any] | None
    parallel_claims: bool
    sc1_policy: dict[str, Any] | None
    hold_profile: str | None
    deferred: list[ReviewInputs] | None
    report_source_lock: Lock
    report_source_cache: dict[tuple[SourceRef, ...], tuple[CanonicalDocumentGraph, dict[str, Any]]]
    usage: dict[str, Any]
    tag_replicates: Callable[..., tuple[TagRun, ...]]
    retrieve_evidence: Callable[..., EvidencePacket]
    form_consensus: Callable[..., ConsensusResult]
    rb1: InputIsolation


def process_claim(execution: ClaimProcessingContext, claim: Claim) -> dict[str, Any]:
    self = execution.runner
    message = execution.lease.message
    tenant, run_id = message.tenant_id, message.run_id
    heartbeat_state = execution.heartbeat_state
    lease = execution.lease
    run = execution.run
    recovery = execution.recovery
    reprocess = execution.reprocess
    snapshot = execution.snapshot
    raw_search = execution.raw_search
    graph = execution.graph
    unattended = execution.unattended
    settings = execution.settings
    transport = execution.transport
    preliminary_supplier = execution.preliminary_supplier
    progress = execution.progress
    report_stage = execution.report_stage
    live = execution.live
    rulepack = execution.rulepack
    gri = execution.gri
    search = execution.search
    generation = execution.generation
    sc1_index = execution.sc1_index
    facility_candidates = execution.facility_candidates
    facility_dimensions = execution.facility_dimensions
    semantic_policy = execution.semantic_policy
    parallel_claims = execution.parallel_claims
    sc1_policy = execution.sc1_policy
    hold_profile = execution.hold_profile
    deferred = execution.deferred
    report_source_lock = execution.report_source_lock
    report_source_cache = execution.report_source_cache
    usage = execution.usage
    tag_replicates = execution.tag_replicates
    retrieve_evidence = execution.retrieve_evidence
    form_consensus = execution.form_consensus

    records = []
    # Keep the existing per-claim exits while mapping claims in source order.
    for claim in (claim,):
        if heartbeat_state is not None:
            heartbeat_state.check()
        if not self.store.jobs.can_call(lease, now=int(self.clock())):
            raise LeaseLost("LEASE_LOST")
        if "tag_job" not in run and recovery is None and reprocess is None:
            with self.store.jobs._transaction() as db:
                prior_revision = self.store.jobs._raw(
                    db,
                    tenant,
                    run_id,
                    "tag_revision",
                    f"{claim.claim_id}:{1:010}",
                )
            if prior_revision is not None:
                prior = self.tags.load_inputs(tenant, run_id, claim.claim_id)  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                records.append(
                    _prior_claim_record(
                        claim.claim_id,
                        prior,
                        snapshot.get("rulepack_use") == "candidate_tagging_reference_only",
                        pinned_profile=snapshot.get("fact_assembly_profile", "strict-v1"),
                    )
                )
                continue
        # An explicit recovery attempts only its bounded authorized claims and
        # carries every other claim forward exactly as the paid stage committed
        # it: no reprocessing, no new call and no second publication of an
        # already immutable revision. A claim is also carried forward, untouched,
        # once the remaining bound can no longer finish it, so the stage never
        # publishes a half-tagged claim that could then never be retried.
        if recovery is not None and (
            claim.claim_id not in recovery.claim_ids or not recovery.can_attempt_claim()
        ):
            records.append(
                reviewable_checkpoint(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                    recovery.carry_forward(claim.claim_id),
                    pinned_profile=snapshot.get("fact_assembly_profile", "strict-v1"),
                )
            )
            continue
        # A manual-classification reprocess attempts exactly its one authorized
        # claim and carries every other committed claim forward verbatim: no
        # reprocessing, no new call and no second publication of an already
        # immutable revision. The target claim is also carried forward untouched
        # once the bound can no longer finish it, so the stage never publishes a
        # half-tagged claim.
        if reprocess is not None and (
            claim.claim_id not in reprocess.claim_ids or not reprocess.can_attempt_claim()
        ):
            records.append(
                reviewable_checkpoint(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                    reprocess.carry_forward(claim.claim_id),
                    pinned_profile=snapshot.get("fact_assembly_profile", "strict-v1"),
                )
            )
            continue
        raw_candidate_review = None
        if raw_search is not None and _source_traceable(claim, graph):
            raw_candidate_review = collect_raw_candidate_review(raw_search, claim.quote)
        reason = (
            "SOURCE_VALIDATION_REQUIRED"
            if claim.source_quality != "verified" and not unattended
            else "TAGGING_RUNTIME_REQUIRED"
            if settings is None or transport is None
            else "PRELIMINARY_TAGS_REQUIRED"
            if preliminary_supplier is None
            else None
        )
        item: dict[str, Any] = dict(
            claim_id=claim.claim_id,
            status="blocked",
            reason=reason,
            tag_runs=[],
            decision=None,
            review_inputs=None,
            raw_candidate_review=raw_candidate_review,
        )
        if unattended:
            item.update(
                source_status=source_status(claim),  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                provisional_grade=empty_provisional(reason),  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                stage="preliminary",
            )
            progress[claim.claim_id] = item
            if not _source_traceable(claim, graph):
                item.update(reason="SOURCE_LOCATION_REQUIRED", status="failed")
                return item
        track: TrackCandidate | None = None
        context: ClaimContext | None = None
        relation_tags: RelationRoles | None = None
        # Paid preliminary replicas stay behind the source-quality gate; an
        # unverified source never buys model calls to make progress.
        if reason is None:
            if reprocess is not None and claim.claim_id in reprocess.claim_ids:
                # A manual-classification reprocess supplies the reviewer's
                # recorded, source-verified classification instead of a model
                # preliminary call. The element stage below still runs its real
                # replicas under the pinned run mode, so no grade is invented and
                # no model vote is fabricated. The prior preliminary_records /
                # preliminary_agreement of the blocked stage are preserved on the
                # carried record for every other claim; this target claim records
                # the distinct reviewed classification instead.
                from proofops.application.evidence.binding import local_relation_tags
                from proofops.application.tagging.manual_classification import (
                    ClassificationRejected,
                    classification_override,
                )

                try:
                    classified = classification_override(
                        reprocess.classification, claim, graph, tenant_id=tenant
                    )
                except ClassificationRejected as error:
                    raise ValueError("REPROCESS_CLASSIFICATION_INVALID") from error
                track, context = classified.track, classified.context
                relation_tags = local_relation_tags(context)
                # Preserve the prior blocked stage's original preliminary provenance
                # for this claim; the reviewed classification is additive, never a
                # replacement of what the model replicas actually recorded.
                prior_record = reprocess.carry_forward(claim.claim_id)
                if "preliminary_records" in prior_record:
                    item["preliminary_records"] = prior_record["preliminary_records"]
                if "preliminary_agreement" in prior_record:
                    item["preliminary_agreement"] = prior_record["preliminary_agreement"]
                item["reviewed_classification"] = dict(
                    classification_id=reprocess.plan.classification_id,
                    classification_sha256=reprocess.plan.classification_sha256,
                    origin=reprocess.classification.get("origin"),
                    classified_by=reprocess.classification.get("classified_by"),
                    review_origin=reprocess.classification.get("review_origin"),
                    track=track.track,
                    safe_harbor_category=classified.safe_harbor_category,
                )
                if context.claim != claim or track.claim != claim:
                    raise ValueError("PRELIMINARY_CLAIM_MISMATCH")
            else:
                preliminary = cast(PreliminarySupplier, preliminary_supplier)(claim, graph)
                report_stage(claim, "preliminary")
                if live is not None:
                    item["preliminary_records"] = live.preliminary_records.get(claim.claim_id, [])
                    item["preliminary_agreement"] = live.preliminary_agreement(claim.claim_id)
                track, context, relation_tags = (
                    (None, None, None) if preliminary is None else preliminary
                )
                if track is None:
                    reason = "PRELIMINARY_TAGS_UNRESOLVED"
                elif cast(ClaimContext, context).claim != claim or track.claim != claim:
                    raise ValueError("PRELIMINARY_CLAIM_MISMATCH")
        # Local, no-model candidate retrieval runs before the source and
        # consensus stops, so a blocked claim still reaches review with its
        # traceable candidates and the recorded reasons instead of nothing.
        # Identity, raw text and tenant mismatches still raise from here. A
        # blocked claim is skipped when its refs no longer point at the pinned
        # parsed text, or when this run has no approved element catalog to
        # scope candidates with; no catalog and no location is ever invented,
        # and a claim that must be tagged still fails here exactly as before.
        original_packet = None
        skipped = None
        if reason is None:
            pass
        elif not _source_traceable(claim, graph):
            skipped = "SOURCE_LOCATION_REQUIRED"
        elif "rubric/elements.yaml" not in rulepack.files:
            skipped = "RULEPACK_CATALOG_REQUIRED"
        if skipped is None:
            gri_entries, indicator_codes = gri.for_claim(claim.quote) if gri else ((), ())
            original_packet = retrieve_evidence(
                claim,
                graph,
                search,
                tenant_id=tenant,
                run_id=run_id,
                index_generation=generation,
                rulepack=rulepack,
                document_context={},
                token_counter=transport.token_counter if transport else _candidate_tokens,
                gri_entries=gri_entries,
                indicator_codes=indicator_codes,
            )
        if reason:
            # An unverified source keeps blocked_evidence here, so the track
            # packet gate below can never accept it either.
            item.update(
                reason=reason,
                **(
                    dict(candidate_retrieval=skipped)
                    if skipped is not None
                    else dict(original_packet=cast(EvidencePacket, original_packet).to_dict())
                ),
            )
            records.append(item)
            continue
        # The preceding reason/skip exits establish all tagging prerequisites.
        original_packet = cast(EvidencePacket, original_packet)
        track = cast(TrackCandidate, track)
        context = cast(ClaimContext, context)
        relation_tags = cast(RelationRoles, relation_tags)
        transport = cast(TagTransport, transport)
        settings = cast(TaggingSettings, settings)
        if unattended:
            item["original_packet"] = original_packet.to_dict()
            original_packet = unattended_packet(
                original_packet, profile=snapshot["pipeline_profile"]
            )
            item["stage"] = "relation"
        if original_packet.to_dict()["status"] != "candidate":
            item.update(reason="EVIDENCE_PACKET_BLOCKED", original_packet=original_packet.to_dict())
            records.append(item)
            continue
        if sc1_index is not None and snapshot.get("analysis_profile_policy", {}).get(
            "qt2_contextual_elements_policy"
        ):
            from proofops.application.tagging.qt2_inventory import link_inventory

            item["qt2_inventory_links"] = link_inventory(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                context,
                sc1_index,
                graph,
                run_id=run_id,
                tenant_id=tenant,
                rulepack=rulepack,
            )
        packet = freeze_track_packet(original_packet, track=track, rulepack=rulepack)
        if facility_candidates:
            from proofops.application.tagging.k6_facilities import augment_packet

            packet = augment_packet(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                packet, facility_dimensions.get(claim.claim_id, {}), graph, tenant_id=tenant
            )
        cf6_policy = snapshot.get("analysis_profile_policy", {}).get("cf6_confirmation")
        if cf6_policy is not None:
            from proofops.application.evidence.retrieval import freeze_packet

            packet = freeze_packet(
                {k: v for k, v in packet.to_dict().items() if k != "packet_sha256"}
                | dict(
                    cf6_confirmation=cf6_policy,
                    cf6_selected_pages=sorted(
                        set(snapshot.get("selected_pages") or ())
                        or {block.page_num for block in graph.blocks}
                    ),
                    cf6_analysis_policy_sha256=canonical_hash(snapshot["analysis_profile_policy"]),
                )
            )
        if live is not None:
            packet = live.display_packet(packet, claim=claim)
            if snapshot.get("analysis_profile_policy", {}).get("qt1_baseline_policy"):
                from proofops.application.evidence.retrieval import freeze_packet
                from proofops.application.tagging.qt1_baseline import (
                    POLICY,
                    baseline_links,
                )
                from proofops.application.tagging.qt1_baseline import (
                    augment_packet as augment_baseline_packet,
                )

                if snapshot["analysis_profile_policy"]["qt1_baseline_policy"] != POLICY:
                    raise ValueError("QT1_BASELINE_POLICY_MISMATCH")
                if sc1_index is not None and track.track == "goal":
                    receipt = baseline_links(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                        context, sc1_index, graph, run_id=run_id, tenant_id=tenant
                    )
                    data = packet.to_dict()
                    data.pop("packet_sha256")
                    data = augment_baseline_packet(data, receipt)  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                    if live.display_catalog is not None:
                        data["display_text"] = live.display_catalog.element_pins(data)  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                    packet = freeze_packet(data)
                    item["qt1_baseline_receipt"] = receipt
            live.allow_packet(claim.claim_id, packet.packet_sha256)
            if snapshot.get("relation_settings") is not None:
                external_roles = live.relations(claim, packet)
                item["relation_records"] = live.relation_records.get(claim.claim_id, [])
                if external_roles is None and unattended:
                    item["relation_reason"] = "RELATION_TAGS_UNRESOLVED"
                    external_roles = {}
                if external_roles is None:
                    item.update(
                        reason="RELATION_TAGS_UNRESOLVED",
                        original_packet=original_packet.to_dict(),
                    )
                    records.append(item)
                    continue
                # Atomic scoped roles keep precedence over any whole-source map.
                relation_tags = {**external_roles, **relation_tags}

        invoke, fenced_usage = self._claim_calls(lease, usage, transport, live, heartbeat_state)

        report_stage(claim, "relation")
        if unattended:
            item["stage"] = "elements"
        tag_runs = tag_replicates(
            packet,
            context=context,
            track=track,
            original=graph,
            relation_tags=relation_tags,
            rulepack=rulepack,
            settings=settings,
            cache=self.cache,
            usage_store=fenced_usage,
            invoke=invoke,
            tenant_id=tenant,
            ensemble_id=str(uuid5(UUID(message.job_id), claim.claim_id)),
            consent_profile=snapshot["consent"]["consent_profile_id"],
            token_counter=transport.token_counter,
            count_input_tokens=live.count_input_tokens if live is not None else None,
            now=lambda: int(self.clock()),
            pipeline_profile=snapshot.get("pipeline_profile"),
            semantic_policy=semantic_policy,
            qt1_baseline_inventory=sc1_index,
            allow_edge_whitespace=_atomic_v3_binding_enabled(snapshot, claim),
            max_workers=(
                1
                if parallel_claims
                else self.max_workers
                if live is not None
                and settings.model_id in ("openai/gpt-6-luna", "gpt-6-luna")
                and settings.wire_policy_version == 2
                else 1
            ),
        )
        report_stage(claim, "elements")
        if live is not None:
            for tag_run in tag_runs:
                live.account(tag_run.request.request_id)
        if heartbeat_state is not None:
            heartbeat_state.check()
        if not self.store.jobs.can_call(lease, now=int(self.clock())):
            raise LeaseLost("LEASE_LOST")
        if unattended:
            if sc1_policy is not None:
                item["sc1_dimensions"] = {
                    k: asdict(v) if v else None for k, v in context.dimensions.items()
                }
            rule_context = RuleContext(
                tenant,
                graph.document_version_id,
                claim.claim_id,
                packet.packet_sha256,
                mode=snapshot["mode"],
                local_synthetic=live is None,
            )
            item.update(
                tag_runs=[asdict(r) for r in tag_runs],
                frozen_packet=packet.to_dict(),
                stage="grade",
            )
            item.update(
                status="processed",
                stage="grade",
                provisional_grade=provisional_result(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                    tag_runs,
                    packet,
                    rulepack,
                    rule_context,
                    profile="k2-v1" if hold_profile == "v3-dec92-v1" else hold_profile,
                    semantic_policy=semantic_policy,
                    original=graph,
                    range_profile=snapshot.get("pipeline_profile")
                    in (
                        "finals-unattended-v1",
                        "finals-unattended-v2",
                        "finals-unattended-j3-v1",
                        "finals-unattended-j7-v1",
                        "finals-unattended-j8-v1",
                    ),
                ),
                reason=None,
            )
            return item
        consensus = form_consensus(
            tag_runs,
            packet=packet,
            rulepack=rulepack,
            tenant_id=tenant,
            tag_revision=1,
            profile=snapshot.get("fact_assembly_profile", "strict-v1"),
        )
        rule_context = RuleContext(
            tenant,
            graph.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            mode=snapshot["mode"],
            local_synthetic=live is None,
        )
        link_config = snapshot.get("report_level_link")
        link_receipts = ()
        if link_config is not None:

            def attest_report_sources(
                refs: tuple[SourceRef, ...],
            ) -> tuple[CanonicalDocumentGraph, dict[str, Any]]:
                with report_source_lock:
                    if refs not in report_source_cache:
                        report_source_cache[refs] = self.tags.verify_context_sources(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                            base_inputs,
                            refs,
                            pinned_run_snapshot=snapshot,
                        )
                    return report_source_cache[refs]

            base_inputs = ReviewInputs(
                run_id,
                context,
                graph,
                rulepack,
                rule_context,
                packet,
                original_packet,
                tag_runs,
                consensus,
                relation_tags,
                fact_assembly_profile=snapshot.get("fact_assembly_profile", "strict-v1"),
            )
            consensus, link_receipts = apply_report_level_link(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                consensus,
                config=link_config,
                context=context,
                graph=graph,
                fallback_tags=strict_fallback(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
                    tag_runs,
                    packet,
                    rulepack,
                    tenant,
                    1,
                    snapshot.get("fact_assembly_profile", "strict-v1"),
                ),
                attest=attest_report_sources,
            )
        rulepack_unapproved = snapshot.get("rulepack_use") == "candidate_tagging_reference_only"
        decision = (
            evaluate(consensus.confirmed_tags, rule_context, rulepack)
            if consensus.confirmed_tags and not rulepack_unapproved
            else None
        )
        decision, candidate_grade = _review_decision(  # type: ignore[no-untyped-call]  # External API is not annotated yet.
            decision,
            snapshot.get("fact_assembly_profile", "strict-v1"),
            consensus.review_status,
        )
        # Explicit needs_review diagnostic: never collapse the "why" to None.
        # Domain approval gate outranks consensus, which outranks rule holds.
        if rulepack_unapproved:
            review_reason = "DOMAIN_RULEPACK_UNAPPROVED"
        elif candidate_grade is not None or not consensus.confirmed_tags:
            review_reason = _consensus_review_reason(consensus)
        elif decision and decision.decision_status != "decided":
            review_reason = decision.decision_status
        else:
            review_reason = None
        inputs = ReviewInputs(
            run_id,
            context,
            graph,
            rulepack,
            rule_context,
            packet,
            original_packet,
            tag_runs,
            consensus,
            relation_tags,
            decision=decision,
            fact_assembly_profile=snapshot.get("fact_assembly_profile", "strict-v1"),
            report_level_link=link_config,
            report_level_review=link_receipts,
        )
        if reprocess is not None:
            # A reprocess target is published only inside the fenced checkpoint
            # transaction, after its authorized lineage is rechecked, so a lineage
            # change during tagging can never leave a revision behind.
            inputs.validate()
            cast(list[ReviewInputs], deferred).append(inputs)
        else:
            self._publish_claim(lease, inputs, heartbeat_state)
        item.update(
            status="completed"
            if decision and decision.decision_status == "decided"
            else "needs_review",
            reason=review_reason,
            tag_runs=[asdict(r) for r in tag_runs],
            decision=asdict(decision) if decision else None,
            candidate_grade=candidate_grade,
            review_inputs=inputs.snapshot(),
        )
        records.append(item)
    return records[0]
