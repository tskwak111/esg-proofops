"""Three source-guarded invocations over one immutable evidence packet.

Composition supplies an authorized transport, scoped cache, durable usage store,
model tokenizer and clock. No credentials, model IDs, approvals or prices are
invented. Raw recovery is restricted to the exact request, never another vote.
"""

import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from typing import Any
from unicodedata import normalize
from uuid import UUID, uuid5

from proofops.adapters.cache.aws import (
    CacheNamespace,
    CacheRequest,
    ImmutableResponseCache,
    cache_request,
)
from proofops.application.budget import (
    BudgetCall,
    BudgetExceeded,
    PricingSnapshot,
    TokenUsage,
    UsageRepository,
    count,
    record_usage,
    reserve_budget,
)
from proofops.application.evidence.binding import ClaimContext, accept_binding, relation_tags_for
from proofops.application.evidence.packet_guard import PacketMetadata, guard_untrusted_packet
from proofops.application.evidence.report_level import scope_rejection_reason
from proofops.application.evidence.retrieval import (
    EvidencePacket,
    evidence_issue_ids,
    freeze_track_packet,
)
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.errors import DomainValidationError
from proofops.domain.numeric import unassigned_note_ids
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import RulePackSnapshot, canonical_json
from proofops.domain.values import LlmTags, SourceRef, _require_uuid, llm_tags_from_dict

_SAFE_INPUT_COUNT_CODES = frozenset(
    {
        "PROBE_REQUEST_TOO_LARGE",
        "PRICE_RECHECK_REQUIRED",
        "INVALID_PROBE_REQUEST",
        "TAGGING_RECOVERY_ALLOWANCE_EXHAUSTED",
        "UPSTAGE_TAGGING_REQUEST_INVALID",
        "UPSTAGE_TAGGING_CLASSIFICATION_REQUIRED",
        "UPSTAGE_TAGGING_CLASSIFICATION_INVALID",
        "UPSTAGE_TAGGING_PACKET_MISMATCH",
        "UPSTAGE_TAGGING_COVERAGE_INVALID",
        "UPSTAGE_TAGGING_ELEMENTS_REQUIRED",
        "LIVE_TAGGING_SETTINGS_MISMATCH",
        "LIVE_TAGGING_PACKET_NOT_AUTHORIZED",
        "LIVE_TAGGING_POLICY_MISMATCH",
        "LIVE_TAGGING_POLICY_NOT_AUTHORIZED",
        "LIVE_TAGGING_AUTHORIZATION_REVOKED",
        "LIVE_TAGGING_AUTHORIZATION_CHANGED",
    }
)


@dataclass(frozen=True, slots=True)
class TaggingSettings:
    binding: ModelBinding
    model_id: str
    model_profile: str
    region: str
    system_prompt: str
    schema_json: str
    max_tokens: int = 4096
    temperature: float = 0.0
    extraction_epoch: int = 1
    max_response_bytes: int = 1_048_576
    wire_policy_version: int = 1

    def __post_init__(self):
        if not isinstance(self.binding, ModelBinding) or self.binding.role != "tagger":
            raise DomainValidationError("tagger binding required")
        if type(self.binding.synthetic) is not bool:
            raise DomainValidationError("synthetic marker required")
        for value in (
            self.binding.binding_id,
            self.model_id,
            self.model_profile,
            self.region,
            self.system_prompt,
        ):
            if not isinstance(value, str) or not value.strip():
                raise DomainValidationError("explicit model and prompt settings required")
        if not isinstance(json.loads(self.schema_json), dict):
            raise DomainValidationError("JSON output schema required")
        if type(self.max_response_bytes) is not int or self.max_response_bytes <= 0:
            raise DomainValidationError("positive response byte limit required")
        if self.wire_policy_version not in (1, 2):
            raise DomainValidationError("invalid wire policy version")

    @property
    def rendered_system(self) -> str:
        return self.system_prompt + "\nOutput JSON schema:\n" + self.schema_json

    def system_for_track(self, track: str, safe_harbor_category: str | None) -> str:
        return (
            self.rendered_system
            + "\nValidated classification; tag only its elements: "
            + canonical_json(dict(track=track, safe_harbor_category=safe_harbor_category))
        )

    @property
    def model_sha256(self) -> str:
        identity: dict[str, Any] = dict(
            binding=asdict(self.binding),
            model_id=self.model_id,
            model_profile=self.model_profile,
            region=self.region,
        )
        if self.wire_policy_version == 2:
            identity["wire_policy_version"] = 2
        return canonical_hash(identity)

    @property
    def prompt_sha256(self) -> str:
        return canonical_hash(self.rendered_system)


@dataclass(frozen=True, slots=True)
class RawTagResponse:
    raw_response_json: str | None
    usage: TokenUsage
    synthetic: bool
    provider_response_json: str | None = None

    def __post_init__(self):
        if type(self.synthetic) is not bool or not isinstance(self.usage, TokenUsage):
            raise DomainValidationError("typed usage and synthetic provenance required")
        if any(
            value is not None and not isinstance(value, str)
            for value in (self.raw_response_json, self.provider_response_json)
        ):
            raise DomainValidationError("raw responses must be strings or null")


