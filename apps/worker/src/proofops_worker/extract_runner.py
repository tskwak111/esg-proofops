"""Explicit local extraction delivery with immutable receipts and fenced publication."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any, Protocol, cast

from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.claims import ClaimDiscovery, ExtractionProfile
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.ports.jobs import JobLease
from proofops.application.telemetry import Telemetry
from proofops.application.uploads import UploadService

from proofops_worker.extraction_parts.attempt import PaidClaimExtractor

if TYPE_CHECKING:
    from proofops_worker.tag_runner import LocalTagRunner


import json as json
import os
import time
from concurrent.futures import (
    ThreadPoolExecutor as ThreadPoolExecutor,
)
from concurrent.futures import (
    as_completed as as_completed,
)
from dataclasses import asdict as asdict
from dataclasses import replace as replace
from threading import Lock as Lock
from uuid import UUID as UUID
from uuid import uuid4 as uuid4
from uuid import uuid5 as uuid5

from proofops.adapters.local.claim_store import (
    DEFERRED_BUDGET_REASON,
    DEFERRED_KIND_REASON,
    DEFERRED_LIMIT_REASON,
    OCR_ACQUISITION_REASON_PREFIX,
    LocalClaimStore,
    _deferred_reason,
    extraction_batch_state,
    guard_extract_continuation,
)
from proofops.adapters.local.claim_store import (
    claim_scope as claim_scope,
)
from proofops.adapters.local.claim_store import (
    deferred_payload as deferred_payload,
)
from proofops.adapters.local.claim_store import (
    discovery_coverage as discovery_coverage,
)
from proofops.adapters.local.claim_store import (
    extraction_outcome as extraction_outcome,
)
from proofops.adapters.local.claim_store import (
    extraction_profile as extraction_profile,
)
from proofops.adapters.local.claim_store import (
    snapshot_pins as snapshot_pins,
)
from proofops.adapters.local.run_artifacts import load_run_graph as load_run_graph
from proofops.adapters.local.source_attestation_errors import (
    ocr_acquisition_failure_code as ocr_acquisition_failure_code,
)
from proofops.adapters.local.source_attestation_errors import (
    source_failure_code as source_failure_code,
)
from proofops.adapters.local.upstage import (
    UPSTAGE_TRANSPORT_STOP_CODES as UPSTAGE_TRANSPORT_STOP_CODES,
)
from proofops.adapters.local.verified_read_cache import (
    fresh_execution_enabled as fresh_execution_enabled,
)
from proofops.adapters.parsing.opendataloader import ParseFailure as ParseFailure
from proofops.application.claim_scope import (
    MAX_EXTRACTION_BATCH_CALLS as MAX_EXTRACTION_BATCH_CALLS,
)
from proofops.application.claim_scope import (
    validate_extraction_limits as validate_extraction_limits,
)
from proofops.application.claims import ClaimExtractorPort, ExtractionOutputError
from proofops.application.claims import (
    discover_atomic_claims as discover_atomic_claims,
)
from proofops.application.ports.jobs import JobMessage as JobMessage
from proofops.application.ports.jobs import LeaseLost as LeaseLost
from proofops.application.preflight import (
    check_local_upstage_binding as check_local_upstage_binding,
)
from proofops.application.rb1_input_isolation import InputIsolation as InputIsolation
from proofops.application.rb3_deadline import admit as _rb3_admit
from proofops.application.rb4_memory import enabled as rb4_memory_enabled
from proofops.application.telemetry import TraceContext as TraceContext
from proofops.application.uploads_security import UploadRejected as UploadRejected
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json as canonical_json
from pypdf.errors import PdfReadError as PdfReadError

from proofops_worker.consumer import (
    StageFailure as StageFailure,
)
from proofops_worker.consumer import (
    consume_job as consume_job,
)
from proofops_worker.consumer import (
    with_lease_heartbeat as with_lease_heartbeat,
)
from proofops_worker.extraction_parts.attempt import (
    ExtractionAttemptContext as ExtractionAttemptContext,
)
from proofops_worker.extraction_parts.attempt import (
    authorize_attempt as authorize_attempt,
)
from proofops_worker.extraction_parts.dispatch import (
    fence_provider_call as fence_provider_call,
)
from proofops_worker.extraction_parts.dispatch import (
    fxg_dispatch_guard as fxg_dispatch_guard,
)
from proofops_worker.extraction_parts.dispatch import (
    prefetch_packets as prefetch_packets,
)
from proofops_worker.extraction_parts.selection import (
    _is_text_candidate as _is_text_candidate,
)
from proofops_worker.extraction_parts.selection import (
    paragraph_priority as paragraph_priority,
)
from proofops_worker.extraction_parts.selection import (
    select_batch_paragraph_sources as select_batch_paragraph_sources,
)
from proofops_worker.extraction_parts.selection import (
    select_stable_paragraph_sources as select_stable_paragraph_sources,
)
from proofops_worker.telemetry import observe_job as observe_job

rb3_admit: Callable[[LocalExtractRunner, dict[str, Any], str], bool] = _rb3_admit


class PacketExtractor(Protocol):
    """Packet dispatch shared by fenced and prefetched extraction adapters."""

    def extract(self, packet: dict[str, Any]) -> dict[str, Any]: ...


def _f1_failure_origin(error: BaseException, snapshot: dict[str, Any]) -> None:
    """F1 private diagnosis without exception messages or document/credential text."""
    if not snapshot.get("analysis_profile_policy", {}).get("provider_resilience"):
        return
    trace = error.__traceback__
    if trace is None:
        return
    while trace.tb_next is not None:
        trace = trace.tb_next
    print(
        json.dumps(
            dict(
                event="f1_extraction_failure_origin",
                exception_type=type(error).__name__,
                file=os.path.basename(trace.tb_frame.f_code.co_filename),
                function=trace.tb_frame.f_code.co_name,
                line=trace.tb_lineno,
            )
        ),
        flush=True,
    )


def _candidate_extract(
    live: PacketExtractor,
    packet: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    fxg_guard: Callable[[], None] | None = None,
) -> dict[str, Any]:
    try:
        from proofops.application.ingest.fxg_wire import dispatch_scope

        with dispatch_scope(fxg_guard):
            return live.extract(packet)
    except ValueError as error:
        code = str(error)
        from proofops.application.input_failures import POLICY, TABLE_ERRORS

        policy = snapshot.get("analysis_profile_policy", {})
        acquisition_code = ocr_acquisition_failure_code(error)
        if acquisition_code and policy.get("provider_resilience"):
            text = packet.get("untrusted_document_data", {}).get("text")
            if isinstance(text, str) and text.strip():
                return deferred_payload(text, OCR_ACQUISITION_REASON_PREFIX + acquisition_code)
        if (
            policy.get("input_failure_policy") == POLICY
            and policy.get("input_failure_policy_sha256") == canonical_hash(POLICY)
            and packet.get("untrusted_document_data", {}).get("kind") == "table"
            and code in TABLE_ERRORS
        ):
            raise ExtractionOutputError("TABLE_GRID_UNREADABLE") from None
        if snapshot.get("pipeline_profile") in (
            "unattended-v1",
            "finals-unattended-v1",
            "finals-unattended-v2",
            "finals-unattended-j3-v1",
            "finals-unattended-j7-v1",
            "finals-unattended-j8-v1",
        ) and (
            code
            in {
                "OPENAI_HTTP_503",
                "OPENAI_HTTP_502",
                "OPENAI_HTTP_429",
                "OPENAI_REQUEST_FAILED",
                "UPSTAGE_REQUEST_FAILED",
                "UPSTREAM_UNAVAILABLE",
                "BUDGET_EXHAUSTED",
                "R108_FINALS_BUDGET_EXHAUSTED",
                "R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED",
            }
        ):
            raise ExtractionOutputError(code) from None
        raise


def _extractor_role_budget(snapshot: dict[str, Any]) -> int | None:
    """Return the run's frozen total call cap for the extractor role, if configured."""
    budget = snapshot.get("budget_limits")
    if not isinstance(budget, dict):
        return None
    roles = budget.get("roles")
    if isinstance(roles, list | tuple):
        for role in roles:
            if isinstance(role, dict) and role.get("role") == "extractor":
                max_calls = role.get("max_calls")
                if isinstance(max_calls, int) and max_calls >= 1:
                    return max_calls
    return None


