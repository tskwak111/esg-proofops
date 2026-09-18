"""Bounded preliminary transport over the paid-transport safeguards; no paid calls here.

A subclass of UpstageTaggingTransport that sends only the trusted
preliminary_request envelope (application/tagging/preliminary) as literal
Unicode JSON. It never approves source quality and never computes domain
grades or labels: the trusted composer must build the packet from
preliminary_request and authorize the actual source. Locks, stop/incomplete
fences, exclusive receipt directories, the shared probe ledger, raw receipts
and authorization are all inherited unchanged.
"""

from __future__ import annotations

import json

from proofops.application.preflight import Preflight
from proofops.application.tagging.preliminary import SCHEMA, SYSTEM_PROMPT
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import _require_sha256, _require_uuid

from proofops_agent.upstage_tagging import UpstageTaggingTransport

MODEL_PROFILE = "upstage-preliminary-source-quotes-v1"
TRANSPORT_VERSION = "preliminary-source-quotes-v1"

_ENVELOPE_KEYS = frozenset(
    (
        "schema",
        "tenant_id",
        "claim_id",
        "claim_sha256",
        "graph_sha256",
        "prompt_sha256",
        "untrusted_document_data",
    )
)


class UpstagePreliminaryTransport(UpstageTaggingTransport):
    """Preliminary source-quotes transport; wire contract only, no grading."""

    MODEL_PROFILE = MODEL_PROFILE
    TRANSPORT_VERSION = TRANSPORT_VERSION

    def _wire_request(self, request: dict) -> tuple[str, str, dict[str, dict], Preflight]:
        settings = self._settings
        # Mandatory callback plus common tenant/claim/request UUID, packet/
        # signature SHA, settings/binding/model/region/temperature/replica/
        # output-cap validation; raises before any spend on failure.
        authorization = self._authorize_request(request)
        if settings.system_prompt != SYSTEM_PROMPT:
            raise ValueError("UPSTAGE_PRELIMINARY_PROMPT_INVALID")
        system = request.get("system_prompt")
        if not isinstance(system, str) or system != settings.rendered_system:
            raise ValueError("UPSTAGE_PRELIMINARY_SYSTEM_REQUIRED")
        try:
            user = json.loads(request["user_json"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("UPSTAGE_PRELIMINARY_PACKET_INVALID") from None
        if not isinstance(user, dict) or set(user) != _ENVELOPE_KEYS:
            raise ValueError("UPSTAGE_PRELIMINARY_PACKET_INVALID")
        if user["schema"] != SCHEMA:
            raise ValueError("UPSTAGE_PRELIMINARY_PACKET_INVALID")
        if user.get("prompt_sha256") != canonical_hash(SYSTEM_PROMPT):
            raise ValueError("UPSTAGE_PRELIMINARY_PROMPT_INVALID")
        if user.get("tenant_id") != request["tenant_id"] or user.get("claim_id") != request.get(
            "claim_id"
        ):
            raise ValueError("UPSTAGE_PRELIMINARY_PACKET_MISMATCH")
        try:
            _require_uuid("tenant_id", user["tenant_id"])
            _require_uuid("claim_id", user["claim_id"])
            for name in ("claim_sha256", "graph_sha256", "prompt_sha256"):
                _require_sha256(name, user[name])
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("UPSTAGE_PRELIMINARY_PACKET_INVALID") from None
        if request.get("packet_sha256") != canonical_hash(user):
            raise ValueError("UPSTAGE_PRELIMINARY_PACKET_MISMATCH")
        data = user["untrusted_document_data"]
        if not isinstance(data, dict) or set(data) != {"sources"}:
            raise ValueError("UPSTAGE_PRELIMINARY_SOURCES_REQUIRED")
        sources = data["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError("UPSTAGE_PRELIMINARY_SOURCES_REQUIRED")
        for index, entry in enumerate(sources):
            if (
                not isinstance(entry, dict)
                or set(entry) != {"source_index", "text"}
                or type(entry["source_index"]) is not int
                or entry["source_index"] != index
                or not isinstance(entry["text"], str)
                or not entry["text"]
            ):
                raise ValueError("UPSTAGE_PRELIMINARY_SOURCES_REQUIRED")
        wire_user = json.dumps(user, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return system, wire_user, {}, authorization
