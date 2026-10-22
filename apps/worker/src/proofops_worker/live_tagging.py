"""Scoped local Upstage composition; immutable receipts, no implicit rule approval."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import Lock

from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.authorization import AuthContext
from proofops.application.budget import BudgetExceeded
from proofops.application.evidence.binding import local_relation_tags
from proofops.application.input_reservation import validate_capacity_policy
from proofops.application.ports.jobs import LeaseLost
from proofops.application.preflight import check_local_upstage_tagger
from proofops.application.registry import Registry, artifact_sha256
from proofops.application.tagging.preliminary import (
    preliminary_request,
    preliminary_table_request,
)
from proofops.application.tagging.relations import (
    OCCURRENCE_PROFILE,
    OCCURRENCE_V3_PROFILE,
    RelationValidationError,
)
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport
from proofops_agent.upstage_tagging import (
    TransportResume,
    UpstageTaggingTransport,
)

from proofops_worker.consumer import TagHeartbeatFailed, point_heartbeat
from proofops_worker.tagging_parts.decisions import (
    configure_decisions,
    decision_pair,
    decision_preliminary,
)
from proofops_worker.tagging_parts.preliminary import (
    build_preliminary_packet,
    preliminary_agreement,
    validate_preliminary_response,
)
from proofops_worker.tagging_parts.relations import (
    build_relation_packet,
    validate_relation_response,
)
from proofops_worker.tagging_parts.replicas import (
    _LOCAL_STOP_SUFFIXES as _LOCAL_STOP_SUFFIXES,
)
from proofops_worker.tagging_parts.replicas import (
    _VALIDATION_CODES as _VALIDATION_CODES,
)
from proofops_worker.tagging_parts.replicas import (
    _VALIDATION_REASONS as _VALIDATION_REASONS,
)
from proofops_worker.tagging_parts.replicas import (
    LOCAL_STOP_CODE as LOCAL_STOP_CODE,
)
from proofops_worker.tagging_parts.replicas import (
    _local_stop_code,
    account,
    flush_accounting,
    source_replicas,
    update_accounting,
)


class LiveTaggingRuntime:
    synthetic = False
    heartbeat_state = None

    def _check_heartbeat(self):
        if self.heartbeat_state is not None:
            self.heartbeat_state.check()

    def reserve_tag_call(self, call, **kwargs):
        """The claim-volume allowance never replaces persisted or USD limits."""
        if not hasattr(self, "s2_call_allowance"):
            return self.runner.store.usage.reserve_budget(call, **kwargs)
        with self._account_lock:
            if len(self.s2_reserved_calls) >= self.s2_call_allowance:
                raise BudgetExceeded("BUDGET_EXHAUSTED: claim-volume call allowance")
            reserved = self.runner.store.usage.reserve_budget(call, **kwargs)
            if reserved:
                self.s2_reserved_calls.add((call.request_id, call.attempt))
            return reserved

    def __init__(self, runner, snapshot, graph, lease, usage, *, probe, ledger, receipts):
        from proofops.application.evidence.relation_attribution import snapshot_policy

        self.attribution_policy = snapshot_policy(snapshot)
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
        self.probe = probe
        if hasattr(probe, "configure_response_policy"):
            probe.configure_response_policy(snapshot, role="elements")
        # An acknowledged bounded resume authorization, when the owning runner is
        # executing an explicit recovery job. None in ordinary operation, which
        # keeps every stop, receipt and budget behavior exactly as it was.
        self.resume = getattr(runner, "resume", None)
        if self.resume is not None:
            if not isinstance(self.resume, TransportResume):
                raise ValueError("LIVE_TAGGING_RESUME_INVALID")
            if (
                self.resume.expected_root is not None
                and self.resume.expected_root.resolve() != self.receipts.resolve()
            ):
                # An authorization is bound to the exact receipt tree it was proven
                # against; it can never be applied to a different local state.
                raise ValueError("LIVE_TAGGING_RESUME_ROOT_MISMATCH")
        self.settings = tagging_settings(snapshot)
        self.preliminary_settings = tagging_settings(snapshot, preliminary=True)
        self.registry = Registry.sqlite(runner.store.path)
        self.auth = AuthContext(
            "local-worker", graph.tenant_id, "viewer", frozenset(), snapshot["run_id"]
        )
        self.allowed_packets = set()
        self.preliminary_records = {}
        self.relation_records = {}
        self.decision_records = {}
        self.decision_request_ids = {p: set() for p in ("openai", "openrouter")}
        self.relation_settings = (
            tagging_settings(snapshot, relation=True) if "relation_settings" in snapshot else None
        )
        self.request_ids = set()
        accounting = snapshot.get("analysis_profile_policy", {}).get("s5_usage_accounting")
        if accounting not in (None, "s5_final_reporting_snapshot_v1"):
            raise ValueError("S5_USAGE_ACCOUNTING_POLICY_MISMATCH")
        self._s5_defer_accounting = accounting is not None
        self._account_lock = Lock()
        self.previously_accounted = {
            identifier
            for row in runner.store.jobs.list_usage(graph.tenant_id, snapshot["run_id"])
            for identifier in row.get("tag_request_ids", [])
        }
        self.display_catalog = None
        if "display_text_policy" in snapshot:
            from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
            from proofops.application.ingest.display_text import POLICY

            if snapshot["display_text_policy"] != POLICY:
                raise ValueError("DISPLAY_POLICY_MISMATCH")
            source = runner.uploads.read_original(graph.tenant_id, graph.document_version_id)
            self.display_catalog = GlyphDisplayCatalog(graph, source)
        self.element_transport = UpstageTaggingTransport(
            probe,
            self.receipts / "elements",
            settings=self.settings,
            tenant_id=graph.tenant_id,
            authorize=self._authorize,
            resume=self.resume,
            display_catalog=self.display_catalog,
        )
        self.preliminary_transport = UpstagePreliminaryTransport(
            probe,
            self.receipts / "preliminary",
            settings=self.preliminary_settings,
            tenant_id=graph.tenant_id,
            authorize=self._authorize,
            resume=self.resume,
            display_catalog=self.display_catalog,
        )
        if self.relation_settings is not None:
            from proofops_agent.upstage_relations import (
                UpstageDecisionGateRelationsTransport,
                UpstageOccurrenceRelationsTransport,
                UpstageOccurrenceV3RelationsTransport,
                UpstageRelationsTransport,
            )

            transport = {
                OCCURRENCE_PROFILE: UpstageOccurrenceRelationsTransport,
                OCCURRENCE_V3_PROFILE: UpstageOccurrenceV3RelationsTransport,
                "relation-decision-gate-v1": UpstageDecisionGateRelationsTransport,
            }.get(self.relation_settings.model_profile, UpstageRelationsTransport)
            self.relation_transport = transport(
                probe,
                self.receipts / "relation",
                settings=self.relation_settings,
                tenant_id=graph.tenant_id,
                authorize=self._authorize,
                resume=self.resume,
            )
        configure_decisions(self, runner, snapshot, ledger)
        self._capacity(self.settings.model_id)

    def _capacity(self, model_id):
        if model_id == "gpt-6-luna":
            from proofops.adapters.local.openai import validate_capacity_policy as validate_openai

            return validate_openai(self.snapshot["input_reservation_policy"], model_id=model_id)
        if model_id == "openai/gpt-6-luna":
            from proofops.adapters.local.openrouter import (
                validate_capacity_policy as validate_luna_capacity,
            )

            return validate_luna_capacity(
                self.snapshot["input_reservation_policy"], model_id=model_id
            )
        return validate_capacity_policy(
            self.snapshot["input_reservation_policy"],
            model_id=model_id,
            checked_at=datetime.fromtimestamp(self.runner.clock(), UTC),
        )

    def _fence(self):
        from proofops.adapters.local.verified_read_cache import _parse_enabled

        self._check_heartbeat()
        now = int(self.runner.clock())
        if not _parse_enabled() and not self.runner.store.jobs.can_call(self.lease, now=now):
            raise LeaseLost("LEASE_LOST")
        try:
            point_heartbeat(
                self.runner.store.jobs, self.lease, self.runner.clock, state=self.heartbeat_state
            )
        except Exception as error:
            if self.heartbeat_state is not None:
                self.heartbeat_state.fail(error)
            if isinstance(error, LeaseLost):
                raise
            raise TagHeartbeatFailed() from None
        self._check_heartbeat()

    def _authorize(self, settings, request):
        self._fence()
        prefix = next(
            (
                name
                for name, selected in (
                    ("preliminary", self.preliminary_settings),
                    ("tagging", self.settings),
                    ("relation", self.relation_settings),
                )
                if selected is not None and settings == selected
            ),
            None,
        )
        if prefix is None:
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

    def display_packet(self, packet, *, claim=None):
        display_catalog = getattr(self, "display_catalog", None)
        policy = getattr(self, "snapshot", {}).get("analysis_profile_policy", {})
        from proofops.application.ingest.k5_context import POLICY as K5_POLICY
        from proofops.application.ingest.k5_context import configured_context

        k5 = policy.get("sentence_context_policy") == K5_POLICY
        if display_catalog is None and not k5:
            return packet
        from proofops.application.evidence.retrieval import freeze_packet

        data = packet.to_dict()
        data.pop("packet_sha256")
        scope_refs = (
            getattr(self, "scope_records", {})
            .get(claim.claim_id if claim else None, {})
            .get("source_refs", [])
        )
        if scope_refs and "G4" in data["allowed_elements"]:
            for ref in scope_refs:
                candidate = next(
                    c for c in data["evidence_candidates"] if c["source_id"] == ref["source_id"]
                )
                candidate["source_refs"].append(ref)
        if k5:
            if claim is None or claim.claim_id != data["claim_id"]:
                raise ValueError("SENTENCE_CONTEXT_CLAIM_REQUIRED")
            data["sentence_context"] = configured_context(claim, self.graph, policy)
        if "tagging_wire_policy" in policy:
            from proofops.application.tagging.k7_wire import POLICY as K7_WIRE
            from proofops.application.tagging.k7_wire import POLICY_K8 as K8_WIRE
            from proofops.application.tagging.k7_wire import POLICY_K8_V2 as K8_WIRE_V2
            from proofops.application.tagging.k7_wire import POLICY_K8_V3 as K8_WIRE_V3
            from proofops.application.tagging.k7_wire import POLICY_K10 as K10_WIRE
            from proofops.application.tagging.k7_wire import POLICY_V1 as K7_WIRE_V1
            from proofops.application.tagging.k11_contract import WIRE_POLICY as K11_WIRE
            from proofops.application.tagging.k11_contract import WIRE_V1_POLICY as K11_WIRE_V1

            if policy["tagging_wire_policy"] not in (
                K7_WIRE,
                K7_WIRE_V1,
                K8_WIRE,
                K8_WIRE_V2,
                K8_WIRE_V3,
                K10_WIRE,
                K11_WIRE,
                K11_WIRE_V1,
            ):
                raise ValueError("K7_WIRE_POLICY_MISMATCH")
            data["tagging_wire_policy"] = policy["tagging_wire_policy"]
        if policy.get("table_evidence") in (
            "table-selected-evidence-pb2-v1",
            "table-selected-evidence-k4-v1",
            "table-selected-evidence-k7-v1",
        ):
            from proofops.application.tagging.pb2_table_evidence import (
                OBSERVED_POLICY,
                POLICY,
                ROW_UNIT_POLICY,
                augment_packet,
            )

            if claim is None or claim.claim_id != data["claim_id"]:
                raise ValueError("TABLE_EVIDENCE_CLAIM_REQUIRED")
            data = augment_packet(
                data,
                claim,
                self.graph,
                tenant_id=self.graph.tenant_id,
                policy=OBSERVED_POLICY
                if policy["table_evidence"] == OBSERVED_POLICY["profile"]
                else ROW_UNIT_POLICY
                if policy["table_evidence"] == ROW_UNIT_POLICY["profile"]
                else POLICY,
            )
        for key in (
            "tagging_response_policy",
            "selected_quantity_policy",
            "structural_quality_policy",
        ):
            if key in policy:
                data[key] = policy[key]
        if "local_implementation_binding_policy" in policy:
            from proofops.application.tagging.k9_contract import (
                BINDING_POLICY,
                BINDING_V1_POLICY,
                BINDING_V2_POLICY,
                BINDING_V3_POLICY,
                BINDING_V4_POLICY,
            )

            if policy["local_implementation_binding_policy"] not in (
                BINDING_V1_POLICY,
                BINDING_V2_POLICY,
                BINDING_V3_POLICY,
                BINDING_V4_POLICY,
                BINDING_POLICY,
            ) or policy.get("local_implementation_binding_policy_sha256") != canonical_hash(
                policy["local_implementation_binding_policy"]
            ):
                raise ValueError("K9_BINDING_POLICY_MISMATCH")
            data["local_implementation_binding_policy"] = policy[
                "local_implementation_binding_policy"
            ]
        if "qt2_contextual_elements_policy" in policy:
            from proofops.application.tagging.qt2_context import augment_packet, validate_policy

            contextual = policy["qt2_contextual_elements_policy"]
            validate_policy(contextual)
            if policy.get("qt2_contextual_elements_policy_sha256") != canonical_hash(contextual):
                raise ValueError("QT2_CONTEXT_POLICY_PIN_MISMATCH")
            data = augment_packet(data, claim, self.graph, tenant_id=self.graph.tenant_id)
        if "qt1_tuple_policy" in policy:
            from proofops.application.tagging.qt1_tuples import POLICY, augment_packet

            if policy["qt1_tuple_policy"] != POLICY:
                raise ValueError("QT1_TUPLE_POLICY_MISMATCH")
            data = augment_packet(data, claim, self.graph, tenant_id=self.graph.tenant_id)
        if "tb1_table_policy" in policy:
            from proofops.application.tagging.tb1_table_bundles import POLICY, augment_packet

            if policy["tb1_table_policy"] != POLICY or policy.get(
                "tb1_table_policy_sha256"
            ) != canonical_hash(POLICY):
                raise ValueError("TB1_TABLE_POLICY_MISMATCH")
            augment_packet(data, claim, self.graph, tenant_id=self.auth.tenant_id)
        if "v3_dec92_policy" in policy:
            from proofops.application.tagging.v3_context import augment_packet as v3_augment
            from proofops.application.tagging.v3_dec92 import validate_policy as validate_v3

            validate_v3(policy["v3_dec92_policy"])
            if policy.get("v3_dec92_policy_sha256") != canonical_hash(policy["v3_dec92_policy"]):
                raise ValueError("V3_DEC92_POLICY_PIN_MISMATCH")
            data = v3_augment(data, claim, self.graph, tenant_id=self.graph.tenant_id)
        if display_catalog is not None:
            data["display_text"] = display_catalog.element_pins(data)
        if policy.get("hold_recovery_policy") is not None:
            from proofops.application.tagging.k2_recovery import validate_policy

            validate_policy(policy["hold_recovery_policy"])
            if policy.get("hold_recovery_policy_sha256") != canonical_hash(
                policy["hold_recovery_policy"]
            ):
                raise ValueError("K2_RECOVERY_POLICY_PIN_MISMATCH")
            data["local_element_recovery_policy"] = policy["hold_recovery_policy"]
        if self.snapshot.get("analysis_profile_policy", {}).get("hold_recovery") == "hf1-v1":
            from proofops.application.tagging.citation_restore import POLICY

            data["citation_restore_policy"] = POLICY
        if policy.get("citation_restore") == "citation-table-separators-pb2-v1":
            from proofops.application.tagging.pb2_citation_restore import POLICY

            data["citation_restore_policy"] = POLICY
        if policy.get("citation_restore") == "citation-selected-value-pb6-v1":
            from proofops.application.tagging.pb6_citation_restore import POLICY

            data["citation_restore_policy"] = POLICY
        if policy.get("citation_restore") == "citation-selected-adjacent-unit-k6-v1":
            from proofops.application.tagging.k6_citations import POLICY

            data["citation_restore_policy"] = POLICY
        return freeze_packet(data)

    def allow_packet(self, claim_id, packet_sha256):
        self.allowed_packets.add((claim_id, packet_sha256))

    @staticmethod
    def token_counter(text):
        # Retrieval size bound only; provider reservation uses the full capacity below.
        return len(text.encode("utf-8"))

    def count_input_tokens(self, request):
        # Validate the actual wire and current authority before reserving its upper bound.
        # A withdrawn or exhausted recovery allowance stops here, before any
        # reservation: tag_replicates records TAGGING_INPUT_COUNT_INVALID and
        # moves on without buying a call or settling a ledger row.
        if not self.element_transport.may_dispatch():
            raise ValueError("TAGGING_RECOVERY_ALLOWANCE_EXHAUSTED")
        return self.element_transport.count_input_tokens(
            request, counter=lambda system, user: self._capacity(self.settings.model_id)
        )

    def account(self, request_id):
        return account(self, request_id)

    def _update_accounting(self):
        return update_accounting(self)

    def flush_accounting(self):
        return flush_accounting(self)

    def invoke(self, request):
        try:
            context = (
                self.probe.response_context(role="elements", replica=request["replicate_id"])
                if hasattr(self.probe, "response_context")
                else nullcontext()
            )
            with context:
                return self.element_transport.invoke(request)
        finally:
            self.account(request["request_id"])

    def preliminary(self, claim, graph):
        from proofops.application.tagging import cf5_context

        display_catalog = getattr(self, "display_catalog", None)
        plan = build_preliminary_packet(
            claim,
            graph,
            snapshot=self.snapshot,
            settings=self.preliminary_settings,
            tenant_id=self.auth.tenant_id,
            bound_context=lambda packet: self.preliminary_transport.bound_context(packet),
            display_catalog=display_catalog,
            preliminary_request=preliminary_request,
            preliminary_table_request=preliminary_table_request,
        )
        if plan is None:
            self.preliminary_records[claim.claim_id] = []
            return None
        packet, context_receipt = plan.packet, plan.context_receipt
        decision, unattended, cf5 = plan.decision, plan.unattended, plan.cf5

        def validate(raw):
            return validate_preliminary_response(
                raw,
                claim=claim,
                graph=graph,
                tenant_id=self.auth.tenant_id,
                snapshot=self.snapshot,
                attribution_policy=self.attribution_policy,
                display_catalog=display_catalog,
                plan=plan,
            )

        results = self._source_replicas(
            "preliminary",
            claim,
            packet,
            self.preliminary_settings,
            self.preliminary_transport,
            self.preliminary_records,
            validate,
            **({"require_consensus": False} if decision or unattended else {}),
            **({"context_receipt": context_receipt} if context_receipt else {}),
        )
        if decision:
            return self._decision_preliminary(claim, packet, results)
        if unattended and results:
            from collections import Counter

            from proofops.application.evidence.binding import ClaimContext

            votes = Counter(
                (r.track.track if r.track else None, r.safe_harbor_category) for r in results
            )
            header, count = votes.most_common(1)[0]
            if cf5 and not cf5_context.header_agreed(
                [(r.track.track if r.track else None, r.safe_harbor_category) for r in results]
            ):
                return None
            if count < 2 or header[0] is None:
                return None
            winners = [
                r for r in results if r.track and (r.track.track, r.safe_harbor_category) == header
            ]
            dimensions = {}
            for key in set().union(*(r.context.dimensions for r in winners)):
                values = [r.context.dimensions.get(key) for r in winners]
                dimensions[key] = values[0] if all(v == values[0] for v in values) else None
            self.preliminary_records[claim.claim_id].append(
                dict(
                    status="cf5_unanimous" if cf5 else "provisional_majority",
                    votes=count,
                    total_replicas=3,
                )
            )
            context = ClaimContext(claim, dimensions)
            return winners[0].track, context, local_relation_tags(context)
        if results is None or results[0].track is None:
            return None
        context = results[0].context
        return results[0].track, context, local_relation_tags(context)

    def preliminary_agreement(self, claim_id):
        return preliminary_agreement(self, claim_id)

    def relations(self, claim, packet):
        """Tag only verified external sources already present in this frozen packet."""
        self.relation_records[claim.claim_id] = []
        if self.relation_settings is None:
            return {}
        try:
            plan = build_relation_packet(
                claim,
                packet,
                graph=self.graph,
                tenant_id=self.auth.tenant_id,
                snapshot=self.snapshot,
                settings=self.relation_settings,
                attribution_policy=self.attribution_policy,
                preliminary_records=self.preliminary_records,
            )
            if not plan.sources:
                self.relation_records[claim.claim_id] = plan.refusals
                return plan.refused
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.relation_records[claim.claim_id] = [
                dict(
                    status="needs_review",
                    stable_reason=dict(
                        category="local_stop",
                        error_code=(
                            error.code
                            if isinstance(error, RelationValidationError)
                            else _local_stop_code("relation", error)
                        ),
                        detail=error.field if isinstance(error, RelationValidationError) else None,
                    ),
                )
            ]
            return None

        sources, envelope, anchors = plan.sources, plan.envelope, plan.anchors
        refused, refusals = plan.refused, plan.refusals
        validate = partial(
            validate_relation_response,
            claim=claim,
            graph=self.graph,
            tenant_id=self.auth.tenant_id,
            settings=self.relation_settings,
            attribution_policy=self.attribution_policy,
            plan=plan,
        )
        results = self._source_replicas(
            "relation",
            claim,
            envelope,
            self.relation_settings,
            self.relation_transport,
            self.relation_records,
            validate,
            retrieval_packet_sha256=packet.packet_sha256,
            require_consensus=False,
        )
        self.relation_records[claim.claim_id].extend(refusals)
        if results is None:
            return None
        # A disputed source stays wholly unresolved; never combine roles from
        # different replicas into a relationship that no replica proposed.
        resolved = {
            source_id: roles
            if all(result[source_id] == roles for result in results)
            else {name: None for result in results for name in result[source_id]}
            for source_id, roles in results[0].items()
        }
        if self.relation_settings.model_profile == "relation-decision-gate-v1":
            from proofops.application.tagging.decisions import relation_questions, resolve_relation

            for index, source in enumerate(sources):
                state = dict(
                    claim=claim.quote,
                    claim_dimensions=anchors,
                    evidence_paragraph=source.quote,
                    occurrence_v3=envelope["untrusted_document_data"]["sources"][index],
                    validated_roles={
                        k: asdict(v) if v else None for k, v in resolved[source.source_id].items()
                    },
                )
                pair, receipts = self._decision_pair(
                    claim,
                    state,
                    relation_questions(),
                    "relation:" + source.source_id,
                    packet_sha256=canonical_hash(envelope),
                    retrieval_packet_sha256=packet.packet_sha256,
                )
                choices = [
                    a.get("relation", {}).get("choice") if a.get("relation") else "unknown"
                    for a in pair
                ]
                support = resolve_relation(*choices)
                self.relation_records[claim.claim_id].append(
                    dict(
                        source_id=source.source_id,
                        decision_relation=support,
                        status="validated_candidate" if support == "supports" else "needs_review",
                        review_message=None if support == "supports" else "후보 있음·확인 필요",
                        model_answers=pair,
                        decision_receipts=receipts,
                    )
                )
                if support != "supports":
                    resolved[source.source_id] = {name: None for name in resolved[source.source_id]}
        return refused | resolved

    def _decision_pair(
        self, claim, state, questions, purpose, *, packet_sha256, retrieval_packet_sha256=None
    ):
        return decision_pair(
            self,
            claim,
            state,
            questions,
            purpose,
            packet_sha256=packet_sha256,
            retrieval_packet_sha256=retrieval_packet_sha256,
        )

    def _decision_preliminary(self, claim, packet, results):
        return decision_preliminary(self, claim, packet, results)

    def _run_source_replicas(self, run_one, settings):
        workers = (
            min(getattr(self, "replica_workers", getattr(self.runner, "max_workers", 1)), 3)
            if settings.model_id in ("openai/gpt-6-luna", "gpt-6-luna")
            and settings.wire_policy_version == 2
            else 1
        )
        if workers == 1 or self.resume is not None:
            outcomes = []
            for replica in (1, 2, 3):
                outcome = run_one(replica)
                outcomes.append(outcome)
                if outcome[-1]:
                    break
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                outcomes = list(pool.map(run_one, (1, 2, 3)))
        return outcomes

    def _source_replicas(
        self,
        prefix,
        claim,
        packet,
        settings,
        transport,
        record_store,
        validate,
        *,
        retrieval_packet_sha256=None,
        require_consensus=True,
        context_receipt=None,
    ):
        return source_replicas(
            self,
            prefix,
            claim,
            packet,
            settings,
            transport,
            record_store,
            validate,
            retrieval_packet_sha256=retrieval_packet_sha256,
            require_consensus=require_consensus,
            context_receipt=context_receipt,
        )
