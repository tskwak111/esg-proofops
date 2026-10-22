"""Conditional immutable cache adapter (TASK-033).

The injected client maps to DynamoDB conditional metadata plus immutable S3
objects in production.  The supplied in-memory client is local contract-test
only; this module has no AWS SDK or network dependency.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from proofops.application.ports.cache import (
    CacheCollisionError as CacheCollisionError,
)
from proofops.application.ports.cache import (
    CacheCorruptionError as CacheCorruptionError,
)
from proofops.application.ports.cache import (
    CacheNamespace as CacheNamespace,
)
from proofops.application.ports.cache import (
    CacheRequest as CacheRequest,
)
from proofops.application.ports.cache import (
    CacheRevokedError as CacheRevokedError,
)
from proofops.application.ports.cache import (
    cache_request as cache_request,
)
from proofops.domain.errors import DomainValidationError
from proofops.domain.values import _require_sha256, _require_uuid


@dataclass(frozen=True, slots=True)
class StoredCacheObject:
    payload: bytes
    payload_sha256: str


class ImmutableCacheClient(Protocol):
    """Small conditional-write/blob boundary for DynamoDB+S3-style adapters."""

    def put_if_absent(self, key: str, value: StoredCacheObject) -> bool: ...

    def get(self, key: str) -> StoredCacheObject | None: ...

    def delete(self, key: str) -> None: ...


class InMemoryImmutableCacheClient:
    """Local contract-test client; process-local and never production-capable."""

    kind = "local-contract-test-only"

    def __init__(self) -> None:
        self._objects: dict[str, StoredCacheObject] = {}

    def put_if_absent(self, key: str, value: StoredCacheObject) -> bool:
        if key in self._objects:
            return False
        self._objects[key] = value
        return True

    def get(self, key: str) -> StoredCacheObject | None:
        return self._objects.get(key)

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def corrupt_for_test(self, key: str, payload: bytes) -> None:
        """Contract-test fault injection; production clients do not expose this."""
        existing = self._objects[key]
        self._objects[key] = StoredCacheObject(payload, existing.payload_sha256)


class ImmutableResponseCache:
    """Raw, guarded, and decision artifacts with conditional immutable writes.

    The in-process manifest enables contract tests and documents the required
    source revocation lookup. A real multi-worker implementation still needs
    DynamoDB manifest transactions, lease/fencing, and S3 versioning.
    """

    def __init__(self, client: ImmutableCacheClient) -> None:
        self._client = client
        self._manifest: dict[CacheNamespace, set[str]] = {}
        self._revoked: set[CacheNamespace] = set()

    def raw_storage_key(self, request: CacheRequest) -> str:
        return self._storage_key("RAW", request)

    def _storage_key(
        self,
        kind: str,
        request: CacheRequest,
        decision_semantic_hash: str | None = None,
    ) -> str:
        suffix = f"#{decision_semantic_hash}" if decision_semantic_hash else ""
        recovery = f"#REQ#{request.request_id}" if kind == "RAW" else ""
        return (
            f"{request.namespace.partition_key}#{kind}#{request.request_signature}"
            f"#REPLICA#{request.replicate_id}#EPOCH#{request.extraction_epoch}{recovery}{suffix}"
        )

    @staticmethod
    def _stored(payload: bytes) -> StoredCacheObject:
        if not isinstance(payload, bytes):
            raise DomainValidationError("cache payload must be bytes")
        return StoredCacheObject(payload, hashlib.sha256(payload).hexdigest())

    @staticmethod
    def _verified(value: StoredCacheObject) -> bytes:
        if hashlib.sha256(value.payload).hexdigest() != value.payload_sha256:
            raise CacheCorruptionError("cache payload hash mismatch")
        return value.payload

    def _assert_not_revoked(self, namespace: CacheNamespace) -> None:
        if namespace in self._revoked:
            raise CacheRevokedError("cache namespace has been revoked")

    def _put(
        self, kind: str, request: CacheRequest, payload: bytes, decision_hash: str | None = None
    ) -> None:
        self._assert_not_revoked(request.namespace)
        key = self._storage_key(kind, request, decision_hash)
        candidate = self._stored(payload)
        if self._client.put_if_absent(key, candidate):
            self._manifest.setdefault(request.namespace, set()).add(key)
            return
        existing = self._client.get(key)
        if existing is None:
            raise CacheCollisionError("conditional cache write lost without a readable object")
        self._verified(existing)
        if existing.payload_sha256 != candidate.payload_sha256:
            raise CacheCollisionError("immutable cache key already has different content")
        self._manifest.setdefault(request.namespace, set()).add(key)

    def _get(
        self, kind: str, request: CacheRequest, decision_hash: str | None = None
    ) -> bytes | None:
        if request.namespace in self._revoked:
            return None
        value = self._client.get(self._storage_key(kind, request, decision_hash))
        return None if value is None else self._verified(value)

    def put_raw(self, request: CacheRequest, payload: bytes) -> None:
        self._put("RAW", request, payload)

    def get_raw(self, request: CacheRequest, *, recovery_request_id: str) -> bytes | None:
        _require_uuid("recovery_request_id", recovery_request_id)
        if recovery_request_id != request.request_id:
            raise DomainValidationError("raw cache reads require the same request_id recovery")
        return self._get("RAW", request)

    def put_guarded(self, request: CacheRequest, payload: bytes) -> None:
        self._put("GUARDED", request, payload)

    def get_guarded(self, request: CacheRequest) -> bytes | None:
        return self._get("GUARDED", request)

    def put_decision(
        self, request: CacheRequest, *, decision_semantic_hash: str, payload: bytes
    ) -> None:
        _require_sha256("decision_semantic_hash", decision_semantic_hash)
        self._put("DECISION", request, payload, decision_semantic_hash)

    def get_decision(self, request: CacheRequest, *, decision_semantic_hash: str) -> bytes | None:
        _require_sha256("decision_semantic_hash", decision_semantic_hash)
        return self._get("DECISION", request, decision_semantic_hash)

    def revoke_document(self, namespace: CacheNamespace) -> None:
        """Delete all locally manifested source cache entries and prevent reuse."""
        self._revoked.add(namespace)
        for key in self._manifest.pop(namespace, set()):
            self._client.delete(key)
