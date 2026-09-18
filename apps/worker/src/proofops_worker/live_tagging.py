"""Scoped local Upstage composition; immutable receipts, no implicit rule approval."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from proofops.adapters.local.tag_store import tagging_settings
from proofops.adapters.local.upstage import request_usage
from proofops.application.authorization import AuthContext
from proofops.application.budget import BudgetCall, BudgetExceeded, TokenUsage
from proofops.application.input_reservation import validate_capacity_policy
from proofops.application.ports.jobs import LeaseLost
from proofops.application.preflight import check_local_upstage_tagger
from proofops.application.registry import Registry, artifact_sha256
from proofops.application.tagging.preliminary import preliminary_request, validate_preliminary
from proofops.application.tagging.service import RawTagResponse
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport
from proofops_agent.upstage_tagging import UpstageTaggingTransport


class LiveTaggingRuntime:
    synthetic = False

    def __init__(self, runner, snapshot, graph, lease, usage, *, probe, ledger, receipts):
        if (
            snapshot.get("tagging_mode") != "upstage_local"
            or snapshot["input_hash"]
            != canonical_hash({k: v for k, v in snapshot.items() if k != "input_hash"})
            or (graph.tenant_id, graph.document_version_id, graph.source_sha256)
            != (
                snapshot["tenant_id"],
                snapshot["document"]["version_id"],
                snapshot["document"]["sha256"],
            )
        ):
            raise ValueError("LIVE_TAGGING_SNAPSHOT_MISMATCH")
        self.runner, self.snapshot, self.graph, self.lease, self.usage = (
            runner,
            snapshot,
            graph,
            lease,
            usage,
        )
        self.ledger, self.receipts = ledger, Path(receipts)
        self.settings = tagging_settings(snapshot)
        self.preliminary_settings = tagging_settings(snapshot, preliminary=True)
        self.registry = Registry.sqlite(runner.store.path)
        self.auth = AuthContext(
            "local-worker", graph.tenant_id, "viewer", frozenset(), snapshot["run_id"]
        )
        self.allowed_packets = set()
        self.preliminary_records = {}
        self.request_ids = set()
        self.previously_accounted = {
            identifier
            for row in runner.store.jobs.list_usage(graph.tenant_id, snapshot["run_id"])
            for identifier in row.get("tag_request_ids", [])
        }
        self.element_transport = UpstageTaggingTransport(
            probe,
            self.receipts / "elements",
            settings=self.settings,
            tenant_id=graph.tenant_id,
            authorize=self._authorize,
        )
        self.preliminary_transport = UpstagePreliminaryTransport(
            probe,
            self.receipts / "preliminary",
            settings=self.preliminary_settings,
            tenant_id=graph.tenant_id,
            authorize=self._authorize,
        )
        self._capacity(self.settings.model_id)

    def _capacity(self, model_id):
        return validate_capacity_policy(
            self.snapshot["input_reservation_policy"],
            model_id=model_id,
            checked_at=datetime.fromtimestamp(self.runner.clock(), UTC),
        )

    def _fence(self):
        now = int(self.runner.clock())
        if not self.runner.store.jobs.can_call(self.lease, now=now):
            raise LeaseLost("LEASE_LOST")
        self.runner.store.jobs.heartbeat(self.lease, now=now, lease_seconds=300)

    def _authorize(self, settings, request):
        self._fence()
        prefix = "preliminary" if settings == self.preliminary_settings else "tagging"
        if settings != getattr(
            self, "preliminary_settings" if prefix == "preliminary" else "settings"
        ):
            raise ValueError("LIVE_TAGGING_SETTINGS_MISMATCH")
        if (request.get("claim_id"), request.get("packet_sha256")) not in self.allowed_packets:
            raise ValueError("LIVE_TAGGING_PACKET_NOT_AUTHORIZED")
        self._capacity(settings.model_id)
        policy_hash = canonical_hash(self.snapshot["input_reservation_policy"])
        if policy_hash != self.snapshot["input_reservation_policy_hash"]:
            raise ValueError("LIVE_TAGGING_POLICY_MISMATCH")
        binding = self.snapshot[prefix + "_runtime"]
        if binding.get("input_reservation_policy_sha256") != policy_hash:
            raise ValueError("LIVE_TAGGING_POLICY_NOT_AUTHORIZED")
        # A frozen grant cannot conceal a later revocation or replacement.
        for kind, frozen, identifier in (
            ("runtime", binding, "runtime_binding_id"),
            ("consent", self.snapshot["consent"], "consent_profile_id"),
            ("rights", self.snapshot["rights"], "rights_profile_id"),
        ):
            try:
                current = self.registry.resolve_profile(self.auth, kind, frozen[identifier])
            except LookupError:
                raise ValueError("LIVE_TAGGING_AUTHORIZATION_REVOKED") from None
            if artifact_sha256(current) != artifact_sha256(frozen):
                raise ValueError("LIVE_TAGGING_AUTHORIZATION_CHANGED")
        return check_local_upstage_tagger(
            binding=binding,
            consent=self.snapshot["consent"],
            settings=settings,
            auth=self.auth,
            checked_at=datetime.fromtimestamp(self.runner.clock(), UTC).isoformat(),
            source_sha256=self.graph.source_sha256,
            document_rights=self.snapshot["document"]["metadata"]["rights_profile_id"],
        )

    def allow_packet(self, claim_id, packet_sha256):
        self.allowed_packets.add((claim_id, packet_sha256))

    @staticmethod
    def token_counter(text):
        # Retrieval size bound only; provider reservation uses the full capacity below.
        return len(text.encode("utf-8"))

    def count_input_tokens(self, request):
        # Validate the actual wire and current authority before reserving its upper bound.
        return self.element_transport.count_input_tokens(
            request, counter=lambda system, user: self._capacity(self.settings.model_id)
        )

    def account(self, request_id):
        if request_id not in self.previously_accounted:
            self.request_ids.add(request_id)
        self.usage.update(request_usage(self.ledger, sorted(self.request_ids)))
        self.usage["tag_request_ids"] = sorted(self.request_ids)

    def invoke(self, request):
        try:
            return self.element_transport.invoke(request)
        finally:
            self.account(request["request_id"])

    def preliminary(self, claim, graph):
        packet = preliminary_request(claim, graph, tenant_id=self.auth.tenant_id)
        packet_hash = canonical_hash(packet)
        self.allow_packet(claim.claim_id, packet_hash)
        settings = self.preliminary_settings
        records, results, signatures, provider_ids = [], [], [], []
        self.preliminary_records[claim.claim_id] = records
        for replica in (1, 2, 3):
            request_id = str(
                uuid5(UUID(self.lease.message.job_id), f"preliminary:{claim.claim_id}:{replica}")
            )
            request = dict(
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
            request["request_signature"] = canonical_hash(request)
            call = BudgetCall(
                self.auth.tenant_id,
                self.snapshot["run_id"],
                graph.document_version_id,
                request_id,
                1,
                "tagger",
                settings.model_id,
                settings.region,
                settings.model_sha256,
                request["request_signature"],
                replica,
            )
            directory = self.receipts / "preliminary" / request_id
            record = dict(request_id=request_id, replicate_id=replica, status="unresolved")
            records.append(record)
            try:
                capacity = self.preliminary_transport.count_input_tokens(
                    request, counter=lambda system, user: self._capacity(settings.model_id)
                )
                if directory.exists():
                    retained = json.loads((directory / "request.json").read_text())
                    if (
                        retained["request"] != request
                        or not (directory / "response.json").is_file()
                    ):
                        raise ValueError("PRELIMINARY_RECEIPT_INCOMPLETE_OR_MISMATCH")
                    raw = json.loads((directory / "response.json").read_text())
                    response = RawTagResponse(**(raw | {"usage": TokenUsage(**raw["usage"])}))
                else:
                    if not self.runner.store.usage.reserve_budget(
                        call,
                        input_tokens=capacity,
                        max_output_tokens=settings.max_tokens,
                        pricing=None,
                        now=int(self.runner.clock()),
                    ):
                        raise ValueError("PRELIMINARY_PENDING_CALL")
                    self._fence()
                    if not self.runner.store.usage.mark_dispatched(call):
                        raise ValueError("PRELIMINARY_PENDING_CALL")
                    response = self.preliminary_transport.invoke(request)
                self.runner.store.usage.record_usage(
                    call, response.usage, now=int(self.runner.clock())
                )
                if (
                    response.synthetic
                    or response.usage.status != "succeeded"
                    or not response.raw_response_json
                ):
                    raise ValueError("PRELIMINARY_PROVIDER_FAILED")
                result = validate_preliminary(
                    claim,
                    graph,
                    json.loads(response.raw_response_json),
                    tenant_id=self.auth.tenant_id,
                )
                values = dict(
                    track=asdict(result.track) if result.track else None,
                    dimensions={
                        key: asdict(value) if value else None
                        for key, value in result.context.dimensions.items()
                    },
                    safe_harbor_category=result.safe_harbor_category,
                )
                record.update(
                    status="validated_candidate",
                    values=values,
                    raw_response_sha256=canonical_hash(response.raw_response_json),
                )
                if not response.usage.provider_request_id:
                    raise ValueError("PRELIMINARY_PROVIDER_ID_REQUIRED")
                results.append(result)
                signatures.append(canonical_hash(values))
                provider_ids.append(response.usage.provider_request_id)
            except LeaseLost:
                raise
            except (ValueError, OSError, KeyError, TypeError, BudgetExceeded):
                record["status"] = "needs_review"
                return None
            finally:
                self.account(request_id)
        if len(set(signatures)) != 1 or len(set(provider_ids)) != 3 or results[0].track is None:
            return None
        return results[0].track, results[0].context, {}
