"""Explicit local extraction delivery with immutable receipts and fenced publication."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from proofops.adapters.local.claim_store import (
    LocalClaimStore,
    claim_scope,
    discovery_coverage,
    extraction_profile,
    snapshot_pins,
)
from proofops.adapters.local.run_artifacts import load_run_graph
from proofops.adapters.local.upstage import UPSTAGE_TRANSPORT_STOP_CODES
from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.application.authorization import AuthContext
from proofops.application.claims import ClaimExtractorPort, discover_atomic_claims
from proofops.application.ports.jobs import JobMessage, LeaseLost
from proofops.application.preflight import check_local_upstage_binding
from proofops.application.telemetry import TraceContext
from proofops.application.uploads_security import UploadRejected
from proofops.domain.rulepacks import canonical_json

from proofops_worker.consumer import StageFailure, consume_job
from proofops_worker.telemetry import observe_job


def _is_text_candidate(kind: str, text: str) -> bool:
    # ponytail: length is a routing heuristic, not a claim/absence classifier.
    return kind == "paragraph" or (kind == "heading" and len(text.strip()) >= 60)


def paragraph_priority(block):
    """Stable prose/page ordering for bounded extraction and raster recovery."""
    # ponytail: routing heuristic only; no claim or absence classification.
    return (
        not block.normalized_text.rstrip().endswith((".", "!", "?")),
        len(block.normalized_text.strip()) < 60,
        block.page_num,
        block.bbox is not None,
        tuple(block.bbox or ()),
        block.normalized_text,
    )


def select_stable_paragraph_sources(graph, scope, max_calls: int) -> set[str]:
    """Prioritize prose within a bounded preview; retain short candidates after it."""
    if type(max_calls) is not int or not 1 <= max_calls <= 20:
        raise ValueError("EXTRACTION_INPUT_INVALID")
    eligible = (
        block
        for block in graph.blocks
        if (scope.mode != "declared_subset" or block.page_num in scope.selected_pages)
        and block.quality in ("verified", "unverified")
        and block.winner is not None
        and _is_text_candidate(block.kind, block.normalized_text)
        and block.normalized_text.strip()
    )
    ordered = sorted(eligible, key=paragraph_priority)
    return {block.source_id for block in ordered[:max_calls]}


class LocalExtractRunner:
    def __init__(
        self, store, uploads, parser, *, extractor: ClaimExtractorPort, telemetry, clock=time.time
    ):
        if not uploads.local_synthetic:
            raise ValueError("local extraction requires local storage")
        self.store, self.uploads, self.parser = store, uploads, parser
        self.extractor, self.telemetry, self.clock = extractor, telemetry, clock
        self.claims = LocalClaimStore(store, uploads, parser)

    def run_once(self, *, tenant_id: str, run_id: str) -> str:
        snapshot = self.store.snapshot(tenant_id, run_id)
        run = self.store.jobs.get_run(tenant_id, run_id)
        if run["cancellation_requested"]:
            return "cancelled"
        for event in self.store.jobs.pending_outbox(tenant_id, run_id, now=int(self.clock())):
            message = JobMessage(**event["message"])
            if message.stage != "extract":
                continue
            next_job = replace(message, job_id=str(uuid5(UUID(message.job_id), "tag")), stage="tag")

            def operation(lease):
                usage = {"model_calls": 0, "extractor_calls": 0}
                is_real, since, manifest_id = False, 0, None

                def sync_usage():
                    if is_real:
                        usage.update(
                            self.extractor.cumulative_usage(
                                since=since, parse_manifest_id=manifest_id
                            )
                        )

                try:
                    profile = extraction_profile(snapshot)
                    is_real = not profile.synthetic
                    if is_real:
                        limits = snapshot.get("extraction_limits")
                        if (
                            snapshot.get("extraction_mode") != "upstage_probe"
                            or not isinstance(limits, dict)
                            or set(limits) != {"max_calls", "max_output_tokens"}
                            or type(limits["max_calls"]) is not int
                            or not 1 <= limits["max_calls"] <= 20
                            or type(limits["max_output_tokens"]) is not int
                            or not 1 <= limits["max_output_tokens"] <= 1024
                            or getattr(self.extractor, "_max_tokens", None)
                            != limits["max_output_tokens"]
                        ):
                            raise ValueError("EXTRACTION_PROFILE_MISMATCH")
                        since = self.extractor.usage_checkpoint()
                    if profile != self.extractor.profile or (
                        message.document_version_id != snapshot["document"]["version_id"]
                        or message.input_hash != snapshot["input_hash"]
                    ):
                        raise ValueError("EXTRACTION_PROFILE_MISMATCH")
                    graph = load_run_graph(
                        self.store, self.uploads, self.parser, tenant_id=tenant_id, run_id=run_id
                    )
                    runner = self
                    manifest_id = graph.parse_manifest_id
                    eligible_sources: set[str] | None = None
                    if is_real:
                        eligible_sources = select_stable_paragraph_sources(
                            graph, claim_scope(snapshot, graph), limits["max_calls"]
                        )

                    class FencedExtractor:
                        def __init__(self):
                            self.profile = profile
                            self.calls = 0

                        def extract(self, packet):
                            if not runner.store.jobs.can_call(lease, now=int(runner.clock())):
                                raise StageFailure("LEASE_LOST", usage=usage)
                            runner.store.jobs.heartbeat(
                                lease, now=int(runner.clock()), lease_seconds=300
                            )
                            if is_real:
                                data = packet["untrusted_document_data"]
                                reason = (
                                    "non_paragraph_kind"
                                    if not _is_text_candidate(data["kind"], data["text"])
                                    else "beyond_extraction_limit"
                                    if data.get("source_id") not in eligible_sources
                                    or self.calls >= limits["max_calls"]
                                    else None
                                )
                                if reason:
                                    return {
                                        "spans": [
                                            dict(
                                                char_start=0,
                                                char_end=len(data["text"]),
                                                quote=data["text"],
                                                kind="unknown",
                                                reason=reason,
                                                topic_ids=[],
                                            )
                                        ]
                                    }
                                authorization = check_local_upstage_binding(
                                    binding=snapshot["runtime"],
                                    consent=snapshot["consent"],
                                    auth=AuthContext(
                                        "local-worker", tenant_id, "viewer", frozenset(), run_id
                                    ),
                                    checked_at=datetime.fromtimestamp(
                                        runner.clock(), UTC
                                    ).isoformat(),
                                    source_sha256=graph.source_sha256,
                                    model_sha256=profile.model_sha256,
                                )
                                if not authorization.ready:
                                    raise ValueError("LOCAL_TEST_AUTHORIZATION_INVALID")
                            self.calls += 1
                            usage["extractor_calls"] += 1
                            try:
                                return runner.extractor.extract(packet)
                            finally:
                                sync_usage()

                    discovery = discover_atomic_claims(
                        graph, claim_scope(snapshot, graph), extractor=FencedExtractor()
                    )
                    current = self.store.jobs.get_run(tenant_id, run_id)
                    checkpoint = self.store.jobs.read_checkpoint(JobMessage(**current["parse_job"]))
                    if checkpoint is None:
                        raise ValueError("PARSE_NOT_PUBLISHED")
                    payload = snapshot_pins(snapshot, graph, profile, checkpoint)
                    coverage = discovery_coverage(
                        json.loads(checkpoint)["coverage"], graph, discovery
                    )
                    payload.update(
                        discovery=asdict(discovery),
                        synthetic=discovery.synthetic,
                        coverage=coverage,
                    )
                    return canonical_json(payload).encode(), usage
                except LeaseLost:
                    raise StageFailure("LEASE_LOST", usage=usage) from None
                except ValueError as error:
                    code = str(error)
                    if code not in UPSTAGE_TRANSPORT_STOP_CODES | {
                        "LOCAL_TEST_AUTHORIZATION_INVALID",
                        "ACCOUNTING_UNAVAILABLE",
                    }:
                        code = "EXTRACTION_INPUT_INVALID"
                    if code == "ACCOUNTING_UNAVAILABLE":
                        usage.update(model_calls=None, accounting_complete=False)
                    raise StageFailure(code, usage=usage) from None
                except (KeyError, TypeError, ParseFailure, UploadRejected):
                    raise StageFailure("EXTRACTION_INPUT_INVALID", usage=usage) from None

            result = consume_job(
                self.store.jobs,
                message,
                owner="local-extract:" + str(uuid4()),
                clock=lambda: int(self.clock()),
                lease_seconds=300,
                operation=lambda lease: observe_job(
                    self.telemetry,
                    lease,
                    operation,
                    context=TraceContext.new(
                        tenant_id=tenant_id, run_id=run_id, job_id=message.job_id
                    ),
                ),
                next_job=next_job,
            )
            if result in {"committed", "ignored", "failed", "retry"}:
                self.store.jobs.mark_outbox(
                    tenant_id,
                    run_id,
                    event["event_id"],
                    now=int(self.clock()),
                    sent=True,
                    expected_attempts=event["attempts"],
                )
            return result
        return "pending_downstream" if run.get("current_stage") == "tag" else "idle"
