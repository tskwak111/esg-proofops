"""Provider receipt allowlist shared by ordinary and split extraction."""

from __future__ import annotations

# Structural ports keep optional display providers outside the wire implementation.
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

if TYPE_CHECKING:
    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph


_PROVIDER_METADATA_KEYS = (
    "provider",
    "model",
    "provider_request_id",
    "provider_model",
    "input_tokens",
    "output_tokens",
    "price_snapshot",
    "cost_with_vat_reserve_usd",
    "cost_source",
    "attempts",
    "schema_valid",
    "response_sha256",
    "response_format",
    "wire_policy",
    "cached_tokens",
    "cache_write_tokens",
    "response_reuse",
    "response_request",
)


class DisplayCatalog(Protocol):
    @property
    def graph(self) -> CanonicalDocumentGraph: ...
    def element_pins(self, data: dict[str, Any]) -> dict[str, Any]: ...
    def block_pin(self, source_id: str) -> dict[str, Any]: ...
    def pin(self, ref: dict[str, Any]) -> dict[str, Any]: ...
    def restore(
        self,
        selection: str,
        original: dict[str, Any],
        pin: dict[str, Any],
        *,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def restore_preliminary(
        self, response: dict[str, Any], packet: dict[str, Any]
    ) -> dict[str, Any]: ...
    def prefetch_pages(self, pages: Iterable[int], *, max_workers: int = 1) -> None: ...


class TitleCatalog(Protocol):
    @property
    def graph(self) -> CanonicalDocumentGraph: ...
    def proof(self, source_id: str) -> dict[str, Any]: ...


class RequestBody(Protocol):
    def __call__(
        self, system: str, user: str, *, request_id: str, max_tokens: int, json_mode: bool
    ) -> dict[str, Any]: ...


class RestoreReference(Protocol):
    def __call__(
        self, selection: Any, refs: dict[str, Any], *, policy: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class DisplayCatalogOption(TypedDict, total=False):
    display_catalog: DisplayCatalog


class TitleCatalogOption(TypedDict, total=False):
    h1_title_catalog: TitleCatalog
