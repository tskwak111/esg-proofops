"""Explicit local tagging stage with durable receipts and one fenced publication.

The actual parser's unverified graph stays fast_preview. Synthetic transport and
source-backed preliminary classification must be explicitly supplied; neither a
missing track nor absent runtime configuration selects a default product model.
"""

import json
import time
from dataclasses import asdict
from uuid import UUID, uuid4, uuid5

from proofops.adapters.cache.aws import ImmutableResponseCache
from proofops.adapters.local.claim_store import LocalClaimStore
from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.adapters.local.tag_cache import SQLiteImmutableCacheClient
from proofops.adapters.local.tag_store import LocalTagStore, tag_pins, tagging_settings
from proofops.application.evidence.retrieval import (
    SearchResult,
    freeze_track_packet,
    retrieve_evidence,
)
from proofops.application.ports.jobs import JobMessage, LeaseLost
from proofops.application.reviews import ReviewInputs, ReviewService
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.service import tag_replicates
from proofops.application.telemetry import TraceContext
from proofops.domain.rulepacks import RulePackSnapshot, canonical_json
from proofops.domain.rules.engine import RuleContext, evaluate

from proofops_worker.telemetry import observe_job


class _TagFenceLost(BaseException):
    """Escape tagger's provider-error boundary without fabricating a response."""


class _LocalClaimSearch:
    """Bounded synthetic local search; only retrieval's verified atomic source is used."""

    synthetic = True

    def search(self, scope, query, *, vector=None):
        return SearchResult(status="bounded")


