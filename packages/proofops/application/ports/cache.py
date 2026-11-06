"""Immutable cache identity and the minimal tagging cache port; no adapter I/O."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash, request_signature
from proofops.domain.values import _require_sha256, _require_strict_int, _require_uuid


class CacheCollisionError(DomainValidationError):
    """A conditional immutable write found different existing content."""


class CacheCorruptionError(DomainValidationError):
    """Stored payload bytes do not match their immutable digest."""


class CacheRevokedError(DomainValidationError):
    """A consent-revoked document namespace cannot accept new cache data."""


@dataclass(frozen=True, slots=True)
class CacheNamespace:
    """Required cache boundary: tenant + consent + document version + role."""

    tenant_id: str
    consent_profile: str
    document_version_id: str
    role: str

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        _require_uuid("document_version_id", self.document_version_id)
        for name in ("consent_profile", "role"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise DomainValidationError(f"{name} must be a non-empty string")

    @property
    def partition_key(self) -> str:
        return "CACHE#" + canonical_hash(
            [self.tenant_id, self.consent_profile, self.document_version_id, self.role]
        )


@dataclass(frozen=True, slots=True)
class CacheRequest:
    """One retryable model request; replica is bound in its request signature."""

    namespace: CacheNamespace
    request_id: str
    request_signature: str
    replicate_id: int
    extraction_epoch: int

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, CacheNamespace):
            raise DomainValidationError("namespace must be CacheNamespace")
        _require_uuid("request_id", self.request_id)
        _require_sha256("request_signature", self.request_signature)
        if _require_strict_int("replicate_id", self.replicate_id) not in (1, 2, 3):
            raise DomainValidationError("replicate_id must be 1, 2, or 3")
        if _require_strict_int("extraction_epoch", self.extraction_epoch) < 1:
            raise DomainValidationError("extraction_epoch must be positive")


def cache_request(
    *,
    namespace: CacheNamespace,
    request_id: str,
    temperature: float,
    model_id: str,
    model_profile: str,
    prompt_sha256: str,
    schema_sha256: str,
    packet_sha256: str,
    tools: Sequence[dict[str, Any]],
    max_tokens: int,
    replicate_id: int,
    extraction_epoch: int,
) -> CacheRequest:
    """Create a fully-bound request identity from a pre-authorized namespace."""
    return CacheRequest(
        namespace=namespace,
        request_id=request_id,
        request_signature=request_signature(
            temperature=temperature,
            model_id=model_id,
            model_profile=model_profile,
            prompt_sha256=prompt_sha256,
            schema_sha256=schema_sha256,
            packet_sha256=packet_sha256,
            tools=tools,
            max_tokens=max_tokens,
            replicate_id=replicate_id,
            extraction_epoch=extraction_epoch,
        ),
        replicate_id=replicate_id,
        extraction_epoch=extraction_epoch,
    )


class TaggingCache(Protocol):
    """Only the operations needed by independent element replicas."""

    def get_raw(self, request: CacheRequest, *, recovery_request_id: str) -> bytes | None: ...

    def put_raw(self, request: CacheRequest, payload: bytes) -> None: ...

    def put_guarded(self, request: CacheRequest, payload: bytes) -> None: ...
