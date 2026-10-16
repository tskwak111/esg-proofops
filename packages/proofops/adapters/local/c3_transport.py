"""Authenticate current C3 responses against the broker ledger and raw sidecar."""

import json
import sqlite3
from pathlib import Path

from proofops.adapters.local.model_response_cache import ModelResponseCache
from proofops.application.tagging.c3_request_binding import request_binding
from proofops.domain.provenance import canonical_hash


def authenticate_response(request, response, probe):
    # Cache hits and saved projections remain usable candidates, never fresh calls.
    if "response_reuse" in response or "saved_response_origin" in response:
        return response
    binding = request_binding(request)
    body = probe.request_body(
        request["system"],
        request["user_json"],
        request_id=request["id"],
        max_tokens=request["max_tokens"],
        json_mode=True,
    )
    cache = response.get("response_request")
    if (
        response.get("request_id") != request["id"]
        or canonical_hash(body) != binding["wire_sha256"]
        or canonical_hash(probe.wire_policy) != binding["model_sha256"]
        or response.get("model_binding_sha256") != binding["model_sha256"]
        or response.get("provider") != "openai"
        or response.get("model") != body["model"]
        or response.get("provider_model") != body["model"]
        or response.get("schema_valid") is not True
        or response.get("simulated", False) is not False
        or not isinstance(cache, dict)
        or any(
            cache.get(k) != binding[k]
            for k in (
                "tenant_id",
                "source_sha256",
                "replica",
                "role",
                "wire_sha256",
                "schema_sha256",
                "analysis_policy_sha256",
            )
        )
    ):
        raise ValueError("C3_TRANSPORT_REQUEST_MISMATCH")
    with sqlite3.connect(Path(probe.ledger).as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT committed,receipt,signature FROM probe_calls WHERE request_id=?",
            (request["id"],),
        ).fetchone()
    if row is None or row[1] is None or row[2] != binding["wire_sha256"]:
        raise ValueError("C3_TRANSPORT_ORIGIN_MISMATCH")
    _, digest = ModelResponseCache._verified(
        canonical_hash(cache),
        (str(probe.ledger), request["id"], json.dumps(response), canonical_hash(response)),
    )
    last = len(response["attempts"]) - 1
    path = Path(str(probe.ledger) + ".responses") / (
        canonical_hash(f"{request['id']}:{last}") + ".json"
    )
    raw = json.loads(path.read_text())["provider_response"]
    if raw.get("id") != response["provider_request_id"] or raw.get("model") != body["model"]:
        raise ValueError("C3_TRANSPORT_ORIGIN_MISMATCH")
    return response | dict(
        transport_receipt=dict(
            schema="c3-authenticated-transport-v1",
            authenticated=True,
            fresh_model_call=True,
            replay=False,
            binding=binding,
            provider_request_id=response["provider_request_id"],
            response_sha256=canonical_hash(response),
            origin_receipt_sha256=digest,
        )
    )