@dataclass(frozen=True, slots=True)
class TagRun:
    request: CacheRequest
    tenant_id: str
    run_id: str
    claim_id: str
    packet_sha256: str
    graph_sha256: str
    rule_sha256: str
    model_sha256: str
    prompt_sha256: str
    raw_response_json: str | None
    usage: TokenUsage | None
    guarded: LlmTags | None
    status: str
    errors: tuple[str, ...]
    source_scopes: tuple[tuple[str, str], ...]
    binding_hashes: tuple[tuple[str, str], ...]
    synthetic: bool
    product_variant: bool = False
    recovered: bool = False
    provider_response_json: str | None = None
    diagnostic_detail: str | None = None

    @property
    def replicate_id(self) -> int:
        return self.request.replicate_id

    @property
    def semantic_hash(self) -> str:
        data = asdict(self)
        data.pop("recovered")
        if data["diagnostic_detail"] is None:
            data.pop("diagnostic_detail")
        return canonical_hash(data)


def output_reservation_tokens(*, model_id: str, max_tokens: int, synthetic: bool) -> int:
    """Luna transports aggregate at most two schema responses per logical call.

    Reserve both outputs before dispatch; wire max_tokens stays per response.
    Synthetic and single-response transports retain their existing allowance.
    """
    attempts = 2 if not synthetic and model_id in ("gpt-6-luna", "openai/gpt-6-luna") else 1
    return max_tokens * attempts


