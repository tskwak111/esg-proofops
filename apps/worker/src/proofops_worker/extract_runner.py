"""Explicit local extraction delivery with immutable receipts and fenced publication."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID, uuid4, uuid5

from proofops.adapters.local.claim_store import (
    DEFERRED_BUDGET_REASON,
    DEFERRED_KIND_REASON,
    DEFERRED_LIMIT_REASON,
    OCR_ACQUISITION_REASON_PREFIX,
    LocalClaimStore,
    _deferred_reason,
    claim_scope,
    deferred_payload,
    discovery_coverage,
    extraction_batch_state,
    extraction_outcome,
    extraction_profile,
    guard_extract_continuation,
    snapshot_pins,
)
from proofops.adapters.local.run_artifacts import load_run_graph
from proofops.adapters.local.source_attestation_errors import (
    ocr_acquisition_failure_code,
    source_failure_code,
)
from proofops.adapters.local.upstage import UPSTAGE_TRANSPORT_STOP_CODES
from proofops.adapters.local.verified_read_cache import fresh_execution_enabled
from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.application.authorization import AuthContext
from proofops.application.claim_scope import MAX_EXTRACTION_BATCH_CALLS, validate_extraction_limits
from proofops.application.claims import (
    ClaimExtractorPort,
    ExtractionOutputError,
    discover_atomic_claims,
)
from proofops.application.ports.jobs import JobMessage, LeaseLost
from proofops.application.preflight import check_local_upstage_binding
from proofops.application.rb1_input_isolation import InputIsolation
from proofops.application.rb3_deadline import admit as rb3_admit
from proofops.application.rb4_memory import enabled as rb4_memory_enabled
from proofops.application.telemetry import TraceContext
from proofops.application.uploads_security import UploadRejected
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from pypdf.errors import PdfReadError

from proofops_worker.consumer import StageFailure, consume_job, with_lease_heartbeat
from proofops_worker.telemetry import observe_job


def _f1_failure_origin(error, snapshot):
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


def _candidate_extract(live, packet, snapshot, *, fxg_guard=None):
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


def _is_text_candidate(
    kind: str,
    text: str,
    *,
    extraction_table_rows=False,
    extraction_k3=False,
    extraction_qt1=False,
    graph=None,
    source_id=None,
    cells=None,
    rb1=None,
) -> bool:
    if rb1 is not None and rb1.active:
        try:
            # Validate before I26's legacy routing fallback can consume the error.
            # This replaces, rather than repeats, QT1 selection for the RB1 pin.
            if extraction_qt1 and kind == "table" and graph is not None:
                from proofops.application.ingest.qt1_tables import candidates_for

                table = next((b for b in graph.blocks if b.source_id == source_id), None)
                if table is not None and candidates_for(table, graph):
                    return True
            return _is_text_candidate(
                kind,
                text,
                extraction_table_rows=extraction_table_rows,
                extraction_k3=extraction_k3,
                extraction_qt1=False,
                graph=graph,
                source_id=source_id,
                cells=cells,
            )
        except ValueError as error:
            if not rb1.capture(source_id, error):
                raise
            return False
    if extraction_qt1 and kind == "table" and graph is not None:
        from proofops.application.ingest.qt1_tables import candidates_for

        table = next((b for b in graph.blocks if b.source_id == source_id), None)
        if table is not None:
            try:
                if candidates_for(table, graph):
                    return True
            except ValueError as error:
                from proofops.application.input_failures import TABLE_ERRORS

                if str(error) not in TABLE_ERRORS:
                    raise
                # Routing is not source admission. Let the extractor's pinned
                # table-failure policy retain this source as unknown; it still
                # rejects a missing grid before any paid model dispatch.
                return True
    if extraction_k3 and extraction_table_rows and kind == "table" and graph is not None:
        from proofops.application.ingest.w9_tables import cell_entries, graph_cells, observations

        table = next((b for b in graph.blocks if b.source_id == source_id), None)
        if table is not None and table.kind == kind and table.normalized_text == text:
            owned = graph_cells(table, graph) if cells is None else cells
            if observations(text, cells=owned) or cell_entries(text, owned, source_id=source_id):
                return True
    # ponytail: length is a routing heuristic, not a claim/absence classifier.
    if extraction_table_rows and kind in ("table", "table_row", "table_cell", "figure"):
        from proofops.application.ingest.table_row_candidates import row_candidates

        return bool(row_candidates(text, kind=kind))
    return kind == "paragraph" or (kind == "heading" and len(text.strip()) >= 60)


def fence_provider_call(runner, lease, usage):
    """One atomic owner/cancellation check plus renewal for the PA2 policy.

    heartbeat uses the same _owned guard as can_call, inside its own writer
    transaction. Cost reservations and settlement still happen per attempt.
    """
    if not fresh_execution_enabled() and not runner.store.jobs.can_call(
        lease, now=int(runner.clock())
    ):
        raise StageFailure("LEASE_LOST", usage=usage)
    try:
        runner.store.jobs.heartbeat(lease, now=int(runner.clock()), lease_seconds=300)
    except LeaseLost:
        raise StageFailure("LEASE_LOST", usage=usage) from None


def fxg_dispatch_guard(runner, lease, usage, snapshot, graph, profile, limit):
    """Additional FXG requests retain the original per-attempt authority and caps."""
    if not getattr(runner.extractor, "_fxg_split", False):
        return None
    remaining, lock = limit, Lock()

    def guard():
        nonlocal remaining
        with lock:
            if remaining <= 0:
                raise ValueError("BUDGET_EXHAUSTED")
            fence_provider_call(runner, lease, usage)
            authorization = check_local_upstage_binding(
                binding=snapshot["runtime"],
                consent=snapshot["consent"],
                auth=AuthContext(
                    "local-worker", graph.tenant_id, "viewer", frozenset(), snapshot["run_id"]
                ),
                checked_at=datetime.fromtimestamp(runner.clock(), UTC).isoformat(),
                source_sha256=graph.source_sha256,
                model_sha256=profile.model_sha256,
            )
            if not authorization.ready:
                raise ValueError("LOCAL_TEST_AUTHORIZATION_INVALID")
            remaining -= 1

    return guard


def prefetch_packets(packets, invoke, *, max_workers=16, on_page=None, prepare_pages=None):
    """Run paid packets concurrently; replay their outcomes in source order."""

    def settle(packet):
        try:
            return invoke(packet)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        if prepare_pages is not None:
            pages = {}
            for packet in packets:
                pages.setdefault(packet["untrusted_document_data"]["page_num"], []).append(packet)
            # Start a prepared page's calls while the next page's CPU preparation
            # proceeds. Discovery still consumes source order, and v2 tagging
            # still waits for the complete, source-attested extraction snapshot.
            pending = {}
            groups = list(pages.values())
            # Read the first page, then prepare the remaining pages together so
            # the existing process pool starts at most twice per batch.
            groups = groups[:1] + (
                [[packet for page in groups[1:] for packet in page]] if len(groups) > 1 else []
            )
            for page_packets in groups:
                prepare_pages(page_packets)
                for packet in page_packets:
                    pending[pool.submit(settle, packet)] = packet
            if on_page is None:
                paid = {
                    packet["untrusted_document_data"]["source_id"]: future.result()
                    for future, packet in pending.items()
                }
                return {
                    p["untrusted_document_data"]["source_id"]: paid[
                        p["untrusted_document_data"]["source_id"]
                    ]
                    for p in packets
                }
        else:
            pending = None
        if on_page is None:
            return dict(
                zip(
                    (p["untrusted_document_data"]["source_id"] for p in packets),
                    pool.map(settle, packets),
                    strict=True,
                )
            )
        if pending is None:
            pending = {pool.submit(settle, packet): packet for packet in packets}
        by_page, paid, counts = {}, {}, {}
        for packet in packets:
            page = packet["untrusted_document_data"]["page_num"]
            counts[page] = counts.get(page, 0) + 1
        for future in as_completed(pending):
            data = pending[future]["untrusted_document_data"]
            page, sid = data["page_num"], data["source_id"]
            paid[sid] = future.result()
            by_page.setdefault(page, {})[sid] = paid[sid]
            if len(by_page[page]) == counts[page]:
                on_page(page, by_page[page])
        return paid


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


def select_batch_paragraph_sources(
    graph,
    scope,
    max_calls: int,
    *,
    completed=frozenset(),
    extraction_table_rows=False,
    extraction_k3=False,
    extraction_qt1=False,
    rb1=None,
) -> set[str]:
    """Next bounded window of eligible prose sources, skipping completed ones.

    The ordering is exactly ``paragraph_priority``; continuation excludes sources
    a previous batch already model-processed. ``completed`` carries
    exact source identifiers, so a source is never processed twice and a source
    that was merely deferred stays eligible.
    """
    if type(max_calls) is not int or not 1 <= max_calls <= MAX_EXTRACTION_BATCH_CALLS:
        raise ValueError("EXTRACTION_INPUT_INVALID")
    from proofops.application.ingest.source_continuations import continuations

    fragments = {p.source_id for parts in continuations(graph).values() for p in parts}
    eligible = (
        block
        for block in graph.blocks
        if (scope.mode != "declared_subset" or block.page_num in scope.selected_pages)
        and block.quality in ("verified", "unverified")
        and block.winner is not None
        and _is_text_candidate(
            block.kind,
            block.normalized_text,
            extraction_table_rows=extraction_table_rows,
            extraction_k3=extraction_k3,
            extraction_qt1=extraction_qt1,
            graph=graph,
            source_id=block.source_id,
            rb1=rb1,
        )
        and block.normalized_text.strip()
        and block.source_id not in completed
        and block.source_id not in fragments
    )
    ordered = sorted(eligible, key=paragraph_priority)
    return {block.source_id for block in ordered[:max_calls]}


def select_stable_paragraph_sources(
    graph,
    scope,
    max_calls: int,
    *,
    extraction_table_rows=False,
    extraction_k3=False,
    extraction_qt1=False,
    rb1=None,
) -> set[str]:
    """Prioritize prose within a bounded preview; retain short candidates after it."""
    return select_batch_paragraph_sources(
        graph,
        scope,
        max_calls,
        extraction_table_rows=extraction_table_rows,
        extraction_k3=extraction_k3,
        extraction_qt1=extraction_qt1,
        rb1=rb1,
    )


def _extractor_role_budget(snapshot: dict) -> int | None:
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


def _live_extractor(extractor, graph, source=None, *, rb1=None):
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
    from proofops_agent.upstage_extraction import GraphBoundExtractor

    return GraphBoundExtractor(
        extractor,
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
        live,
        profile,
        prior,
        window,
        max_calls,
        *,
        prior_failed=None,
        prior_calls: int = 0,
        total_budget: int | None = None,
        extraction_table_rows: bool = False,
        extraction_k3: bool = False,
        extraction_qt1: bool = False,
        graph=None,
        rb1=None,
    ):
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
        self.stop_code = None
        self.stop_source = None

    def extract(self, packet):
        data = packet["untrusted_document_data"]
        source_id, text = data["source_id"], data["text"]
        if self._rb1 is not None:
            self._rb1.check(source_id)
        receipt = self._prior.get(source_id)
        if receipt is not None and receipt["packet_sha256"] == canonical_hash(packet):
            self.replayed.add(source_id)
            return json.loads(receipt["raw_response_json"])
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
        deferred = _deferred_reason(canonical_json(payload))
        if deferred:
            self.deferred[source_id] = deferred
        else:
            self.processed.add(source_id)
        return payload


class LocalExtractRunner:
    def __init__(
        self,
        store,
        uploads,
        parser,
        *,
        extractor: ClaimExtractorPort,
        telemetry,
        clock=time.time,
        max_workers=16,
        tag_composition=None,
    ):
        if not uploads.local_synthetic:
            raise ValueError("local extraction requires local storage")
        if type(max_workers) is not int or not 1 <= max_workers <= 24:
            raise ValueError("EXTRACTION_CONCURRENCY_INVALID")
        self.store, self.uploads, self.parser = store, uploads, parser
        self.extractor, self.telemetry, self.clock = extractor, telemetry, clock
        self.max_workers = max_workers
        self.tag_composition = tag_composition
        self.claims = LocalClaimStore(store, uploads, parser)

    def _publication_payload(
        self, lease, snapshot, graph, profile, discovery, *, tenant_id, run_id
    ):
        """Assemble the extract checkpoint exactly as the single-shot stage does."""
        current = self.store.jobs.get_run(tenant_id, run_id)
        checkpoint = self.store.jobs.read_checkpoint(JobMessage(**current["parse_job"]))
        if checkpoint is None:
            raise ValueError("PARSE_NOT_PUBLISHED")
        payload = snapshot_pins(snapshot, graph, profile, checkpoint)
        payload.update(
            discovery=asdict(discovery),
            synthetic=discovery.synthetic,
            coverage=discovery_coverage(json.loads(checkpoint)["coverage"], graph, discovery),
            extraction_outcome=extraction_outcome(
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

            reader = publication_reader(snapshot["claim_source_policy"])
            _, source, _ = load_run_inputs(
                self.store, self.uploads, tenant_id=tenant_id, run_id=run_id
            )
            self.store.jobs.heartbeat(lease, now=int(self.clock()), lease_seconds=300)
            payload["claim_source_attestation"] = attest_claims(
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

            payload["occurrence_groups"] = occurrence_groups(discovery.claims)
        return payload

    def run_batch(self, *, tenant_id: str, run_id: str, max_calls: int | None = None) -> dict:
        """Process the next bounded window of eligible sources as a new revision.

        The published revision is a new immutable extract checkpoint under its own
        job id: the previous checkpoint stays byte-identical and readable by its
        own message, while the run head advances. Sources already model-processed
        are replayed from their stored receipts, so no provider call is repeated
        and no claim is duplicated. Returns an honest per-batch summary; it never
        reports a source as absent.
        """
        snapshot = self.store.snapshot(tenant_id, run_id)
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
                guard_extract_continuation(db, self.store.jobs, current, now=int(self.clock()))
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
            prior_envelope, _, graph = self.claims.load_evidence(
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
                guard_extract_continuation(db, self.store.jobs, current, now=int(self.clock()))
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
        state = extraction_batch_state(prior_envelope)
        profile = extraction_profile(snapshot)
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
        scope = claim_scope(snapshot, graph)
        prior_charged = len(state["model_processed"]) + len(state["failed"])
        usage_records = self.store.jobs.list_usage(tenant_id, run_id)
        charged_from_usage = sum(
            row.get("extractor_calls", 0) for row in usage_records if isinstance(row, dict)
        )
        prior_calls = max(prior_charged, charged_from_usage)
        completed = set(state["model_processed"]) | set(state["failed"])
        rb1 = InputIsolation(snapshot.get("analysis_profile_policy", {}))
        if rb1.active:
            for excluded in prior_envelope["discovery"]["exclusions"]:
                code = excluded["reason"]
                if code.startswith("TABLE_RB1_"):
                    rb1.capture(excluded["source_id"], ValueError(code.removeprefix("TABLE_RB1_")))
        if rb4_memory_enabled(snapshot):
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
        usage = {"model_calls": 0, "extractor_calls": 0}
        outcome: dict = {}

        def operation(lease):
            since = 0 if profile.synthetic else self.extractor.usage_checkpoint()
            usage_lock = Lock()

            def sync_usage():
                if not profile.synthetic:
                    with usage_lock:
                        usage.update(
                            self.extractor.cumulative_usage(
                                since=since, parse_manifest_id=graph.parse_manifest_id
                            )
                        )

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

                def extract(self, packet):
                    fence_provider_call(runner, lease, usage)
                    if not rb3_admit(runner, snapshot, "extract"):
                        return deferred_payload(
                            packet["untrusted_document_data"]["text"], "TIME_BUDGET"
                        )
                    if not profile.synthetic:
                        authorization = check_local_upstage_binding(
                            binding=snapshot["runtime"],
                            consent=snapshot["consent"],
                            auth=AuthContext(
                                "local-worker", tenant_id, "viewer", frozenset(), run_id
                            ),
                            checked_at=datetime.fromtimestamp(runner.clock(), UTC).isoformat(),
                            source_sha256=graph.source_sha256,
                            model_sha256=profile.model_sha256,
                        )
                        if not authorization.ready:
                            raise ValueError("LOCAL_TEST_AUTHORIZATION_INVALID")
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
                    if prepare and not fresh_execution_enabled():
                        prepare(packets)
                    paid = prefetch_packets(
                        packets,
                        live.extract,
                        max_workers=self.max_workers,
                        **(dict(prepare_pages=prepare) if fresh_execution_enabled() else {}),
                    )
                    sync_usage()

                    class PrefetchedLive:
                        prepaid = paid.keys()

                        def extract(self, packet):
                            answer = paid[packet["untrusted_document_data"]["source_id"]]
                            if isinstance(answer, Exception):
                                raise answer
                            return answer

                    selected_live = PrefetchedLive()
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
            published = extraction_batch_state(self.claims.load_evidence(tenant_id, run_id)[0])
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
        snapshot = self.store.snapshot(tenant_id, run_id)
        probe = getattr(self.extractor, "_probe", None)
        if probe is not None and hasattr(probe, "configure_response_policy"):
            probe.configure_response_policy(snapshot, role="extract")
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
                usage_lock = Lock()

                def sync_usage():
                    if is_real:
                        with usage_lock:
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
                        try:
                            validate_extraction_limits(limits, snapshot["selected_pages"])
                            valid_limits = True
                        except ValueError:
                            valid_limits = False
                        if (
                            not valid_limits
                            or snapshot.get("extraction_mode") != "upstage_probe"
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
                    rb1 = InputIsolation(snapshot.get("analysis_profile_policy", {}))
                    display_profile = getattr(runner.extractor, "_display_text_profile", None)
                    if display_profile:
                        from proofops.application.ingest.display_text import POLICY, PROFILE

                        if (
                            display_profile != PROFILE
                            or snapshot.get("display_text_policy") != POLICY
                        ):
                            raise ValueError("DISPLAY_POLICY_MISMATCH")
                    elif "display_text_policy" in snapshot:
                        raise ValueError("DISPLAY_POLICY_MISMATCH")
                    source = (
                        runner.uploads.read_original(tenant_id, graph.document_version_id)
                        if display_profile
                        else None
                    )
                    live_extractor = _live_extractor(runner.extractor, graph, source, rb1=rb1)
                    role_budget = _extractor_role_budget(snapshot)
                    effective_max = (
                        (
                            limits["max_calls"]
                            if role_budget is None
                            else min(limits["max_calls"], role_budget)
                        )
                        if is_real
                        else 0
                    )
                    fxg_guard = fxg_dispatch_guard(
                        runner, lease, usage, snapshot, graph, profile, effective_max
                    )
                    eligible_sources: set[str] | None = None
                    if is_real:
                        eligible_sources = select_stable_paragraph_sources(
                            graph,
                            claim_scope(snapshot, graph),
                            effective_max,
                            extraction_table_rows=getattr(runner.extractor, "_table_rows", False),
                            extraction_k3=getattr(runner.extractor, "_k3", False),
                            extraction_qt1=getattr(runner.extractor, "_qt1", False),
                            rb1=rb1,
                        )

                    class FencedExtractor:
                        def __init__(self):
                            self.profile = profile
                            self.calls = 0

                        def extract(self, packet):
                            rb1.check(packet["untrusted_document_data"]["source_id"])
                            fence_provider_call(runner, lease, usage)
                            if is_real:
                                data = packet["untrusted_document_data"]
                                reason = (
                                    "non_paragraph_kind"
                                    if not _is_text_candidate(
                                        data["kind"],
                                        data["text"],
                                        extraction_table_rows=getattr(
                                            runner.extractor, "_table_rows", False
                                        ),
                                        extraction_k3=getattr(runner.extractor, "_k3", False),
                                        extraction_qt1=getattr(runner.extractor, "_qt1", False),
                                        graph=graph,
                                        source_id=data["source_id"],
                                        rb1=rb1,
                                    )
                                    else "beyond_extraction_limit"
                                    if data.get("source_id") not in eligible_sources
                                    or self.calls >= effective_max
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
                                if not rb3_admit(runner, snapshot, "extract"):
                                    return deferred_payload(data["text"], "TIME_BUDGET")
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
                            with usage_lock:
                                self.calls += 1
                                usage["extractor_calls"] += 1
                            try:
                                return _candidate_extract(
                                    live_extractor, packet, snapshot, fxg_guard=fxg_guard
                                )
                            finally:
                                sync_usage()

                    selected_extractor = FencedExtractor()
                    page_pipeline = None
                    if is_real and getattr(
                        getattr(self.extractor, "_probe", None), "model", None
                    ) in ("openai/gpt-6-luna", "gpt-6-luna"):
                        scope = claim_scope(snapshot, graph)
                        candidates = sorted(
                            (
                                block
                                for block in graph.blocks
                                if block.source_id in eligible_sources
                            ),
                            key=lambda block: (block.page_num, block.source_id),
                        )
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
                            for block in candidates
                        ]
                        base_extractor = selected_extractor
                        prepare = getattr(live_extractor, "prefetch", None)
                        if prepare and not fresh_execution_enabled():
                            prepare(packets)
                        if snapshot.get("pipeline_profile") == "finals-unattended-v1":
                            from proofops_worker.unattended_pipeline import PageTagPipeline

                            parse_run = self.store.jobs.get_run(tenant_id, run_id)
                            parse_checkpoint = self.store.jobs.read_checkpoint(
                                JobMessage(**parse_run["parse_job"])
                            )
                            page_pipeline = PageTagPipeline(
                                self, snapshot, graph, profile, lease, parse_checkpoint
                            )
                        paid = prefetch_packets(
                            packets,
                            base_extractor.extract,
                            max_workers=self.max_workers,
                            on_page=page_pipeline.ready if page_pipeline else None,
                            **(dict(prepare_pages=prepare) if fresh_execution_enabled() else {}),
                        )

                        class PrefetchedExtractor:
                            profile = base_extractor.profile

                            def extract(self, packet):
                                source_id = packet["untrusted_document_data"]["source_id"]
                                if source_id not in paid:
                                    return base_extractor.extract(packet)
                                answer = paid[source_id]
                                if isinstance(answer, Exception):
                                    raise answer
                                return answer

                        selected_extractor = PrefetchedExtractor()
                    discovery = discover_atomic_claims(
                        graph, claim_scope(snapshot, graph), extractor=selected_extractor
                    )
                    current = self.store.jobs.get_run(tenant_id, run_id)
                    checkpoint = self.store.jobs.read_checkpoint(JobMessage(**current["parse_job"]))
                    if checkpoint is None:
                        raise ValueError("PARSE_NOT_PUBLISHED")
                    payload = snapshot_pins(snapshot, graph, profile, checkpoint)
                    coverage = discovery_coverage(
                        json.loads(checkpoint)["coverage"], graph, discovery
                    )
                    if page_pipeline is not None:
                        payload["page_tag_pipeline"] = page_pipeline.finish()
                    payload.update(
                        discovery=asdict(discovery),
                        synthetic=discovery.synthetic,
                        extraction_outcome=extraction_outcome(
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
                        coverage=coverage,
                    )
                    if (
                        snapshot.get("analysis_profile_policy", {}).get("extraction_pb1")
                        == "pb1-v1"
                    ):
                        from proofops.application.ingest.pb1_tables import occurrence_groups

                        payload["occurrence_groups"] = occurrence_groups(discovery.claims)
                    if "claim_source_policy" in snapshot:
                        from proofops.adapters.local.claim_source_policies import (
                            attest_claims,
                            publication_reader,
                        )
                        from proofops.adapters.local.claim_source_verification import (
                            discovery_refs,
                        )
                        from proofops.adapters.local.run_artifacts import load_run_inputs

                        reader = publication_reader(snapshot["claim_source_policy"])
                        _, source, _ = load_run_inputs(
                            self.store, self.uploads, tenant_id=tenant_id, run_id=run_id
                        )
                        self.store.jobs.heartbeat(lease, now=int(self.clock()), lease_seconds=300)
                        payload["claim_source_attestation"] = attest_claims(
                            reader=reader,
                            graph=graph,
                            source=source.content,
                            refs=discovery_refs(discovery),
                            tenant_id=tenant_id,
                            cache=snapshot.get("pipeline_profile")
                            in (
                                "finals-unattended-v1",
                                "finals-unattended-v2",
                                "finals-unattended-j3-v1",
                                "finals-unattended-j7-v1",
                                "finals-unattended-j8-v1",
                            ),
                            run_id=run_id,
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
                owner="local-extract:" + str(uuid4()),
                clock=lambda: int(self.clock()),
                lease_seconds=300,
                operation=lambda lease: observe_job(
                    self.telemetry,
                    lease,
                    lambda active_lease: with_lease_heartbeat(
                        self.store.jobs, active_lease, self.clock, operation
                    ),
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