def _live_extractor(
    extractor: ClaimExtractorPort,
    graph: CanonicalDocumentGraph,
    source: bytes | None = None,
    *,
    rb1: InputIsolation | None = None,
) -> ClaimExtractorPort:
    """Bind the run graph for a context-mode extractor; legacy passes through.

    Composition already built the context profile exactly when the frozen
    settings opted in, so the wrap decision reads the extractor itself — no
    snapshot shape change, and a context extractor can never run unbound
    (its own call would fail closed) nor silently fall back to legacy.
    """
    if not (
        getattr(extractor, "_context", False) or getattr(extractor, "_display_text_profile", None)
    ):
        return extractor
    from proofops_agent.upstage_extraction import GraphBoundExtractor, UpstageClaimExtractor

    return GraphBoundExtractor(
        cast(UpstageClaimExtractor, extractor),
        graph,
        source,
        display_prefetch_workers=int(os.environ.get("PROOFOPS_DISPLAY_PREFETCH_WORKERS", "1")),
        rb1=rb1,
    )


class _ContinuingExtractor:
    """Replay prior model receipts, call the model only inside this batch window.

    A source with a prior model receipt for this exact packet hash is answered
    from that stored payload: no call, no charge, no duplicated claim. A source in
    the window is passed to the live extractor. Everything else is answered
    locally as deferred, so it stays eligible for a later batch instead of being
    recorded as absent. The first transport stop latches: the remaining sources
    become ``extraction_budget_stop`` and the batch still publishes the calls it
    already paid for.
    """

    def __init__(
        self,
        live: PacketExtractor,
        profile: ExtractionProfile,
        prior: dict[str, dict[str, Any]],
        window: Collection[str],
        max_calls: int,
        *,
        prior_failed: dict[str, dict[str, Any]] | None = None,
        prior_calls: int = 0,
        total_budget: int | None = None,
        extraction_table_rows: bool = False,
        extraction_k3: bool = False,
        extraction_qt1: bool = False,
        graph: CanonicalDocumentGraph | None = None,
        rb1: InputIsolation | None = None,
    ) -> None:
        self.profile = profile
        self._table_rows = extraction_table_rows
        self._k3 = extraction_k3
        self._qt1 = extraction_qt1
        self._graph = graph
        self._rb1 = rb1
        self._live = live
        self._prior = prior
        self._prior_failed = prior_failed or {}
        self._window = window
        self._max_calls = max_calls
        self._prior_calls = prior_calls
        self._total_budget = total_budget
        self.calls = 0
        self.replayed: set[str] = set()
        self.processed: set[str] = set()
        self.deferred: dict[str, str] = {}
        self.stop_code: str | None = None
        self.stop_source: str | None = None

    def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
        data = packet["untrusted_document_data"]
        source_id, text = data["source_id"], data["text"]
        if self._rb1 is not None:
            self._rb1.check(source_id)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        receipt = self._prior.get(source_id)
        if receipt is not None and receipt["packet_sha256"] == canonical_hash(packet):
            self.replayed.add(source_id)
            payload: dict[str, Any] = json.loads(receipt["raw_response_json"])
            return payload
        failed_receipt = self._prior_failed.get(source_id)
        if failed_receipt is not None and failed_receipt["packet_sha256"] == canonical_hash(packet):
            self.replayed.add(source_id)
            raise ExtractionOutputError("PREVIOUS_EXTRACTION_FAILED")
        reason = None
        if not _is_text_candidate(
            data["kind"],
            text,
            extraction_table_rows=self._table_rows,
            extraction_k3=self._k3,
            extraction_qt1=self._qt1,
            graph=self._graph,
            source_id=source_id,
            rb1=self._rb1,
        ):
            reason = DEFERRED_KIND_REASON
        elif self.stop_code is not None and source_id not in getattr(self._live, "prepaid", ()):
            reason = DEFERRED_BUDGET_REASON
        elif source_id not in self._window or self.calls >= self._max_calls:
            reason = DEFERRED_LIMIT_REASON
        elif (
            self._total_budget is not None and self._prior_calls + self.calls >= self._total_budget
        ):
            self.stop_code = "BUDGET_EXHAUSTED"
            self.stop_source = source_id
            reason = DEFERRED_BUDGET_REASON
        if reason is not None:
            self.deferred[source_id] = reason
            return deferred_payload(text, reason)
        self.calls += 1
        try:
            payload = self._live.extract(packet)
        except ValueError as error:
            code = str(error)
            if code not in UPSTAGE_TRANSPORT_STOP_CODES:
                raise
            # Keep this batch's earlier, already charged results instead of
            # failing the stage; this source and the rest stay pending.
            self.stop_code, self.stop_source = code, source_id
            self.deferred[source_id] = DEFERRED_BUDGET_REASON
            return deferred_payload(text, DEFERRED_BUDGET_REASON)
        deferred = _deferred_reason(canonical_json(payload))  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        if deferred:
            self.deferred[source_id] = deferred
        else:
            self.processed.add(source_id)
        return payload


