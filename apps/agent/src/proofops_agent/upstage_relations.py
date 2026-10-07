"""Versioned Upstage transport for literal source-role relation tagging."""

from __future__ import annotations

import json

from proofops.application.preflight import Preflight
from proofops.application.tagging.relations import (
    OCCURRENCE_PROFILE,
    OCCURRENCE_SCHEMA,
    OCCURRENCE_SYSTEM_PROMPT,
    SCHEMA,
    SYSTEM_PROMPT,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import _require_sha256, _require_uuid

from proofops_agent.upstage_tagging import UpstageTaggingTransport

MODEL_PROFILE = "upstage-relation-source-quotes-v1"
TRANSPORT_VERSION = "relation-source-quotes-v1"

_ENVELOPE_KEYS = frozenset(
    (
        "schema",
        "tenant_id",
        "claim_id",
        "graph_sha256",
        "sources_sha256",
        "retrieval_packet_sha256",
        "prompt_sha256",
        "untrusted_document_data",
    )
)


class UpstageRelationsTransport(UpstageTaggingTransport):
    """Literal relation transport; inherited receipts preserve raw relations."""

    MODEL_PROFILE = MODEL_PROFILE
    TRANSPORT_VERSION = TRANSPORT_VERSION
    SCHEMA = SCHEMA
    SYSTEM_PROMPT = SYSTEM_PROMPT

    def _wire_request(self, request: dict) -> tuple[str, str, dict[str, dict], Preflight, str]:
        settings = self._settings
        if settings.system_prompt != self.SYSTEM_PROMPT:
            raise ValueError("UPSTAGE_RELATIONS_PROMPT_INVALID")
        authorization = self._authorize_request(request)
        system = request.get("system_prompt")
        if not isinstance(system, str) or system != settings.rendered_system:
            raise ValueError("UPSTAGE_RELATIONS_SYSTEM_REQUIRED")
        try:
            user = json.loads(request["user_json"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("UPSTAGE_RELATIONS_PACKET_INVALID") from None
        if (
            not isinstance(user, dict)
            or set(user) != _ENVELOPE_KEYS
            or user["schema"] != self.SCHEMA
        ):
            raise ValueError("UPSTAGE_RELATIONS_PACKET_INVALID")
        if (
            user.get("tenant_id") != request["tenant_id"]
            or user.get("claim_id") != request.get("claim_id")
            or user.get("retrieval_packet_sha256") != request.get("retrieval_packet_sha256")
            or user.get("prompt_sha256") != canonical_hash(self.SYSTEM_PROMPT)
        ):
            raise ValueError("UPSTAGE_RELATIONS_PACKET_MISMATCH")
        try:
            _require_uuid("tenant_id", user["tenant_id"])
            _require_uuid("claim_id", user["claim_id"])
            for name in (
                "graph_sha256",
                "sources_sha256",
                "retrieval_packet_sha256",
                "prompt_sha256",
            ):
                _require_sha256(name, user[name])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("UPSTAGE_RELATIONS_PACKET_INVALID") from None
        if request.get("packet_sha256") != canonical_hash(user):
            raise ValueError("UPSTAGE_RELATIONS_PACKET_MISMATCH")
        data = user["untrusted_document_data"]
        if not isinstance(data, dict) or set(data) != {"sources"}:
            raise ValueError("UPSTAGE_RELATIONS_SOURCES_REQUIRED")
        sources = data["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError("UPSTAGE_RELATIONS_SOURCES_REQUIRED")
        for index, source in enumerate(sources):
            if (
                not isinstance(source, dict)
                or set(source) != self._source_fields()
                or type(source["source_index"]) is not int
                or source["source_index"] != index
                or not isinstance(source["text"], str)
                or not source["text"]
            ):
                raise ValueError("UPSTAGE_RELATIONS_SOURCES_REQUIRED")
            self._validate_occurrences(source)
        return (
            system,
            json.dumps(user, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            {},
            authorization,
            settings.schema_json,
        )

    def _source_fields(self) -> set[str]:
        return {"source_index", "text"}

    def _validate_occurrences(self, source: dict) -> None:
        pass  # Legacy wire has no occurrence catalog.


class UpstageOccurrenceRelationsTransport(UpstageRelationsTransport):
    """Explicit opt-in; raw ID responses and v2 receipt pins stay immutable."""

    MODEL_PROFILE = OCCURRENCE_PROFILE
    TRANSPORT_VERSION = "relation-occurrence-selection-v2"
    SCHEMA = OCCURRENCE_SCHEMA
    SYSTEM_PROMPT = OCCURRENCE_SYSTEM_PROMPT

    def _source_fields(self) -> set[str]:
        return {"source_index", "source_id", "text", "occurrences"}

    def _validate_occurrences(self, source: dict) -> None:
        try:
            _require_uuid("source_id", source["source_id"])
            candidates = source["occurrences"]
            if not isinstance(candidates, list) or len(candidates) > 4096:
                raise ValueError
            seen = set()
            for candidate in candidates:
                if not isinstance(candidate, dict) or set(candidate) != {
                    "span_id",
                    "quote",
                    "start",
                    "end",
                }:
                    raise ValueError
                _require_sha256("span_id", candidate["span_id"])
                start, end = candidate["start"], candidate["end"]
                if (
                    candidate["span_id"] in seen
                    or type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= len(source["text"])
                    or candidate["quote"] != source["text"][start:end]
                ):
                    raise ValueError
                seen.add(candidate["span_id"])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("UPSTAGE_RELATIONS_OCCURRENCES_INVALID") from None
