"""Source-replica dispatch, receipt recovery and accounting; element votes stay separate."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from proofops.adapters.local.upstage import request_usage
from proofops.application.budget import BudgetCall, BudgetExceeded, TokenUsage
from proofops.application.claims import Claim
from proofops.application.ports.jobs import LeaseLost
from proofops.application.tagging.contracts import TaggingSettings
from proofops.application.tagging.relations import (
    RelationValidationError,
)
from proofops.application.tagging.service import RawTagResponse, output_reservation_tokens
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops_agent.upstage_tagging import (
    NEVER_SENT_ERROR_CODES,
)

from proofops_worker.tagging_parts.contracts import ReplicaOutcome, ReplicaValue, SourceTransport

# The local stop conditions this module raises itself, per replica prefix. Recording
# only these keeps a durable record free of arbitrary exception text while still
# naming the exact condition that stopped the operation.
_LOCAL_STOP_SUFFIXES = (
    "_RECEIPT_INCOMPLETE_OR_MISMATCH",
    "_PENDING_CALL",
    "_PROVIDER_FAILED",
    "_PROVIDER_ID_REQUIRED",
    "_RECOVERY_ALLOWANCE_EXHAUSTED",
)
LOCAL_STOP_CODE = "LOCAL_STOP"
_VALIDATION_REASONS = {
    "display quote absent or ambiguous": "DISPLAY_QUOTE_UNRESOLVED",
    "preliminary quote absent or ambiguous": "PRELIMINARY_QUOTE_UNRESOLVED",
    "invalid preliminary fields; grades are prohibited": "PRELIMINARY_FIELDS_INVALID",
    "invalid preliminary safe harbor category": "PRELIMINARY_CATEGORY_INVALID",
    "unresolved track requires null confidence": "PRELIMINARY_CONFIDENCE_INVALID",
    "invalid preliminary confidence": "PRELIMINARY_CONFIDENCE_INVALID",
    "preliminary claim mismatch": "PRELIMINARY_CLAIM_MISMATCH",
    "required preliminary dimension roles missing": "PRELIMINARY_ROLES_MISSING",
    "invalid preliminary source span": "PRELIMINARY_SPAN_INVALID",
    "invalid preliminary source selection": "PRELIMINARY_SELECTION_INVALID",
    "preliminary span outside literal claim source": "PRELIMINARY_SPAN_OUTSIDE_SOURCE",
}
_VALIDATION_CODES = frozenset(
    """PROBE_REQUEST_TOO_LARGE INVALID_PROBE_REQUEST DISPLAY_PACKET_MISMATCH
