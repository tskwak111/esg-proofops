"""Single extraction delivery with original lease, usage and publication order."""

from __future__ import annotations

from typing import Any, cast

from proofops.application.claims import ClaimExtractorPort
from proofops.application.ports.jobs import JobLease

from proofops_worker import extract_runner as runtime
from proofops_worker.extraction_parts.attempt import PaidClaimExtractor


def run_once(self: runtime.LocalExtractRunner, *, tenant_id: str, run_id: str) -> str:
    snapshot = self.store.snapshot(tenant_id, run_id)
    probe = getattr(self.extractor, "_probe", None)
    if probe is not None and hasattr(probe, "configure_response_policy"):
        probe.configure_response_policy(snapshot, role="extract")
    run = self.store.jobs.get_run(tenant_id, run_id)
    if run["cancellation_requested"]:
        return "cancelled"
    for event in self.store.jobs.pending_outbox(tenant_id, run_id, now=int(self.clock())):
        message = runtime.JobMessage(**event["message"])
        if message.stage != "extract":
            continue
        next_job = runtime.replace(
            message, job_id=str(runtime.uuid5(runtime.UUID(message.job_id), "tag")), stage="tag"
        )

        def operation(lease: JobLease) -> tuple[bytes, dict[str, Any]]:
            usage: dict[str, Any] = {"model_calls": 0, "extractor_calls": 0}
            attempt = runtime.ExtractionAttemptContext(self, snapshot, usage)
            usage_lock = attempt.lock
            sync_usage = attempt.sync_usage

            try:
                profile = runtime.extraction_profile(snapshot)
                is_real = attempt.is_real = not profile.synthetic
                if is_real:
                    limits = cast(dict[str, Any], snapshot.get("extraction_limits"))
                    try:
                        runtime.validate_extraction_limits(limits, snapshot["selected_pages"])
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
                    attempt.since = cast(PaidClaimExtractor, self.extractor).usage_checkpoint()
                if profile != self.extractor.profile or (
                    message.document_version_id != snapshot["document"]["version_id"]
                    or message.input_hash != snapshot["input_hash"]
                ):
                    raise ValueError("EXTRACTION_PROFILE_MISMATCH")
                graph = runtime.load_run_graph(
                    self.store, self.uploads, self.parser, tenant_id=tenant_id, run_id=run_id
                )
                runner = self
                rb1 = runtime.InputIsolation(snapshot.get("analysis_profile_policy", {}))
                display_profile = getattr(runner.extractor, "_display_text_profile", None)
                if display_profile:
                    from proofops.application.ingest.display_text import POLICY, PROFILE

                    if display_profile != PROFILE or snapshot.get("display_text_policy") != POLICY:
                        raise ValueError("DISPLAY_POLICY_MISMATCH")
                elif "display_text_policy" in snapshot:
                    raise ValueError("DISPLAY_POLICY_MISMATCH")
                source = (
                    runner.uploads.read_original(tenant_id, graph.document_version_id)
                    if display_profile
                    else None
                )
                live_extractor = runtime._live_extractor(runner.extractor, graph, source, rb1=rb1)
                role_budget = runtime._extractor_role_budget(snapshot)
                effective_max = (
                    (
                        limits["max_calls"]
                        if role_budget is None
                        else min(limits["max_calls"], role_budget)
                    )
                    if is_real
                    else 0
                )
                fxg_guard = runtime.fxg_dispatch_guard(
                    runner, lease, usage, snapshot, graph, profile, effective_max
                )
                eligible_sources: set[str] | None = None
                if is_real:
                    eligible_sources = runtime.select_stable_paragraph_sources(
                        graph,
                        runtime.claim_scope(snapshot, graph),
                        effective_max,
                        extraction_table_rows=getattr(runner.extractor, "_table_rows", False),
                        extraction_k3=getattr(runner.extractor, "_k3", False),
                        extraction_qt1=getattr(runner.extractor, "_qt1", False),
                        rb1=rb1,
                    )

                class FencedExtractor:
                    def __init__(self) -> None:
                        self.profile = profile
                        self.calls = 0

                    def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
                        rb1.check(packet["untrusted_document_data"]["source_id"])
                        runtime.fence_provider_call(runner, lease, usage)
                        if is_real:
                            data = packet["untrusted_document_data"]
                            reason = (
                                "non_paragraph_kind"
                                if not runtime._is_text_candidate(
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
                                if data.get("source_id") not in cast(set[str], eligible_sources)
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
                            if not attempt.admit(
                                graph,
                                profile,
                                tenant_id=tenant_id,
                                run_id=run_id,
                                admit=runtime.rb3_admit,
                                check_binding=runtime.check_local_upstage_binding,
                            ):
                                return runtime.deferred_payload(data["text"], "TIME_BUDGET")
                        with usage_lock:
                            self.calls += 1
                            usage["extractor_calls"] += 1
                        try:
                            return runtime._candidate_extract(
                                live_extractor, packet, snapshot, fxg_guard=fxg_guard
                            )
                        finally:
                            sync_usage()

                selected_extractor: ClaimExtractorPort = FencedExtractor()
                page_pipeline = None
                if is_real and getattr(getattr(self.extractor, "_probe", None), "model", None) in (
                    "openai/gpt-6-luna",
                    "gpt-6-luna",
                ):
                    scope = runtime.claim_scope(snapshot, graph)
                    candidates = sorted(
                        (
                            block
                            for block in graph.blocks
                            if block.source_id in cast(set[str], eligible_sources)
                        ),
                        key=lambda block: (block.page_num, block.source_id),
                    )
                    packets = [
                        dict(
                            tenant_id=scope.tenant_id,
                            document_version_id=scope.document_version_id,
                            parse_manifest_id=scope.parse_manifest_id,
                            source_sha256=graph.source_sha256,
                            extraction_profile=runtime.asdict(profile),
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
                    if prepare and not runtime.fresh_execution_enabled():
                        prepare(packets)
                    if snapshot.get("pipeline_profile") == "finals-unattended-v1":
                        from proofops_worker.unattended_pipeline import PageTagPipeline

                        parse_run = self.store.jobs.get_run(tenant_id, run_id)
                        parse_checkpoint = self.store.jobs.read_checkpoint(
                            runtime.JobMessage(**parse_run["parse_job"])
                        )
                        page_pipeline = PageTagPipeline(
                            self, snapshot, graph, profile, lease, cast(bytes, parse_checkpoint)
                        )
                    paid = runtime.prefetch_packets(
                        packets,
                        base_extractor.extract,
                        max_workers=self.max_workers,
                        on_page=page_pipeline.ready if page_pipeline else None,
                        **(
                            dict(prepare_pages=prepare) if runtime.fresh_execution_enabled() else {}
                        ),
                    )

                    class PrefetchedExtractor:
                        profile = base_extractor.profile

                        def extract(self, packet: dict[str, Any]) -> dict[str, Any]:
                            source_id = packet["untrusted_document_data"]["source_id"]
                            if source_id not in paid:
                                return base_extractor.extract(packet)
                            answer = paid[source_id]
                            if isinstance(answer, Exception):
                                raise answer
                            return answer

                    selected_extractor = PrefetchedExtractor()
                discovery = runtime.discover_atomic_claims(
                    graph,
                    runtime.claim_scope(snapshot, graph),
                    extractor=selected_extractor,
                )
                current = self.store.jobs.get_run(tenant_id, run_id)
                checkpoint = self.store.jobs.read_checkpoint(
                    runtime.JobMessage(**current["parse_job"])
                )
                if checkpoint is None:
                    raise ValueError("PARSE_NOT_PUBLISHED")
                payload = runtime.snapshot_pins(snapshot, graph, profile, checkpoint)
                coverage = runtime.discovery_coverage(
                    runtime.json.loads(checkpoint)["coverage"], graph, discovery
                )
                if page_pipeline is not None:
                    payload["page_tag_pipeline"] = page_pipeline.finish()
                payload.update(
                    discovery=runtime.asdict(discovery),
                    synthetic=discovery.synthetic,
                    extraction_outcome=runtime.extraction_outcome(
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
                if snapshot.get("analysis_profile_policy", {}).get("extraction_pb1") == "pb1-v1":
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
                    _, source_artifact, _ = load_run_inputs(
                        self.store, self.uploads, tenant_id=tenant_id, run_id=run_id
                    )
                    self.store.jobs.heartbeat(lease, now=int(self.clock()), lease_seconds=300)
                    payload["claim_source_attestation"] = attest_claims(
                        reader=reader,
                        graph=graph,
                        source=source_artifact.content,
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
                return runtime.canonical_json(payload).encode(), usage
            except runtime.LeaseLost:
                raise runtime.StageFailure("LEASE_LOST", usage=usage) from None
            except ValueError as error:
                runtime._f1_failure_origin(error, snapshot)
                code = str(error)
                acquisition_code = runtime.ocr_acquisition_failure_code(error)
                if acquisition_code:
                    code = "OCR_PAGE_ACQUISITION_FAILED:" + acquisition_code
                elif code not in runtime.UPSTAGE_TRANSPORT_STOP_CODES | {
                    "LOCAL_TEST_AUTHORIZATION_INVALID",
                    "ACCOUNTING_UNAVAILABLE",
                }:
                    code = "EXTRACTION_INPUT_INVALID"
                if code == "ACCOUNTING_UNAVAILABLE":
                    usage.update(model_calls=None, accounting_complete=False)
                raise runtime.StageFailure(code, usage=usage) from None
            except (
                KeyError,
                TypeError,
                runtime.ParseFailure,
                runtime.UploadRejected,
                runtime.PdfReadError,
            ) as error:
                runtime._f1_failure_origin(error, snapshot)
                raise runtime.StageFailure(
                    runtime.source_failure_code(error) or "EXTRACTION_INPUT_INVALID", usage=usage
                ) from None

        result = runtime.consume_job(
            self.store.jobs,
            message,
            owner="local-extract:" + str(runtime.uuid4()),
            clock=lambda: int(self.clock()),
            lease_seconds=300,
            operation=lambda lease: runtime.observe_job(
                self.telemetry,
                lease,
                lambda active_lease: runtime.with_lease_heartbeat(
                    self.store.jobs, active_lease, self.clock, operation
                ),
                context=runtime.TraceContext.new(
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