class LocalTagRunner:
    def __init__(
        self,
        store,
        uploads,
        parser,
        *,
        telemetry,
        transport=None,
        preliminary=None,
        clock=time.time,
    ):
        if not uploads.local_synthetic:
            raise ValueError("local tagging requires local storage")
        if transport is not None and getattr(transport, "synthetic", None) is not True:
            raise ValueError("explicit synthetic transport required")
        self.store, self.uploads, self.parser = store, uploads, parser
        self.telemetry, self.transport, self.preliminary, self.clock = (
            telemetry,
            transport,
            preliminary,
            clock,
        )
        self.claims = LocalClaimStore(store, uploads, parser)
        self.tags = LocalTagStore(store, uploads, parser)
        self.cache = ImmutableResponseCache(SQLiteImmutableCacheClient(store.path))
        self.reviews = ReviewService(
            LocalSQLiteReviewStore(store.jobs), load_inputs=self.tags.load_inputs
        )

    def _execute(self, lease, snapshot, usage):
        message = lease.message
        tenant, run_id = message.tenant_id, message.run_id
        extraction, discovery, graph = self.claims.load_evidence(tenant, run_id)
        run = self.store.jobs.get_run(tenant, run_id)
        if (message.input_hash, message.document_version_id) != (
            snapshot["input_hash"],
            graph.document_version_id,
        ):
            raise ValueError("TAG_INPUT_MISMATCH")
        envelope = tag_pins(snapshot, extraction, run["claim_snapshot_sha256"])
        rulepack = RulePackSnapshot(**snapshot["rulepack"])
        settings = tagging_settings(snapshot) if snapshot.get("tagging_settings") else None
        records, publications = [], []
        for claim in discovery.claims:
            if not self.store.jobs.can_call(lease, now=int(self.clock())):
                raise LeaseLost("LEASE_LOST")
            reason = (
                "SOURCE_VALIDATION_REQUIRED"
                if claim.source_quality != "verified"
                else "TAGGING_RUNTIME_REQUIRED"
                if settings is None or self.transport is None
                else "PRELIMINARY_TAGS_REQUIRED"
                if self.preliminary is None
                else None
            )
            item = dict(
                claim_id=claim.claim_id,
                status="blocked",
                reason=reason,
                tag_runs=[],
                decision=None,
                review_inputs=None,
            )
            if reason:
                records.append(item)
                continue
            track, context, relation_tags = self.preliminary(claim, graph)
            if context.claim != claim or track.claim != claim:
                raise ValueError("PRELIMINARY_CLAIM_MISMATCH")
            original_packet = retrieve_evidence(
                claim,
                graph,
                _LocalClaimSearch(),
                tenant_id=tenant,
                run_id=run_id,
                index_generation="local-atomic-only-v1",
                rulepack=rulepack,
                document_context={},
                token_counter=self.transport.token_counter,
            )
            if original_packet.to_dict()["status"] != "candidate":
                item.update(
                    reason="EVIDENCE_PACKET_BLOCKED", original_packet=original_packet.to_dict()
                )
                records.append(item)
                continue
            packet = freeze_track_packet(original_packet, track=track, rulepack=rulepack)

            def invoke(request):
                # The budget service records actual completed usage even if the fence is
                # lost in-flight. The fenced usage wrapper below stops BEFORE reservation.
                if not self.store.jobs.can_call(lease, now=int(self.clock())):
                    raise _TagFenceLost()
                try:
                    self.store.jobs.heartbeat(lease, now=int(self.clock()), lease_seconds=300)
                except LeaseLost:
                    raise _TagFenceLost() from None
                usage["synthetic_calls"] += 1
                return self.transport.invoke(request)

            runner = self

            class FencedUsage:
                def __getattr__(self, name):
                    return getattr(runner.store.usage, name)

                def reserve_budget(self, *args, **kwargs):
                    if not runner.store.jobs.can_call(lease, now=int(runner.clock())):
                        raise LeaseLost("LEASE_LOST")
                    runner.store.jobs.heartbeat(lease, now=int(runner.clock()), lease_seconds=300)
                    return runner.store.usage.reserve_budget(*args, **kwargs)

                def mark_dispatched(self, call):
                    if not runner.store.jobs.can_call(lease, now=int(runner.clock())):
                        raise LeaseLost("LEASE_LOST")
                    return runner.store.usage.mark_dispatched(call)

            tag_runs = tag_replicates(
                packet,
                context=context,
                track=track,
                original=graph,
                relation_tags=relation_tags,
                rulepack=rulepack,
                settings=settings,
                cache=self.cache,
                usage_store=FencedUsage(),
                invoke=invoke,
                tenant_id=tenant,
                ensemble_id=str(uuid5(UUID(message.job_id), claim.claim_id)),
                consent_profile=snapshot["consent"]["consent_profile_id"],
                token_counter=self.transport.token_counter,
                now=lambda: int(self.clock()),
            )
            if not self.store.jobs.can_call(lease, now=int(self.clock())):
                raise LeaseLost("LEASE_LOST")
            consensus = form_consensus(
                tag_runs, packet=packet, rulepack=rulepack, tenant_id=tenant, tag_revision=1
            )
            rule_context = RuleContext(
                tenant,
                graph.document_version_id,
                claim.claim_id,
                packet.packet_sha256,
                mode=snapshot["mode"],
                local_synthetic=True,
            )
            decision = (
                evaluate(consensus.confirmed_tags, rule_context, rulepack)
                if consensus.confirmed_tags
                else None
            )
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
            )
            inputs.validate()
            publications.append(inputs)
            item.update(
                status="completed"
                if decision and decision.decision_status == "decided"
                else "needs_review",
                reason=None,
                tag_runs=[asdict(r) for r in tag_runs],
                decision=asdict(decision) if decision else None,
                review_inputs=inputs.snapshot(),
            )
            records.append(item)
        decided = sum(item["status"] == "completed" for item in records)
        stage_status = (
            "blocked"
            if not publications
            else "needs_review"
            if decided != len(records)
            else "completed"
        )
        envelope.update(
            claims=records,
            stage_status=stage_status,
            downstream_status="human_review",
            coverage=dict(
                extraction["coverage"],
                claims_decided=decided,
                claims_needs_review=len(records) - decided,
                complete=False,
            ),
            synthetic=True,
        )
        return canonical_json(envelope).encode(), publications

    def run_once(self, *, tenant_id: str, run_id: str) -> str:
        snapshot = self.store.snapshot(tenant_id, run_id)
        jobs = self.store.jobs
        run = jobs.get_run(tenant_id, run_id)
        if run["cancellation_requested"]:
            return "cancelled"
        for event in jobs.pending_outbox(tenant_id, run_id, now=int(self.clock())):
            message = JobMessage(**event["message"])
            if message.stage != "tag":
                continue
            lease = jobs.claim_job(
                message, owner="local-tag:" + str(uuid4()), now=int(self.clock()), lease_seconds=300
            )
            if lease is None:
                if jobs.delivery_status(message) in {"pending", "leased"}:
                    return "deferred"
                jobs.mark_outbox(
                    tenant_id,
                    run_id,
                    event["event_id"],
                    now=int(self.clock()),
                    sent=True,
                    expected_attempts=event["attempts"],
                )
                return "ignored"
            usage = {"model_calls": 0, "synthetic_calls": 0}
            publications = []

            def operation(owned):
                payload, prepared = self._execute(owned, snapshot, usage)
                publications.extend(prepared)
                return payload, usage

            try:
                payload, _ = observe_job(
                    self.telemetry,
                    lease,
                    operation,
                    context=TraceContext.new(
                        tenant_id=tenant_id, run_id=run_id, job_id=message.job_id
                    ),
                )
            except (ValueError, KeyError, TypeError, LeaseLost, _TagFenceLost):
                jobs.record_usage(lease, usage)
                try:
                    jobs.fail_job(lease, error_code="TAG_INPUT_INVALID", now=int(self.clock()))
                except LeaseLost:
                    return "discarded"
                jobs.mark_outbox(
                    tenant_id,
                    run_id,
                    event["event_id"],
                    now=int(self.clock()),
                    sent=True,
                    expected_attempts=event["attempts"],
                )
                return "failed"
            jobs.record_usage(lease, usage)

            def publish(db):
                for inputs in publications:
                    self.reviews.publish_transaction(db, inputs)
                pending = jobs._get(db, tenant_id, run_id, "outbox", event["event_id"])
                if pending["status"] != "pending" or pending["attempts"] != event["attempts"]:
                    raise ValueError("TAG_OUTBOX_FENCE_MISMATCH")
                pending.update(status="sent", attempts=pending["attempts"] + 1)
                jobs._put(db, tenant_id, run_id, "outbox", event["event_id"], pending)

            if not jobs.commit_job(lease, payload=payload, now=int(self.clock()), publish=publish):
                return "discarded"
            return json.loads(payload)["stage_status"]
        if "tag_job" in run:
            return self.tags.load_snapshot(tenant_id, run_id)["stage_status"]
        return "idle"
