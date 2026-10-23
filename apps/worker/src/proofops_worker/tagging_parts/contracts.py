"""Typed callbacks shared by claim orchestration and source replica dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypedDict, TypeVar

from proofops.application.budget import PricingSnapshot
from proofops.application.claims import Claim
from proofops.application.evidence.binding import ClaimContext
from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
from proofops.application.tagging.contracts import RawTagResponse
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.values import SourceRef

type RelationRoles = dict[str, dict[str, SourceRef | None]]
type PreliminaryResult = tuple[TrackCandidate, ClaimContext, RelationRoles]
type PreliminarySupplier = Callable[[Claim, CanonicalDocumentGraph], PreliminaryResult | None]
ReplicaValue = TypeVar("ReplicaValue")
type ReplicaOutcome[ReplicaValue] = tuple[
    list[dict[str, Any]], list[ReplicaValue], list[str], list[str], bool
]


class TagTransport(Protocol):
    synthetic: bool

    def invoke(self, request: dict[str, Any]) -> RawTagResponse: ...
    def token_counter(self, text: str) -> int: ...


class SourceTransport(Protocol):
    def count_input_tokens(
        self, request: dict[str, Any], *, counter: Callable[[str, str], int]
    ) -> int: ...
    def may_dispatch(self) -> bool: ...
    def invoke(self, request: dict[str, Any]) -> RawTagResponse: ...


class BudgetReservation(TypedDict):
    input_tokens: int
    max_output_tokens: int
    pricing: PricingSnapshot | None
    now: int


class ConsensusOptions(TypedDict, total=False):
    require_consensus: bool


class ContextReceiptOptions(TypedDict, total=False):
    context_receipt: dict[str, Any]