def tag_replicates(
    packet: EvidencePacket,
    *,
    context: ClaimContext,
    track: TrackCandidate,
    original: CanonicalDocumentGraph,
    relation_tags: Mapping[str, Mapping[str, SourceRef | None]],
    rulepack: RulePackSnapshot,
    settings: TaggingSettings,
    cache: ImmutableResponseCache,
    usage_store: UsageRepository,
    invoke: Callable[[dict[str, Any]], RawTagResponse],
    tenant_id: str,
    ensemble_id: str,
    consent_profile: str,
    token_counter: Callable[[str], int],
    now: Callable[[], int],
    pricing: PricingSnapshot | None = None,
    count_input_tokens: Callable[[dict[str, Any]], int] | None = None,
    max_workers: int = 1,
    pipeline_profile: str | None = None,
    semantic_policy: dict | None = None,
    allow_edge_whitespace: bool = False,
    qt1_baseline_inventory=None,
) -> tuple[TagRun, ...]:
    """Execute or recover replicas 1/2/3, preserving failures and budget stops.

    Call freeze_track_packet once before this function and pass that same
    selected packet to form_consensus and immutable storage.

    No implicit retry or model fallback is performed. An indeterminate in-flight
    attempt stays pending for recovery; it is never sent twice. Absence and N/A
    require upstream approval/coverage unavailable in a bounded retrieval packet,
    so those model candidates remain unknown here. Computed numeric checks and
    covered-assurance assertions likewise require their dedicated services.
    """
    _require_uuid("ensemble_id", ensemble_id)
    _require_uuid("tenant_id", tenant_id)
    if not settings.binding.synthetic and not callable(count_input_tokens):
        raise DomainValidationError("TAGGING_INPUT_COUNTER_REQUIRED")
    if not isinstance(packet, EvidencePacket) or not isinstance(context, ClaimContext):
        raise DomainValidationError("immutable packet and claim context required")
    if type(allow_edge_whitespace) is not bool:
        raise DomainValidationError("edge-whitespace binding policy must be boolean")
    data = packet.to_dict()
    qt1_tuples, qt1_links = [], []
    if "qt1_tuple_policy" in data:
        from proofops.application.tagging.qt1_tuples import validate_packet

        qt1_tuples = validate_packet(data, context.claim, original, tenant_id=tenant_id)
    if "qt1_baseline_receipt" in data:
        from proofops.application.tagging.qt1_baseline import validate_packet as validate_baseline

        if qt1_baseline_inventory is None:
            raise DomainValidationError("QT1_BASELINE_INVENTORY_REQUIRED")
        qt1_links = validate_baseline(
            data, context, qt1_baseline_inventory, original, tenant_id=tenant_id
        )
    contextual_policy = data.get("qt2_contextual_elements_policy")
    if contextual_policy is not None:
        from proofops.application.tagging.qt2_context import accepts_context
        from proofops.application.tagging.qt2_context import validate_policy as validate_contextual

        validate_contextual(contextual_policy)
    v3_policy = data.get("v3_dec92_policy")
    if v3_policy is not None:
        from proofops.application.tagging.v3_context import accepts_context as accepts_v3
        from proofops.application.tagging.v3_dec92 import validate_policy as validate_v3

        validate_v3(v3_policy)
    local_recovery = data.get("local_element_recovery_policy")
    implementation_binding = data.get("local_implementation_binding_policy")
    structural_policy = data.get("structural_quality_policy")
    from proofops.application.tagging.q1_contract import QA2_POLICY, QUALITY_POLICIES

    r12_quality = structural_policy in QUALITY_POLICIES
    if structural_policy is not None:
        from proofops.application.tagging.q1_contract import validate_policy as validate_structural

        validate_structural(structural_policy)
    if implementation_binding is not None:
        from proofops.application.tagging.k9_contract import (
            BINDING_POLICY,
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
        )

        if implementation_binding not in (
            BINDING_V1_POLICY,
            BINDING_V2_POLICY,
            BINDING_V3_POLICY,
            BINDING_V4_POLICY,
            BINDING_POLICY,
        ):
            raise DomainValidationError("K9_BINDING_POLICY_MISMATCH")
    if local_recovery is not None:
        from proofops.application.tagging.k2_recovery import validate_policy

        validate_policy(local_recovery)
    claim = context.claim
    if pipeline_profile not in (
        None,
        "unattended-v1",
        "finals-unattended-v1",
        "finals-unattended-v2",
        "finals-unattended-j3-v1",
        "finals-unattended-j7-v1",
        "finals-unattended-j8-v1",
    ):
        raise DomainValidationError("unknown pipeline profile")
    unattended = (
        pipeline_profile
        in (
            "unattended-v1",
            "finals-unattended-v1",
            "finals-unattended-v2",
            "finals-unattended-j3-v1",
            "finals-unattended-j7-v1",
            "finals-unattended-j8-v1",
        )
        and data.get("pipeline_profile") == pipeline_profile
    )
    if not isinstance(track, TrackCandidate) or track.claim != claim:
        raise DomainValidationError("track/claim identity mismatch")
    if freeze_track_packet(packet, track=track, rulepack=rulepack) != packet:
        raise DomainValidationError("freeze the complete track packet before tagging")
    if (claim.source_quality != "verified" and not unattended) or (
        claim.document_version_id,
        claim.parse_manifest_id,
        claim.source_sha256,
    ) != (original.document_version_id, original.parse_manifest_id, original.source_sha256):
        raise DomainValidationError("claim/original source identity or quality mismatch")
    rendered_system = settings.system_for_track(track.track, track.safe_harbor_category)
    if semantic_policy is not None:
        from proofops.application.tagging.semantic_admission import validate_policy

        validate_policy(semantic_policy)
    prompt_sha256 = canonical_hash(rendered_system)
    expected = dict(
        tenant_id=tenant_id,
        document_version_id=claim.document_version_id,
        parse_manifest_id=claim.parse_manifest_id,
        claim_id=claim.claim_id,
        atomic_quote=claim.quote,
        source_sha256=claim.source_sha256,
        graph_sha256=canonical_hash(asdict(original)),
        rule_sha256=rulepack.sha256,
    )
    if (original.tenant_id, claim.tenant_id, rulepack.tenant_id) != (tenant_id,) * 3 or any(
        data.get(key) != value for key, value in expected.items()
    ):
        raise DomainValidationError("packet/claim/source identity mismatch")
    if data.get("status") != "candidate" or data.get("content_trust") != "untrusted_document_data":
        raise DomainValidationError("blocked or unguarded evidence packet")
    if data.get("claim_source_refs") != json.loads(
        canonical_json(
            [asdict(verify_source_ref(s, original, tenant_id=tenant_id)) for s in claim.source_refs]
        )
    ):
        raise DomainValidationError("atomic source span mismatch")
    if not unattended and any(
        unassigned_note_ids(original, ref.source_id) for ref in claim.source_refs
    ):
        raise DomainValidationError("unassigned footnote requires review")
    _require_uuid("run_id", data["run_id"])
    definitions = {e["id"]: e for e in rulepack.file_content("rubric/elements.yaml")["elements"]}
    allowed = tuple(data["allowed_elements"])
    if not allowed or len(set(allowed)) != len(allowed) or set(allowed) - definitions.keys():
        raise DomainValidationError("invalid allowed element catalog")
    document_context = data.get("document_context")
    if (
        not isinstance(document_context, dict)
        or set(document_context) - {"company", "period", "industry", "boundary"}
        or any(
            value is not None and not isinstance(value, str) for value in document_context.values()
        )
    ):
        raise DomainValidationError("invalid document context; gold/grades forbidden")
    source_candidates: dict[str, dict] = {}
    approved_refs: list[SourceRef] = []
    for candidate in data["evidence_candidates"]:
        if set(candidate) != {"source_id", "source_scope", "allowed_elements", "source_refs"}:
            raise DomainValidationError("invalid evidence candidate fields")
        if candidate["source_id"] in source_candidates:
            raise DomainValidationError("duplicate evidence candidate")
        source_candidates[candidate["source_id"]] = candidate
        for value in candidate["source_refs"]:
            source = SourceRef(**value)
            if unassigned_note_ids(original, source.source_id):
                raise DomainValidationError("unassigned footnote requires review")
            metadata = PacketMetadata(
                tenant_id,
                data["run_id"],
                claim.claim_id,
                source,
                settings.binding,
                (settings.binding,),
                rendered_system,
                1_048_576,
                2_097_152,
            )
            guarded = guard_untrusted_packet(
                source.quote, metadata, original=original, tenant_id=tenant_id
            )
            guarded.authorize_model(settings.binding)
            approved_refs.append(source)
    if not approved_refs and not unattended:
        raise DomainValidationError("verified packet evidence required")
    source_ids = {ref.source_id for ref in approved_refs}
    source_ids.update(ref.source_id for ref in claim.source_refs)
    if not unattended and evidence_issue_ids(
        original, source_ids, [*approved_refs, *claim.source_refs]
    ):
        raise DomainValidationError("open source issue requires review")
    # Explicit data allowlist: no prior votes, gold, tools or model-selected policy.
    user_data = {
        key: data[key]
        for key in (
            "atomic_quote",
            "claim_source_refs",
            "document_context",
            "allowed_elements",
            "evidence_candidates",
            "search_coverage",
        )
    }
    if contextual_policy is not None:
        user_data["qt2_contextual_elements_policy"] = contextual_policy
    if "qt1_tuple_policy" in data:
        user_data["qt1_tuple_policy"] = data["qt1_tuple_policy"]
        user_data["qt1_table_tuples"] = qt1_tuples
    if "qt1_baseline_receipt" in data:
        user_data["qt1_baseline_policy"] = data["qt1_baseline_receipt"]["policy"]
        user_data["qt1_baseline_links"] = [
            {k: link[k] for k in ("value", "unit", "period", "meaning", "elements")}
            for link in qt1_links
        ]
    if v3_policy is not None:
        user_data["v3_dec92_policy"] = v3_policy
    if implementation_binding is not None:
        user_data["local_implementation_binding_policy"] = implementation_binding
    if structural_policy is not None:
        user_data["structural_quality_policy"] = structural_policy
    if "display_text" in data:
        user_data["display_text"] = data["display_text"]
    if "tagging_wire_policy" in data:
        from proofops.application.tagging.k7_wire import POLICY as K7_WIRE
        from proofops.application.tagging.k7_wire import POLICY_K8 as K8_WIRE
        from proofops.application.tagging.k7_wire import POLICY_K8_V2 as K8_WIRE_V2
        from proofops.application.tagging.k7_wire import POLICY_K8_V3 as K8_WIRE_V3
        from proofops.application.tagging.k7_wire import POLICY_K10 as K10_WIRE
        from proofops.application.tagging.k7_wire import POLICY_V1 as K7_WIRE_V1
        from proofops.application.tagging.k11_contract import WIRE_POLICY as K11_WIRE
        from proofops.application.tagging.k11_contract import WIRE_V1_POLICY as K11_WIRE_V1

        if data["tagging_wire_policy"] not in (
            K7_WIRE,
            K7_WIRE_V1,
            K8_WIRE,
            K8_WIRE_V2,
            K8_WIRE_V3,
            K10_WIRE,
            K11_WIRE,
            K11_WIRE_V1,
        ):
            raise DomainValidationError("K7_WIRE_POLICY_MISMATCH")
        user_data["tagging_wire_policy"] = (
            data["tagging_wire_policy"]
            if data["tagging_wire_policy"]
            in (K8_WIRE, K8_WIRE_V2, K8_WIRE_V3, K10_WIRE, K11_WIRE, K11_WIRE_V1)
            else K7_WIRE
        )
    sentence_interpretation = None
    if "sentence_context" in data:
        from proofops.application.ingest.k5_context import sentence_context

        sentence_interpretation = sentence_context(claim, original)
        if data["sentence_context"] != sentence_interpretation:
            raise DomainValidationError("SENTENCE_CONTEXT_SOURCE_MISMATCH")
        # Interpretation references do not enter approved_refs/source_candidates.
        user_data["sentence_context"] = sentence_interpretation
        if data.get("tagging_wire_policy", {}).get("profile") in (
            "bounded-interpretation-k7-v2",
            "bounded-interpretation-k8-v1",
            "bounded-interpretation-k8-v2",
            "bounded-interpretation-k8-v3",
            "bounded-interpretation-k10-v1",
            "bounded-interpretation-k11-v1",
            "bounded-interpretation-k11-v2",
        ) and (sentence_interpretation is not None):
            focal = next(
                b for b in original.blocks if b.source_id == claim.source_refs[0].source_id
            )
            user_data["sentence_context"] = sentence_interpretation | dict(_source_kind=focal.kind)
    from proofops.application.tagging.k4_contract import RESPONSE_POLICY
    from proofops.application.tagging.k4_contract import VALUE_POLICY as K4_VALUE

    for key, expected in (
        ("tagging_response_policy", RESPONSE_POLICY),
        ("selected_quantity_policy", K4_VALUE),
    ):
        if key in data:
            if data[key] != expected:
                raise DomainValidationError("K4_POLICY_MISMATCH")
            user_data[key] = data[key]
    if "citation_restore_policy" in data:
        from proofops.application.tagging.citation_restore import POLICY
        from proofops.application.tagging.k6_citations import POLICY as K6_POLICY
        from proofops.application.tagging.pb2_citation_restore import POLICY as TABLE_POLICY
        from proofops.application.tagging.pb6_citation_restore import POLICY as VALUE_POLICY

        if data["citation_restore_policy"] not in (POLICY, TABLE_POLICY, VALUE_POLICY, K6_POLICY):
            raise DomainValidationError("CITATION_RESTORE_POLICY_UNKNOWN")
        user_data["citation_restore_policy"] = data["citation_restore_policy"]
    if "table_observation_evidence" in data:
        from proofops.application.tagging.pb2_table_evidence import validated_observation

        user_data["table_observation_evidence"] = validated_observation(
            data, claim, original, tenant_id=tenant_id
        )
    # Only typed coverage identifiers reach the model, never arbitrary metadata.
    user_data["search_coverage"] = {"not_found_state": "unknown"}
    graph_ids = {block.source_id for block in original.blocks}
    for key in ("omitted_source_ids", "unprocessed_source_ids"):
        values = data["search_coverage"].get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(sid, str) or sid not in graph_ids for sid in values
        ):
            raise DomainValidationError("invalid search coverage identifiers")
        user_data["search_coverage"][key] = list(values)
    if unattended:
        user_data["pipeline_profile"] = pipeline_profile
    namespace = CacheNamespace(tenant_id, consent_profile, claim.document_version_id, "tagger")
    synthetic = settings.binding.synthetic or bool(data["synthetic"])
    if type(max_workers) is not int or not 1 <= max_workers <= 24:
        raise ValueError("TAGGING_CONCURRENCY_INVALID")

    def run_one(replica):
        runs = []
        for replica in (replica,):
            user_json = canonical_json(
                dict(
                    packet_sha256=packet.packet_sha256,
                    replicate_id=replica,
                    claim_id=claim.claim_id,
                    untrusted_document_data=user_data,
                )
            )
            signature_options = dict(
                namespace=namespace,
                temperature=settings.temperature,
                model_id=settings.model_id,
                model_profile=settings.model_sha256,
                prompt_sha256=prompt_sha256,
                schema_sha256=canonical_hash(settings.schema_json),
                packet_sha256=packet.packet_sha256,
                tools=[],
                max_tokens=settings.max_tokens,
                replicate_id=replica,
                extraction_epoch=settings.extraction_epoch,
            )
            provisional = cache_request(request_id=ensemble_id, **signature_options)
            request = replace(
                provisional, request_id=str(uuid5(UUID(ensemble_id), provisional.request_signature))
            )
            identity: dict[str, Any] = dict(
                request=asdict(request),
                tenant_id=tenant_id,
                run_id=data["run_id"],
                claim_id=claim.claim_id,
                packet_sha256=packet.packet_sha256,
                graph_sha256=data["graph_sha256"],
                rule_sha256=rulepack.sha256,
                model_sha256=settings.model_sha256,
                prompt_sha256=prompt_sha256,
            )
            run = TagRun(
                request,
                tenant_id,
                data["run_id"],
                claim.claim_id,
                packet.packet_sha256,
                data["graph_sha256"],
                rulepack.sha256,
                settings.model_sha256,
                prompt_sha256,
                None,
                None,
                None,
                "pending",
                (),
                (),
                (),
                synthetic,
            )
            run = replace(run, product_variant=context.dimensions.get("product") is not None)
            try:
                cached = cache.get_raw(request, recovery_request_id=request.request_id)
                if cached is not None:
                    envelope = json.loads(cached)
                    if envelope["identity"] != json.loads(canonical_json(identity)):
                        raise DomainValidationError("raw cache identity mismatch")
                    response = RawTagResponse(
                        envelope["raw_response_json"],
                        TokenUsage(**envelope["usage"]),
                        envelope["synthetic"],
                        envelope.get("provider_response_json"),
                    )
                    run = replace(run, recovered=True)
                else:
                    call = BudgetCall(
                        tenant_id,
                        data["run_id"],
                        claim.document_version_id,
                        request.request_id,
                        1,
                        "tagger",
                        settings.model_id,
                        settings.region,
                        settings.model_sha256,
                        request.request_signature,
                        replica,
                    )
                    model_request = dict(
                        tenant_id=tenant_id,
                        claim_id=claim.claim_id,
                        packet_sha256=packet.packet_sha256,
                        replicate_id=replica,
                        request_id=request.request_id,
                        request_signature=request.request_signature,
                        binding=asdict(settings.binding),
                        model_id=settings.model_id,
                        model_profile=settings.model_profile,
                        region=settings.region,
                        system_prompt=rendered_system,
                        user_json=user_json,
                        temperature=settings.temperature,
                        max_tokens=settings.max_tokens,
                    )
                    if data.get("cf6_confirmation") is not None:
                        model_request.update(
                            cf6_confirmation=data["cf6_confirmation"],
                            cf6_analysis_policy_sha256=data["cf6_analysis_policy_sha256"],
                        )
                    try:
                        input_tokens = count(
                            "input_tokens",
                            count_input_tokens(model_request)
                            if count_input_tokens is not None
                            else token_counter(rendered_system + user_json),
                        )
                    except (ValueError, KeyError, TypeError) as error:
                        code = str(error)
                        runs.append(
                            replace(
                                run,
                                status="invalid_request",
                                errors=("TAGGING_INPUT_COUNT_INVALID",),
                                diagnostic_detail=type(error).__name__
                                + (f": {code}" if code in _SAFE_INPUT_COUNT_CODES else ""),
                            )
                        )
                        continue
                    if not reserve_budget(
                        usage_store,
                        call,
                        input_tokens=input_tokens,
                        max_output_tokens=output_reservation_tokens(
                            model_id=settings.model_id,
                            max_tokens=settings.max_tokens,
                            synthetic=settings.binding.synthetic,
                        ),
                        pricing=pricing,
                        now=now(),
                    ):
                        runs.append(run)
                        continue
                    if not usage_store.mark_dispatched(call):
                        runs.append(run)
                        continue
                    try:
                        response = invoke(model_request)
                        if not isinstance(response, RawTagResponse) or not isinstance(
                            response.usage, TokenUsage
                        ):
                            raise DomainValidationError("raw response and usage required")
                    except Exception:
                        response = RawTagResponse(
                            None,
                            TokenUsage(
                                None, None, None, None, 0, "failed", None, "MODEL_UNAVAILABLE"
                            ),
                            settings.binding.synthetic,
                        )
                    record_usage(usage_store, call, response.usage, now=now())
                    envelope = dict(
                        identity=identity,
                        raw_response_json=response.raw_response_json,
                        usage=asdict(response.usage),
                        synthetic=response.synthetic,
                        provider_response_json=response.provider_response_json,
                    )
                    cache.put_raw(request, canonical_json(envelope).encode())
            except BudgetExceeded:
                runs.append(replace(run, status="budget_exhausted", errors=("BUDGET_EXHAUSTED",)))
                continue
            except (ValueError, KeyError, TypeError):
                runs.append(replace(run, status="invalid_cache", errors=("CACHE_INVALID",)))
                continue
            run = replace(
                run,
                raw_response_json=response.raw_response_json,
                usage=response.usage,
                provider_response_json=response.provider_response_json,
            )
            if response.synthetic != settings.binding.synthetic:
                runs.append(
                    replace(run, status="invalid_response", errors=("MODEL_PROVENANCE_INVALID",))
                )
                continue
            if response.usage.status != "succeeded" or response.raw_response_json is None:
                validation_error = None
                if response.usage.status == "succeeded" and response.raw_response_json is None:
                    try:
                        provider_result = json.loads(response.provider_response_json or "null")
                    except (ValueError, TypeError):
                        provider_result = None
                    if isinstance(provider_result, dict):
                        candidate = provider_result.get("validation_error")
                        if isinstance(candidate, str) and candidate.startswith(
                            "TAGGING_EVIDENCE_ID_"
                        ):
                            validation_error = candidate
                if validation_error is not None:
                    runs.append(
                        replace(
                            run,
                            status="citation_unresolved",
                            errors=(validation_error,),
                        )
                    )
                else:
                    runs.append(replace(run, status="model_failed", errors=("MODEL_UNAVAILABLE",)))
                continue
            try:
                if len(response.raw_response_json.encode()) > settings.max_response_bytes:
                    raise DomainValidationError("response exceeds limit")
                raw_tags = llm_tags_from_dict(json.loads(response.raw_response_json))
                if (raw_tags.claim_id, raw_tags.packet_sha256, raw_tags.replicate_id) != (
                    claim.claim_id,
                    packet.packet_sha256,
                    replica,
                ):
                    raise DomainValidationError("response identity mismatch")
                ids = [element.element_id for element in raw_tags.elements]
                if len(set(ids)) != len(ids) or set(ids) != set(allowed):
                    raise DomainValidationError("response must tag every allowed element once")
            except (ValueError, TypeError, UnicodeError):
                runs.append(replace(run, status="invalid_response", errors=("LLM_SCHEMA_INVALID",)))
                continue
            elements, errors, scopes, bindings = [], [], [], []
            if (
                raw_tags.track != track.track
                or raw_tags.safe_harbor_category != track.safe_harbor_category
            ):
                errors.append("TRACK_CATEGORY_CHANGED")
            if "sentence_context" in data:
                from proofops.application.ingest.k5_context import superlative_errors

                errors.extend(
                    superlative_errors(
                        raw_tags.superlative_quote, claim.quote, sentence_interpretation
                    )
                )
            elif raw_tags.superlative_quote and raw_tags.superlative_quote not in claim.quote:
                errors.append("SUPERLATIVE_SOURCE_INVALID")
            for element in raw_tags.elements:
                model_element = element
                table_selected = False
                qt1_table_selected = baseline_selected = False
                if data.get("table_evidence_policy", {}).get("profile") in (
                    "table-selected-evidence-pb2-v1",
                    "table-selected-evidence-k4-v1",
                    "table-selected-evidence-k7-v1",
                ):
                    from proofops.application.tagging.pb2_table_evidence import (
                        OBSERVED_POLICY,
                        POLICY,
                        ROW_UNIT_POLICY,
                        prepare_element,
                    )

                    if data["table_evidence_policy"] not in (
                        POLICY,
                        ROW_UNIT_POLICY,
                        OBSERVED_POLICY,
                    ):
                        raise DomainValidationError("table evidence policy mismatch")
                    element, table_selected = prepare_element(
                        element,
                        claim,
                        original,
                        tenant_id=tenant_id,
                        policy=data["table_evidence_policy"],
                    )
                if contextual_policy is not None and not table_selected:
                    from proofops.application.tagging.qt2_context import prepare_table

                    element, table_selected = prepare_table(
                        element, claim, original, tenant_id=tenant_id
                    )
                if qt1_tuples:
                    from proofops.application.tagging.qt1_tuples import (
                        prepare_element as qt1_prepare,
                    )

                    selected_element, qt1_table_selected = qt1_prepare(model_element, qt1_tuples)
                    if qt1_table_selected:
                        element = selected_element
                    table_selected |= qt1_table_selected
                if qt1_links:
                    from proofops.application.tagging.qt1_baseline import (
                        prepare_element as baseline_prepare,
                    )

                    element, baseline_selected = baseline_prepare(element, qt1_links)
                state = element.state
                binding_reasons: list[str] = []
                if (
                    implementation_binding is not None
                    and element.element_id == "G4"
                    and state == "present"
                ):
                    from proofops.application.tagging.k9_contract import g4_complete

                    if not g4_complete(element, context, original, policy=implementation_binding):
                        state = "unknown"
                scope_reason = scope_rejection_reason(
                    element.element_id,
                    element.evidence_refs,
                    rulepack=rulepack,
                    original=original,
                    policy=element.reason_code,
                )
                if state == "present" and scope_reason:
                    state = "unknown"
                refs = []
                scope_set = set()
                if state == "present":
                    for source in element.evidence_refs:
                        if implementation_binding is not None and element.element_id != "G4":
                            from proofops.application.tagging.k9_contract import (
                                scope_definition_refs,
                            )

                            if any(
                                r.source_id == source.source_id
                                and r.char_start
                                <= source.char_start
                                < source.char_end
                                <= r.char_end
                                for r in scope_definition_refs(claim, original)
                            ):
                                state = "unknown"
                                break
                        candidate = source_candidates.get(source.source_id)
                        contained = any(
                            s.source_id == source.source_id
                            and s.char_start <= source.char_start < source.char_end <= s.char_end
                            for s in approved_refs
                        )
                        if (
                            not candidate
                            or not contained
                            or element.element_id not in candidate["allowed_elements"]
                            or candidate["source_scope"]
                            not in definitions[element.element_id]["source_scopes"]
                            and not (baseline_selected or qt1_table_selected)
                        ):
                            state = "unknown"
                            if r12_quality:
                                binding_reasons.append("evidence_catalog_rejected")
                            break
                        verified = verify_source_ref(source, original, tenant_id=tenant_id)
                        if verified.verification_state != "verified":
                            state = "unknown"
                            if r12_quality:
                                binding_reasons.append("source_unverified")
                            break
                        if (
                            not table_selected
                            and not baseline_selected
                            and not (
                                contextual_policy is not None
                                and accepts_context(
                                    context,
                                    verified,
                                    original,
                                    tenant_id=tenant_id,
                                    element_id=element.element_id,
                                    relation_tags=relation_tags_for(verified, relation_tags),
                                )
                            )
                            and not (
                                v3_policy is not None
                                and accepts_v3(
                                    context,
                                    verified,
                                    original,
                                    tenant_id=tenant_id,
                                    element_id=element.element_id,
                                    relation_tags=relation_tags_for(verified, relation_tags),
                                )
                            )
                            and accept_binding(
                                context,
                                verified,
                                relation_tags_for(verified, relation_tags),
                                original=original,
                                tenant_id=tenant_id,
                                rulepack=rulepack,
                                element_id=element.element_id,
                                local_value_identity=local_recovery is not None,
                                local_binding_policy=implementation_binding,
                                structural_policy=structural_policy,
                                allow_edge_whitespace=allow_edge_whitespace,
                                diagnostics=binding_reasons if r12_quality else None,
                            )
                            != "accepted"
                        ):
                            state = "unknown"
                            break
                        refs.append(verified)
                        if baseline_selected:
                            from proofops.domain.rules.qt1_baseline import SOURCE_SCOPE

                            scope_set.add(SOURCE_SCOPE)
                        else:
                            scope_set.add(
                                "same_table" if qt1_table_selected else candidate["source_scope"]
                            )
                    if local_recovery is not None and state == "present":
                        from proofops.application.tagging.k2_recovery import recover_value

                        element, refs = recover_value(
                            element, refs, claim, original, tenant_id=tenant_id
                        )
                    if data.get("selected_quantity_policy") is not None and state == "present":
                        from proofops.application.tagging.k4_contract import (
                            VALUE_POLICY,
                            recover_selected_quantities,
                        )

                        if data["selected_quantity_policy"] != VALUE_POLICY:
                            raise DomainValidationError("K4_VALUE_POLICY_MISMATCH")
                        element, refs = recover_selected_quantities(
                            element, refs, claim, original, tenant_id=tenant_id
                        )
                    if element.normalized_value is None and element.element_id in (
                        "G1",
                        "G2",
                        "G3",
                        "G5",
                        "P1",
                        "P2",
                    ):
                        state = "unknown"
                    if element.normalized_value is not None and not any(
                        " ".join(normalize("NFC", element.normalized_value).split())
                        == " ".join(normalize("NFC", source.quote).split())
                        for source in refs
                    ):
                        state = "unknown"
                    if element.credited_from is not None and element.credited_from not in {
                        ref.source_id for ref in refs
                    }:
                        state = "unknown"
                    # These are outputs of dedicated deterministic services, never LLM votes.
                    if element.element_id in ("P4", "P6") or not refs:
                        state = "unknown"
                elif state in ("absent", "not_applicable"):
                    state = "unknown"
                semantic_reason = None
                if semantic_policy is not None and state == "present":
                    from proofops.application.tagging.semantic_admission import guard_element

                    admitted = guard_element(
                        replace(element, evidence_refs=tuple(refs)),
                        policy=semantic_policy,
                        claim_quote=claim.quote,
                    )
                    if admitted.state != "present":
                        state, semantic_reason = admitted.state, admitted.reason_code
                if contextual_policy is not None and state == "present":
                    from proofops.application.tagging.qt2_context import guard as contextual_guard

                    admitted = contextual_guard(replace(element, evidence_refs=tuple(refs)))
                    if admitted.state != "present":
                        state, semantic_reason = admitted.state, admitted.reason_code
                if structural_policy == QA2_POLICY and state == "present":
                    from proofops.application.tagging.q1_contract import (
                        future_implementation_guard,
                    )

                    admitted = future_implementation_guard(
                        replace(element, evidence_refs=tuple(refs)),
                        claim_quote=claim.quote,
                    )
                    if admitted.state != "present":
                        state, semantic_reason = admitted.state, admitted.reason_code
                if v3_policy is not None and state == "present":
                    from proofops.application.tagging.v3_dec92 import guard as v3_guard

                    admitted = v3_guard(
                        replace(element, evidence_refs=tuple(refs)), claim_quote=claim.quote
                    )
                    if admitted.state != "present":
                        state, semantic_reason = admitted.state, admitted.reason_code
                if element.element_id == "P6" and element.state in ("present", "conflict"):
                    # Both agreement AND contradiction require the numeric service.
                    # Retain the raw vote and citations for review, never a model verdict.
                    state = "unknown"
                    errors.append("DETERMINISTIC_CHECK_REQUIRED:P6")
                if state in ("unknown", "conflict"):
                    errors.append(f"UNRESOLVED:{element.element_id}")
                    errors.extend(
                        f"UNRESOLVED:{element.element_id}:{reason}" for reason in binding_reasons
                    )
                    if scope_reason:
                        errors.append(f"{scope_reason}:{element.element_id}")
                scope = next(
                    (
                        scope
                        for scope in (
                            "qt1_maintenance_baseline_v1",
                            "global_bound",
                            "same_table",
                            "local_claim",
                        )
                        if scope in scope_set
                    ),
                    "local_claim",
                )
                scopes.append((element.element_id, scope))
                bindings.append(
                    (
                        element.element_id,
                        canonical_hash(
                            {
                                key: source.quote if source else None
                                for key, source in context.dimensions.items()
                            }
                        ),
                    )
                )
                elements.append(
                    replace(
                        element,
                        state=state,
                        evidence_refs=tuple(refs) if state == "present" else element.evidence_refs,
                        normalized_value=element.normalized_value if state == "present" else None,
                        credited_from=element.credited_from if state == "present" else None,
                        reason_code=semantic_reason or scope_reason or binding_reasons[0]
                        if (semantic_reason or scope_reason or binding_reasons)
                        and state == "unknown"
                        else element.reason_code,
                    )
                )
            guarded_tags = replace(raw_tags, elements=tuple(elements))
            run = replace(
                run,
                guarded=guarded_tags,
                status="needs_review" if errors else "succeeded",
                errors=tuple(errors),
                source_scopes=tuple(scopes),
                binding_hashes=tuple(bindings),
            )
            # Pin postprocessor, graph, rule and roles against revision overwrite.
            post_request = replace(
                request,
                request_signature=canonical_hash(
                    dict(
                        raw_request=asdict(request),
                        graph=run.graph_sha256,
                        rule=run.rule_sha256,
                        roles={
                            sid: {
                                name: asdict(ref) if ref else None for name, ref in values.items()
                            }
                            for sid, values in relation_tags.items()
                        },
                        claim_roles={
                            name: asdict(ref) if ref else None
                            for name, ref in context.dimensions.items()
                        },
                        track=track.track,
                        safe_harbor_category=track.safe_harbor_category,
                        guard_version="tagging-010-v4-numeric-origin"
                        if semantic_policy is None
                        else "tagging-010-w8-v1:" + canonical_hash(semantic_policy),
                    )
                ),
            )
            cache.put_guarded(
                post_request, canonical_json(asdict(run) | {"recovered": False}).encode()
            )
            runs.append(run)
        return runs[0]

    if max_workers == 1:
        return tuple(run_one(replica) for replica in (1, 2, 3))
    with ThreadPoolExecutor(max_workers=min(max_workers, 3)) as pool:
        return tuple(pool.map(run_one, (1, 2, 3)))
