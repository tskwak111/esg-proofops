"""SC1 wire over the existing authorized, fenced, immutable tagging transport."""

import json
from dataclasses import replace

from proofops.application.tagging.i24_inventory import SCHEMA, WIRE_PROMPT, transport_request
from proofops.domain.rulepacks import canonical_json

from proofops_agent.upstage_tagging import UpstageTaggingTransport


class SC1InventoryTransport(UpstageTaggingTransport):
    TRANSPORT_VERSION = "sc1-inventory-hosted-i24-v1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TRANSPORT_VERSION = "sc1-inventory-hosted-i24-v1"

    def _wire_request(self, request):
        authorization = self._authorize_request(request)
        original = json.loads(request["user_json"])
        if request != transport_request(original, self._settings):
            raise ValueError("SC1_TRANSPORT_REQUEST_MISMATCH")
        from proofops.application.tagging.cf1_inventory import enabled as cf1_enabled
        from proofops.application.tagging.cf1_inventory import wire_request

        if cf1_enabled(original["untrusted_document_data"]["selection"]):
            system, user, schema = wire_request(original)
            return system, user, {"cf1": True}, authorization, schema
        # Send only the exact text offsets and IDs; full original geometry and
        # provenance stay in the authenticated request receipt, not token overhead.
        chunk = original["untrusted_document_data"]
        wire = original | dict(
            untrusted_document_data=chunk
            | dict(
                spans=[
                    dict(
                        kind=s["kind"],
                        source_ref={
                            k: s["source_ref"][k]
                            for k in ("source_id", "char_start", "char_end", "quote")
                        },
                    )
                    for s in chunk["spans"]
                ]
            )
        )
        return (
            WIRE_PROMPT,
            canonical_json(wire),
            {},
            authorization,
            canonical_json(SCHEMA),
        )

    def restore_payload(self, payload, refs, *, policy=None):
        from jsonschema import Draft202012Validator
        from proofops.application.tagging.cf1_inventory import SCHEMA as CF1_SCHEMA

        schema = CF1_SCHEMA if refs.get("cf1") else SCHEMA
        if not Draft202012Validator(schema).is_valid(payload):
            raise ValueError("SC1_RESPONSE_SCHEMA_INVALID")
        return payload

    def _response_metadata(self, response):
        from proofops.adapters.local.i27_inventory_execution import current

        request = current.get()
        if request is None or not request["attempts"]:
            return response
        request["degraded"] = bool(request["terminal_code"] and response.usage.status == "failed")
        return replace(
            response,
            provider_response_json=canonical_json(
                json.loads(response.provider_response_json or "{}") | dict(i27_sc1_failure=request)
            ),
        )