DISPLAY_MAP_MISMATCH DISPLAY_REF_MISMATCH DISPLAY_CONTEXT_MISMATCH DISPLAY_PRELIMINARY_SELECTION
UPSTAGE_PRELIMINARY_PROMPT_INVALID UPSTAGE_PRELIMINARY_SYSTEM_REQUIRED
UPSTAGE_PRELIMINARY_PACKET_INVALID UPSTAGE_PRELIMINARY_PACKET_MISMATCH
UPSTAGE_PRELIMINARY_CONTEXT_POLICY_INVALID UPSTAGE_PRELIMINARY_SOURCES_REQUIRED
UPSTAGE_PRELIMINARY_TABLE_SOURCE_INVALID UPSTAGE_PRELIMINARY_TABLE_POLICY_INVALID
UPSTAGE_PRELIMINARY_CONTEXT_INVALID RELATION_PACKET_MISMATCH RELATION_CLAIM_MISMATCH
K1_PUE_PERFORMANCE_RETAG_REQUIRED K4_CONNECTIVE_GOAL_RETAG_REQUIRED""".split()
)


if TYPE_CHECKING:
    from proofops_worker.live_tagging import LiveTaggingRuntime


def _local_stop_code(prefix: str, error: BaseException) -> str:
    """Map a local stop to a stable code; never echo an unrecognized message."""
    if isinstance(error, BudgetExceeded) or str(error) in {
        "R108_FINALS_BUDGET_EXHAUSTED",
        "R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED",
        "BUDGET_EXHAUSTED",
    }:
        return "BUDGET_EXHAUSTED"
    if str(error) == "PROCESSING_UNCERTAIN":
        return "PROCESSING_UNCERTAIN"
    known = {prefix.upper() + suffix for suffix in _LOCAL_STOP_SUFFIXES}
    text = str(error)
    if text in known:
        return text
    if text in _VALIDATION_CODES:
        return text
    if text in _VALIDATION_REASONS:
        return _VALIDATION_REASONS[text]
    return prefix.upper() + "_" + LOCAL_STOP_CODE + ":" + type(error).__name__


def source_replicas(
    self: LiveTaggingRuntime,
    prefix: str,
    claim: Claim,
    packet: dict[str, Any],
    settings: TaggingSettings,
    transport: SourceTransport,
    record_store: dict[str, list[dict[str, Any]]],
    validate: Callable[[dict[str, Any]], tuple[ReplicaValue, dict[str, Any]]],
    *,
    retrieval_packet_sha256: str | None = None,
    require_consensus: bool = True,
    context_receipt: dict[str, Any] | None = None,
) -> list[ReplicaValue] | None:
    packet_hash = canonical_hash(packet)
    self.allow_packet(claim.claim_id, packet_hash)
    record_store[claim.claim_id] = []

    def run_one(replica: int) -> ReplicaOutcome[ReplicaValue]:
        records, results, signatures, provider_ids = [], [], [], []
        for replica in (replica,):
            self._check_heartbeat()
            request_id = str(
                uuid5(UUID(self.lease.message.job_id), f"{prefix}:{claim.claim_id}:{replica}")
            )
            request: dict[str, Any] = dict(
                tenant_id=self.auth.tenant_id,
                claim_id=claim.claim_id,
                packet_sha256=packet_hash,
                replicate_id=replica,
                request_id=request_id,
                binding=asdict(settings.binding),
                model_id=settings.model_id,
                model_profile=settings.model_profile,
                region=settings.region,
                system_prompt=settings.rendered_system,
                user_json=canonical_json(packet),
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
                input_reservation_policy_sha256=self.snapshot["input_reservation_policy_hash"],
            )
            if retrieval_packet_sha256 is not None:
                request["retrieval_packet_sha256"] = retrieval_packet_sha256
            from proofops.application.tagging.pb2_preliminary import enabled as pb2_enabled

            if prefix == "preliminary" and pb2_enabled(
                claim, self.graph, self.snapshot.get("analysis_profile_policy", {})
            ):
                request["preliminary_fact_fields"] = "preliminary-fact-fields-pb2-v1"
                scope = self.snapshot.get("analysis_profile_policy", {}).get(
                    "preliminary_fact_fields_scope"
                )
                if scope is not None:
                    request["preliminary_fact_fields_scope"] = scope
            if self.snapshot.get("pipeline_profile") in (
                "unattended-v1",
                "finals-unattended-v1",
                "finals-unattended-v2",
                "finals-unattended-j3-v1",
                "finals-unattended-j7-v1",
                "finals-unattended-j8-v1",
            ):
                request["pipeline_profile"] = self.snapshot["pipeline_profile"]
            request["request_signature"] = canonical_hash(request)
            call = BudgetCall(
                self.auth.tenant_id,
                self.snapshot["run_id"],
                self.graph.document_version_id,
                request_id,
                1,
                "tagger",
                settings.model_id,
                settings.region,
                settings.model_sha256,
                request["request_signature"],
                replica,
            )
            directory = self.receipts / prefix / request_id
            record: dict[str, Any] = dict(
                request_id=request_id, replicate_id=replica, status="unresolved"
            )
            if context_receipt:
                record.update(context_receipt)
            records.append(record)
            response = None
            try:
                capacity = transport.count_input_tokens(
                    request, counter=lambda system, user: self._capacity(settings.model_id)
                )
                if directory.exists():
                    retained = json.loads((directory / "request.json").read_text())
                    if (
                        retained["request"] != request
                        or not (directory / "response.json").is_file()
                    ):
                        raise ValueError(prefix.upper() + "_RECEIPT_INCOMPLETE_OR_MISMATCH")
                    raw = json.loads((directory / "response.json").read_text())
                    response = RawTagResponse(**(raw | {"usage": TokenUsage(**raw["usage"])}))
                else:
                    # A withdrawn or exhausted recovery allowance stops before the
                    # reservation, so no budget is held and no ledger row settles
                    # for a request this operation is no longer authorized to send.
                    if not transport.may_dispatch():
                        raise ValueError(prefix.upper() + "_RECOVERY_ALLOWANCE_EXHAUSTED")
                    self._fence()
                    lock = (
                        self.heartbeat_state.lock
                        if self.heartbeat_state is not None
                        else nullcontext()
                    )
                    with lock:
                        self._check_heartbeat()
                        if not self.reserve_tag_call(
                            call,
                            input_tokens=capacity,
                            # Source transports aggregate schema-retry usage just
                            # like element tagging; reserve every allowed output.
                            max_output_tokens=output_reservation_tokens(
                                model_id=settings.model_id,
                                max_tokens=settings.max_tokens,
                                synthetic=settings.binding.synthetic,
                            ),
                            pricing=None,
                            now=int(self.runner.clock()),
                        ):
                            raise ValueError(prefix.upper() + "_PENDING_CALL")
                    self._fence()
                    with lock:
                        self._check_heartbeat()
                        if not self.runner.store.usage.mark_dispatched(call):
                            raise ValueError(prefix.upper() + "_PENDING_CALL")
                    self._check_heartbeat()
                    context = (
                        self.probe.response_context(
                            role="elements" if prefix == "tagging" else prefix,
                            replica=replica,
                        )
                        if hasattr(self.probe, "response_context")
                        else nullcontext()
                    )
                    with context:
                        response = transport.invoke(request)
                self.runner.store.usage.record_usage(
                    call, response.usage, now=int(self.runner.clock())
                )
                if (
                    response.synthetic
                    or response.usage.status != "succeeded"
                    or not response.raw_response_json
                ):
                    raise ValueError(prefix.upper() + "_PROVIDER_FAILED")
                result, values = validate(json.loads(response.raw_response_json))
                record.update(
                    status="validated_candidate",
                    values=values,
                    raw_response_sha256=canonical_hash(response.raw_response_json),
                )
                if not response.usage.provider_request_id:
                    raise ValueError(prefix.upper() + "_PROVIDER_ID_REQUIRED")
                results.append(result)
                signatures.append(canonical_hash(values))
                provider_ids.append(response.usage.provider_request_id)
            except LeaseLost:
                raise
            except (ValueError, OSError, KeyError, TypeError, BudgetExceeded) as error:
                # Never collapse the actual outcome to a bare "needs_review": a
                # provider error_code (e.g. UPSTREAM_UNAVAILABLE) means this specific
                # attempt was never actually sent (locally suppressed, latency 0ms,
                # no provider_request_id); that is a distinct, stable fact from a
                # real settled provider failure or a local/authorization/budget stop
                # raised before any transport call. Both are surfaced here so a
                # never-sent attempt is never misread as an unknown model outcome.
                usage = getattr(response, "usage", None)
                settled_code = getattr(usage, "error_code", None)
                record.update(
                    status="needs_review",
                    stable_reason=dict(
                        # "never_sent" requires the transport's own explicitly
                        # known local-suppression code, not merely a zero latency:
                        # a fast real failure can also round to 0ms and lack a
                        # provider id. The durable proof that no call happened is
                        # the absent receipt directory, checked by the recovery
                        # classifier; this label only reports the transport's
                        # settled code without reinterpreting it.
                        category="never_sent"
                        if usage is not None
                        and usage.status == "failed"
                        and settled_code in NEVER_SENT_ERROR_CODES
                        and usage.provider_request_id is None
                        and usage.latency_ms == 0
                        else "provider_failed"
                        if usage is not None and usage.status == "failed"
                        else "local_stop",
                        # Stable internal codes only. An unrecognized exception
                        # never leaks its message text into a durable record.
                        error_code=settled_code
                        or (
                            error.code
                            if prefix == "relation" and isinstance(error, RelationValidationError)
                            else _local_stop_code(prefix, error)
                        ),
                        detail=(
                            error.field
                            if prefix == "relation" and isinstance(error, RelationValidationError)
                            else None
                        ),
                    ),
                )
                return records, results, signatures, provider_ids, True
            finally:
                self.account(request_id)
        return records, results, signatures, provider_ids, False

    outcomes = self._run_source_replicas(run_one, settings)
    records, results, signatures, provider_ids = [], [], [], []
    failed = False
    for outcome in outcomes:
        replica_records, replica_results, replica_signatures, replica_ids, replica_failed = outcome
        records.extend(replica_records)
        results.extend(replica_results)
        signatures.extend(replica_signatures)
        provider_ids.extend(replica_ids)
        failed |= replica_failed
    record_store[claim.claim_id] = records
    unattended_majority = prefix == "preliminary" and self.snapshot.get("pipeline_profile") in (
        "unattended-v1",
        "finals-unattended-v1",
        "finals-unattended-v2",
        "finals-unattended-j3-v1",
        "finals-unattended-j7-v1",
        "finals-unattended-j8-v1",
    )
    if failed and not (unattended_majority and len(results) >= 2):
        return None
    if (
        len(set(provider_ids)) != len(provider_ids)
        or (not unattended_majority and len(set(provider_ids)) != 3)
    ) or (require_consensus and len(set(signatures)) != 1):
        return None
    return results


def account(self: LiveTaggingRuntime, request_id: str) -> None:
    with self._account_lock:
        if request_id not in self.previously_accounted:
            self.request_ids.add(request_id)
        if not self._s5_defer_accounting:
            self._update_accounting()


def update_accounting(self: LiveTaggingRuntime) -> None:
    identifiers = sorted(self.request_ids)
    self.usage.update(request_usage(self.ledger, identifiers))
    self.usage["tag_request_ids"] = identifiers


def flush_accounting(self: LiveTaggingRuntime) -> None:
    with self._account_lock:
        self._update_accounting()
