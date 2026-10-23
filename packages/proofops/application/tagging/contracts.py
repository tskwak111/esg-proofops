"""Pure settings, results and retained TagRun decoding shared by tagging callers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Protocol, TypedDict

from proofops.application.budget import TokenUsage
from proofops.application.evidence.binding import ClaimContext
from proofops.application.ports.cache import CacheNamespace, CacheRequest
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops.domain.values import ElementState, LlmTags, SourceRef, llm_tags_from_dict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from proofops.application.evidence.retrieval import EvidencePacket
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.application.tagging.analysis_scope import InventoryIndex
    from proofops.domain.rulepacks import RulePackSnapshot
    from proofops.domain.rules.engine import RuleContext


FactState = ElementState | Literal["absent_in_scope"]


class ContextAdmission(Protocol):
    def __call__(
        self,
        context: ClaimContext,
        ref: SourceRef,
        graph: CanonicalDocumentGraph,
        *,
        tenant_id: str,
        element_id: str,
        relation_tags: Mapping[str, SourceRef | None] | None = None,
    ) -> bool: ...


class CellSpec(TypedDict):
    column: int
    start: int
    end: int
    ref: SourceRef


class CacheSignatureOptions(TypedDict):
    namespace: CacheNamespace
    temperature: float
    model_id: str
    model_profile: str
    prompt_sha256: str
    schema_sha256: str
    packet_sha256: str
    tools: list[dict[str, Any]]
    max_tokens: int
    replicate_id: int
    extraction_epoch: int


class AssemblyInputs(TypedDict):
    context: ClaimContext
    graph: CanonicalDocumentGraph
    packet: EvidencePacket
    rulepack: RulePackSnapshot
    tag_revision: NotRequired[int]


class C2AssemblyInputs(AssemblyInputs):
    source_scoped_quotes: NotRequired[bool]


class ScopeInputs(TypedDict):
    runs: tuple[TagRun, ...]
    packet: EvidencePacket
    context: ClaimContext
    graph: CanonicalDocumentGraph
    rulepack: RulePackSnapshot
    rule_context: RuleContext
    inventory: InventoryIndex | dict[str, Any]
    prior_projection: NotRequired[dict[str, Any] | None]


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

    def __post_init__(self) -> None:
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

    def __post_init__(self) -> None:
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


@dataclass(frozen=True, slots=True)
class PreliminaryClassification:
    track: TrackCandidate | None
    context: ClaimContext
    track_confidence: float | None
    safe_harbor_category: str | None


def read_runs(values: Sequence[dict[str, Any]]) -> tuple[TagRun, ...]:
    """Decode retained TagRuns without relabeling responses or request identities."""

    return tuple(
        TagRun(
            **(
                r
                | dict(
                    request=CacheRequest(
                        **(
                            r["request"]
                            | dict(namespace=CacheNamespace(**r["request"]["namespace"]))
                        )
                    ),
                    usage=TokenUsage(**r["usage"]) if r["usage"] else None,
                    guarded=llm_tags_from_dict(r["guarded"]) if r["guarded"] else None,
                    errors=tuple(r["errors"]),
                    source_scopes=tuple(map(tuple, r["source_scopes"])),
                    binding_hashes=tuple(map(tuple, r["binding_hashes"])),
                )
            )
        )
        for r in values
    )