class LocalExtractRunner:
    def __init__(
        self,
        store: LocalSQLiteRunStore,
        uploads: UploadService,
        parser: OpenDataLoaderParser,
        *,
        extractor: ClaimExtractorPort,
        telemetry: Telemetry,
        clock: Callable[[], float] = time.time,
        max_workers: int = 16,
        tag_composition: Callable[[], LocalTagRunner] | None = None,
    ) -> None:
        if not uploads.local_synthetic:
            raise ValueError("local extraction requires local storage")
        if type(max_workers) is not int or not 1 <= max_workers <= 24:
            raise ValueError("EXTRACTION_CONCURRENCY_INVALID")
        self.store, self.uploads, self.parser = store, uploads, parser
        self.extractor, self.telemetry, self.clock = extractor, telemetry, clock
        self.max_workers = max_workers
        self.tag_composition = tag_composition
        self.claims = LocalClaimStore(store, uploads, parser)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.

    def _publication_payload(
        self,
        lease: JobLease,
        snapshot: dict[str, Any],
        graph: CanonicalDocumentGraph,
        profile: ExtractionProfile,
        discovery: ClaimDiscovery,
        *,
        tenant_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Assemble the extract checkpoint exactly as the single-shot stage does."""
        current = self.store.jobs.get_run(tenant_id, run_id)
        checkpoint = self.store.jobs.read_checkpoint(JobMessage(**current["parse_job"]))
        if checkpoint is None:
            raise ValueError("PARSE_NOT_PUBLISHED")
        payload: dict[str, Any] = snapshot_pins(snapshot, graph, profile, checkpoint)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        payload.update(
            discovery=asdict(discovery),
            synthetic=discovery.synthetic,
            coverage=discovery_coverage(json.loads(checkpoint)["coverage"], graph, discovery),  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
            extraction_outcome=extraction_outcome(  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
                graph,
                discovery,
                claim_pages=snapshot.get("extraction_limits", {}).get("claim_pages")
                or snapshot["selected_pages"],
                include_source_failures=snapshot.get("analysis_profile_policy", {}).get(
                    "candidate_failure_policy"
                )
                == "invalid-table-unknown-v1"
                or getattr(self.extractor, "_failure_diagnostics", False),
            ),
        )
        if "claim_source_policy" in snapshot:
            from proofops.adapters.local.claim_source_policies import (
                attest_claims,
                publication_reader,
            )
            from proofops.adapters.local.claim_source_verification import discovery_refs
            from proofops.adapters.local.run_artifacts import load_run_inputs

            reader = publication_reader(snapshot["claim_source_policy"])  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
            _, source, _ = load_run_inputs(
                self.store, self.uploads, tenant_id=tenant_id, run_id=run_id
            )
            self.store.jobs.heartbeat(lease, now=int(self.clock()), lease_seconds=300)
            payload["claim_source_attestation"] = attest_claims(  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
                reader=reader,
                graph=graph,
                source=source.content,
                refs=discovery_refs(discovery),
                tenant_id=tenant_id,
                cache=True,
                run_id=run_id,
            )
        if snapshot.get("analysis_profile_policy", {}).get("extraction_pb1") == "pb1-v1":
            from proofops.application.ingest.pb1_tables import occurrence_groups

            payload["occurrence_groups"] = occurrence_groups(discovery.claims)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        return payload

    def run_batch(
        self, *, tenant_id: str, run_id: str, max_calls: int | None = None
    ) -> dict[str, Any]:
        """Process the next bounded window of eligible sources as a new revision.

        The published revision is a new immutable extract checkpoint under its own
        job id: the previous checkpoint stays byte-identical and readable by its
        own message, while the run head advances. Sources already model-processed
        are replayed from their stored receipts, so no provider call is repeated
        and no claim is duplicated. Returns an honest per-batch summary; it never
        reports a source as absent.
        """
        snapshot = self.store.snapshot(tenant_id, run_id)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        probe = getattr(self.extractor, "_probe", None)
        if probe is not None and hasattr(probe, "configure_response_policy"):
            probe.configure_response_policy(snapshot, role="extract")
        run = self.store.jobs.get_run(tenant_id, run_id)
        if run["cancellation_requested"]:
            return dict(status="cancelled")
        if "extract_job" not in run:
            return dict(status="no_revision", detail="run the extract stage once first")
        if not rb3_admit(self, snapshot, "extract"):
            return dict(status="partial", stop_code="TIME_BUDGET")
        try:
            with self.store.jobs._transaction() as db:
                current = self.store.jobs._get(db, tenant_id, run_id, "run", "META")
                guard_extract_continuation(db, self.store.jobs, current, now=int(self.clock()))  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        except ValueError as error:
            return dict(
                status="blocked",
                detail=(
                    "active tag lease in flight; cannot continue extraction"
                    if str(error) == "TAG_LEASE_CONFLICT"
                    else "cannot continue extraction after tag/review publication; start a new run"
                ),
            )
        # Strict verification of the prior revision before any receipt is reused:
        # this replays every stored receipt against the frozen pins and graph.
        try:
            prior_envelope, _, graph = self.claims.load_evidence(  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
                tenant_id, run_id, for_extraction=True
            )
        except ValueError as error:
            if str(error) != "CLAIM_SNAPSHOT_HEAD_CHANGED":
                raise
            current = self.store.jobs.get_run(tenant_id, run_id)
            pinned_head_unchanged = all(
                current.get(key) == run.get(key)
                for key in ("extract_job", "parse_job", "claim_snapshot_sha256")
            )
            if current.get("cancellation_requested") is True and pinned_head_unchanged:
                return dict(status="cancelled")
            raise
        # Fence the original continuation head again after the potentially slow
        # receipt replay, including downstream publication/active tag leases.
        with self.store.jobs._transaction() as db:
            current = self.store.jobs._get(db, tenant_id, run_id, "run", "META")
            if any(
                current.get(key) != run.get(key)
                for key in ("extract_job", "parse_job", "claim_snapshot_sha256")
            ):
                raise ValueError("CLAIM_SNAPSHOT_HEAD_CHANGED")
            if current["cancellation_requested"]:
                return dict(status="cancelled")
            try:
                guard_extract_continuation(db, self.store.jobs, current, now=int(self.clock()))  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
            except ValueError as error:
                if str(error) not in {"TAG_LEASE_CONFLICT", "TAG_PUBLICATION_CONFLICT"}:
                    raise
                return dict(
                    status="blocked",
                    detail=(
                        "active tag lease in flight; cannot continue extraction"
                        if str(error) == "TAG_LEASE_CONFLICT"
                        else (
                            "cannot continue extraction after tag/review publication; "
                            "start a new run"
                        )
                    ),
                )
        state = extraction_batch_state(prior_envelope)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        profile = extraction_profile(snapshot)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        limits = snapshot.get("extraction_limits")
        if not profile.synthetic:
            validate_extraction_limits(limits, snapshot["selected_pages"])
            if (
                snapshot.get("extraction_mode") != "upstage_probe"
                or getattr(self.extractor, "_max_tokens", None) != limits["max_output_tokens"]
            ):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
        if profile != self.extractor.profile:
            raise ValueError("EXTRACTION_PROFILE_MISMATCH")
        frozen_calls = (limits or {}).get("max_calls", 1)
        if max_calls is not None:
            if type(max_calls) is not int or not 1 <= max_calls <= MAX_EXTRACTION_BATCH_CALLS:
                raise ValueError("EXTRACTION_INPUT_INVALID")
            if max_calls > frozen_calls:
                raise ValueError("EXTRACTION_INPUT_INVALID")
            batch_calls = max_calls
        else:
            batch_calls = frozen_calls
        total_budget = _extractor_role_budget(snapshot)
        scope = claim_scope(snapshot, graph)  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        prior_charged = len(state["model_processed"]) + len(state["failed"])
        usage_records = self.store.jobs.list_usage(tenant_id, run_id)
        charged_from_usage = sum(
            row.get("extractor_calls", 0) for row in usage_records if isinstance(row, dict)
        )
        prior_calls = max(prior_charged, charged_from_usage)
        completed = set(state["model_processed"]) | set(state["failed"])
        rb1 = InputIsolation(snapshot.get("analysis_profile_policy", {}))  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        if rb1.active:
            for excluded in prior_envelope["discovery"]["exclusions"]:
                code = excluded["reason"]
                if code.startswith("TABLE_RB1_"):
                    rb1.capture(excluded["source_id"], ValueError(code.removeprefix("TABLE_RB1_")))  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
        if rb4_memory_enabled(snapshot):  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
            # Replay and both head/fence checks above are complete. Continuation
            # needs only the source response receipts in state, not the large
            # nested source-proof tree from the previous checkpoint.
            del prior_envelope
        window = select_batch_paragraph_sources(
            graph,
            scope,
            batch_calls,
            completed=completed,
            extraction_table_rows=getattr(self.extractor, "_table_rows", False),
            extraction_k3=getattr(self.extractor, "_k3", False),
            extraction_qt1=getattr(self.extractor, "_qt1", False),
            rb1=rb1,
        )
        summary = dict(
            status="idle",
            revision_job_id=run["extract_job"]["job_id"],
            model_processed_before=len(completed),
            window=sorted(window),
            pending_before=sorted(state["pending"]),
        )
        if not window:
            return dict(summary, status="complete", pending_after=[], replayed=len(completed))
        base = JobMessage(**run["extract_job"])
        # One job per (stage, shard) is an immutable invariant of the job store, so
        # each batch revision takes its own shard. The first unused index is this
        # batch; an already published index is skipped, which makes the command
        # safe to re-run.
        message = None
        for index in range(1, 201):
            shard = f"{base.shard}-b{index}"
            candidate = replace(
                base,
                job_id=str(uuid5(UUID(base.job_id), f"extract-batch:{index}")),
                shard=shard[:128],
            )
            # Preserve existing legacy jobs; new long chains must not truncate
            # away their distinguishing suffix and collide with the prior batch.
            if len(shard) > 128 and self.store.jobs.delivery_status(candidate) == "not_found":
                candidate = replace(candidate, shard=f"extract-batch-{candidate.job_id}")
            if self.store.jobs.delivery_status(candidate) in {"not_found", "pending", "leased"}:
                message = candidate
                break
        if message is None:
            return dict(summary, status="batch_limit_reached")
        next_job = replace(message, job_id=str(uuid5(UUID(message.job_id), "tag")), stage="tag")
        if self.store.jobs.delivery_status(message) == "not_found":
            self.store.jobs.enqueue(message, now=int(self.clock()))
        usage: dict[str, Any] = {"model_calls": 0, "extractor_calls": 0}
        outcome: dict[str, Any] = {}

        def operation(lease: JobLease) -> tuple[bytes, dict[str, Any]]:
            since = (
                0
                if profile.synthetic
                else cast(PaidClaimExtractor, self.extractor).usage_checkpoint()
            )
            attempt = ExtractionAttemptContext(
                self,
                snapshot,
                usage,
                is_real=not profile.synthetic,
                since=since,
                manifest_id=graph.parse_manifest_id,
            )
            usage_lock = attempt.lock
            sync_usage = attempt.sync_usage

            runner = self
            source = (
                runner.uploads.read_original(tenant_id, graph.document_version_id)
                if getattr(runner.extractor, "_display_text_profile", None)
                else None
            )
            live_extractor = _live_extractor(runner.extractor, graph, source, rb1=rb1)
            fxg_guard = fxg_dispatch_guard(
                runner,
                lease,
                usage,
                snapshot,
                graph,
                profile,
                min(batch_calls, total_budget - prior_calls)
                if total_budget is not None
                else batch_calls,
            )

            class FencedLive:
                profile_ = profile

                def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
                    fence_provider_call(runner, lease, usage)
                    if not attempt.admit(
                        graph,
                        profile,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        admit=rb3_admit,
                        check_binding=check_local_upstage_binding,
                    ):
                        return deferred_payload(
                            packet["untrusted_document_data"]["text"], "TIME_BUDGET"
                        )
                    with usage_lock:
                        usage["extractor_calls"] += 1
                    try:
                        return _candidate_extract(
                            live_extractor, packet, snapshot, fxg_guard=fxg_guard
                        )
                    finally:
                        sync_usage()

            try:
                live = FencedLive()
                if getattr(getattr(runner.extractor, "_probe", None), "model", None) in (
                    "openai/gpt-6-luna",
                    "gpt-6-luna",
                ):
                    # The provider ledger atomically fences all in-flight reservations.
                    # Map preserves packet order when the serial discovery consumes results.
                    candidates = sorted(
                        (block for block in graph.blocks if block.source_id in window),
                        key=lambda block: (block.page_num, block.source_id),
                    )
                    remaining = max(0, (total_budget or prior_calls + batch_calls) - prior_calls)
                    packets = [
                        dict(
                            tenant_id=scope.tenant_id,
                            document_version_id=scope.document_version_id,
                            parse_manifest_id=scope.parse_manifest_id,
                            source_sha256=graph.source_sha256,
                            extraction_profile=asdict(profile),
                            untrusted_document_data=dict(
                                source_id=block.source_id,
                                page_num=block.page_num,
                                kind=block.kind,
                                text=block.normalized_text,
                            ),
                        )
                        for block in candidates[:remaining]
                    ]

                    prepare = getattr(live_extractor, "prefetch", None)
                    if prepare and not fresh_execution_enabled():  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
                        prepare(packets)
                    paid = prefetch_packets(
                        packets,
                        live.extract,
                        max_workers=self.max_workers,
                        **(dict(prepare_pages=prepare) if fresh_execution_enabled() else {}),  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
                    )
                    sync_usage()

                    class PrefetchedLive:
                        prepaid = paid.keys()

                        def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
                            answer = paid[packet["untrusted_document_data"]["source_id"]]
                            if isinstance(answer, Exception):
                                raise answer
                            return answer

                    selected_live: PacketExtractor = PrefetchedLive()
                else:
                    selected_live = live
                extractor = _ContinuingExtractor(
                    selected_live,
                    profile,
                    state["model_processed"],
                    window,
                    batch_calls,
                    prior_failed=state.get("failed_receipts", {}),
                    prior_calls=prior_calls,
                    total_budget=total_budget,
                    extraction_table_rows=getattr(runner.extractor, "_table_rows", False),
                    extraction_k3=getattr(runner.extractor, "_k3", False),
                    extraction_qt1=getattr(runner.extractor, "_qt1", False),
                    graph=graph,
                    rb1=rb1,
                )
                discovery = discover_atomic_claims(graph, scope, extractor=extractor)
                payload = self._publication_payload(
                    lease, snapshot, graph, profile, discovery, tenant_id=tenant_id, run_id=run_id
                )
                outcome.update(
                    replayed=sorted(extractor.replayed),
                    processed=sorted(extractor.processed),
                    deferred=dict(sorted(extractor.deferred.items())),
                    stop_code=extractor.stop_code,
                    stop_source=extractor.stop_source,
                    claims=len(discovery.claims),
                )
                return canonical_json(payload).encode(), usage
            except LeaseLost:
                raise StageFailure("LEASE_LOST", usage=usage) from None
            except ValueError as error:
                _f1_failure_origin(error, snapshot)
                code = str(error)
                acquisition_code = ocr_acquisition_failure_code(error)
                if acquisition_code:
                    code = "OCR_PAGE_ACQUISITION_FAILED:" + acquisition_code
                elif code not in UPSTAGE_TRANSPORT_STOP_CODES | {
                    "LOCAL_TEST_AUTHORIZATION_INVALID",
                    "ACCOUNTING_UNAVAILABLE",
                }:
                    code = "EXTRACTION_INPUT_INVALID"
                if code == "ACCOUNTING_UNAVAILABLE":
                    usage.update(model_calls=None, accounting_complete=False)
                raise StageFailure(code, usage=usage) from None
            except (KeyError, TypeError, ParseFailure, UploadRejected, PdfReadError) as error:
                _f1_failure_origin(error, snapshot)
                raise StageFailure(
                    source_failure_code(error) or "EXTRACTION_INPUT_INVALID", usage=usage
                ) from None

        result = consume_job(
            self.store.jobs,
            message,
            owner="local-extract-batch:" + str(uuid4()),
            clock=lambda: int(self.clock()),
            lease_seconds=300,
            operation=lambda lease: observe_job(
                self.telemetry,
                lease,
                lambda active_lease: with_lease_heartbeat(
                    self.store.jobs, active_lease, self.clock, operation
                ),
                context=TraceContext.new(tenant_id=tenant_id, run_id=run_id, job_id=message.job_id),
            ),
            next_job=next_job,
        )
        summary.update(status=result, usage=usage, **outcome)
        if result == "committed":
            published = extraction_batch_state(self.claims.load_evidence(tenant_id, run_id)[0])  # type: ignore[no-untyped-call]  # External package boundary; annotations owned by another workstream.
            summary.update(
                revision_job_id=message.job_id,
                model_processed_after=len(published["model_processed"]),
                pending_after=sorted(published["pending"]),
                unreadable=sorted(published["failed"]),
                excluded=len(published["excluded"]),
                budget_stopped=sorted(published["budget_stopped"]),
            )
        return summary

    def run_once(self, *, tenant_id: str, run_id: str) -> str:
        from proofops_worker.extraction_parts.single_shot import run_once

        return run_once(self, tenant_id=tenant_id, run_id=run_id)
