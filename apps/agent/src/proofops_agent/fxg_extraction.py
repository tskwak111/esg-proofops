"""Opt-in bounded extraction dispatch; complete source units and immutable receipts."""

import json
from collections import Counter
from dataclasses import asdict
from uuid import UUID, uuid5

from proofops.application.claims import ExtractionOutputError
from proofops.application.ingest.fxg_wire import POLICY, before_dispatch
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json


def wire_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def plan(probe, system, user, *, max_tokens):
    """Preflight every child before dispatch; preserve complete blocks and global indexes."""
    parts = []
    parent_id = user["request_id"]

    def visit(value, path):
        if path:
            value = value | dict(
                request_id=str(
                    uuid5(UUID(parent_id), canonical_hash(dict(policy=POLICY, path=path)))
                )
            )
        try:
            probe.request_body(
                system,
                wire_json(value),
                request_id=value["request_id"],
                max_tokens=max_tokens,
                json_mode=True,
            )
        except ValueError as error:
            if str(error) != "PROBE_REQUEST_TOO_LARGE":
                raise
            data = value["untrusted_document_data"]
            # Keep parent-context indexes stable: candidate_contexts are never renumbered.
            for field in ("source_sentences", "context_blocks"):
                items = data.get(field, [])
                if len(items) > 1:
                    middle = len(items) // 2
                    for index, subset in enumerate((items[:middle], items[middle:])):
                        visit(
                            value | dict(untrusted_document_data=data | {field: subset}),
                            path + f"/{field}/{index}",
                        )
                    return
            raise ExtractionOutputError(
                "EXTRACTION_FXG_BLOCK_TOO_LARGE", failure_code="EXTRACTION_FXG_BLOCK_TOO_LARGE"
            ) from None
        parts.append(value)
        if len(parts) > POLICY["max_parts"]:
            raise ExtractionOutputError(
                "EXTRACTION_FXG_PART_LIMIT", failure_code="EXTRACTION_FXG_PART_LIMIT"
            )

    visit(user, "")
    return parts


def _save_or_check(extractor, path, value):
    content = canonical_json(value)
    if path.exists():
        if path.read_text() != content:
            raise ValueError("EXTRACTION_FXG_RECEIPT_MISMATCH")
    else:
        extractor._write(path, content)


def extract_parts(extractor, packet, system, user, parts, *, context_graph):
    """Validate each response against exactly its sent selectors before combining it."""
    root = extractor._receipts / user["request_id"]
    root.mkdir(mode=0o700, exist_ok=True)
    _save_or_check(extractor, root / "packet.json", packet)
    requests = [
        extractor._context_request_body(system, wire_json(p), p["request_id"]) for p in parts
    ]
    manifest = dict(
        policy=POLICY,
        packet_sha256=canonical_hash(packet),
        original_request=extractor._context_request_body(
            system, wire_json(user), user["request_id"]
        ),
        requests=requests,
    )
    _save_or_check(extractor, root / "fxg-split.json", manifest)
    presented, selected = Counter(), Counter()
    child_hashes = []
    data = packet["untrusted_document_data"]
    for part, request in zip(parts, requests, strict=True):
        directory = root / part["request_id"]
        if not directory.exists():
            if (root / "result.json").exists():
                raise ValueError("EXTRACTION_FXG_RECEIPT_MISMATCH")
            before_dispatch()
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            fresh = False
        else:
            fresh = True
        _save_or_check(extractor, directory / "request.json", request)
        raw_path = directory / "raw_response.json"
        allowed = [e["sentence_id"] for e in part["untrusted_document_data"]["source_sentences"]]
        failure_path = directory / "failure.json"
        if failure_path.exists():
            failure = json.loads(failure_path.read_text())
            if (
                failure.get("packet_sha256") != canonical_hash(packet)
                or failure.get("request_id") != part["request_id"]
            ):
                raise ValueError("EXTRACTION_FXG_RECEIPT_MISMATCH")
            error = failure.get("error")
            if error in {"UPSTREAM_UNAVAILABLE", "UPSTAGE_REQUEST_FAILED"}:
                raise ExtractionOutputError("PREVIOUS_TRANSPORT_FAILED")
            if not isinstance(error, str):
                raise ValueError("EXTRACTION_FXG_RECEIPT_MISMATCH")
            raise ValueError(error)
        if not fresh and not raw_path.exists():
            # A pending/billed dispatch is never guessed safe to repeat.
            raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")
        if fresh:
            from proofops.adapters.local.openrouter import OpenRouterProbe

            schema = dict(
                type="object",
                additionalProperties=False,
                required=["sentence_ids"],
                properties=dict(
                    sentence_ids=dict(
                        type="array",
                        uniqueItems=True,
                        items={"enum": allowed},
                        maxItems=len(allowed),
                    )
                ),
            )
            extractor._request_ids.append((packet["parse_manifest_id"], part["request_id"]))
            try:
                response = extractor._probe.complete(
                    system,
                    request["user_json"],
                    request_id=part["request_id"],
                    max_tokens=extractor._max_tokens,
                    json_mode=True,
                    **(
                        {"schema_json": json.dumps(schema)}
                        if isinstance(extractor._probe, OpenRouterProbe)
                        else {}
                    ),
                )
            except Exception as error:
                code = str(error) if isinstance(error, ValueError) else ""
                if code in {
                    "DUPLICATE_PROBE_REQUEST",
                    "PRICE_RECHECK_REQUIRED",
                    "BUDGET_EXHAUSTED",
                    "BUDGET_POLICY_MISMATCH",
                    "PROBE_REQUEST_TOO_LARGE",
                    "INVALID_PROBE_REQUEST",
                }:
                    extractor._request_ids.remove((packet["parse_manifest_id"], part["request_id"]))
                extractor._fail(
                    directory, canonical_hash(packet), part["request_id"], code, transport=True
                )
            from proofops_agent.upstage_extraction import _PROVIDER_METADATA_KEYS

            response = (
                {k: response[k] for k in (*_PROVIDER_METADATA_KEYS, "content") if k in response}
                if isinstance(response, dict)
                else {"invalid_transport_type": type(response).__name__}
            )
            extractor._write(raw_path, canonical_json(response))
        response = json.loads(raw_path.read_text())
        try:
            if not isinstance(response, dict) or response.get("schema_valid") is False:
                raise ValueError("invalid schema")
            payload = json.loads(response["content"])
            if not isinstance(payload, dict):
                raise ValueError("invalid object")
            ids = payload.get("sentence_ids")
            if (
                set(payload) != {"sentence_ids"}
                or not isinstance(ids, list)
                or any(not isinstance(i, str) or i not in allowed for i in ids)
                or len(set(ids)) != len(ids)
            ):
                raise ValueError("chunk selector invalid")
            spans, diagnostics = extractor._resolve_payload(
                payload,
                data["text"],
                data["source_id"],
                packet.get("display_text"),
                packet=packet,
                context_graph=context_graph,
            )
        except (KeyError, TypeError, ValueError):
            raise ExtractionOutputError(
                "EXTRACTION_FXG_CHUNK_INVALID", failure_code="EXTRACTION_FXG_CHUNK_INVALID"
            ) from None
        result = dict(
            request_sha256=canonical_hash(request),
            response_sha256=canonical_hash(response),
            spans=[asdict(s) for s in spans],
            diagnostics=diagnostics,
        )
        _save_or_check(extractor, directory / "result.json", result)
        child_hashes.append(canonical_hash(result))
        presented.update(allowed)
        selected.update(ids)
    payload = dict(
        sentence_ids=[
            e["sentence_id"]
            for e in user["untrusted_document_data"]["source_sentences"]
            if selected[e["sentence_id"]] == presented[e["sentence_id"]]
            and presented[e["sentence_id"]] > 0
        ]
    )
    spans, diagnostics = extractor._resolve_payload(
        payload,
        data["text"],
        data["source_id"],
        packet.get("display_text"),
        packet=packet,
        context_graph=context_graph,
    )
    # A context-dependent selection that changes between views stays unknown.
    diagnostics = diagnostics | dict(
        fxg_context_disagreements=[
            e["sentence_id"]
            for e in user["untrusted_document_data"]["source_sentences"]
            if 0 < selected[e["sentence_id"]] < presented[e["sentence_id"]]
        ]
    )
    result = dict(spans=[asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans])
    _save_or_check(
        extractor,
        root / "result.json",
        dict(
            **result,
            profile=asdict(extractor.profile),
            packet_sha256=canonical_hash(packet),
            split_sha256=canonical_hash(manifest),
            child_result_sha256=child_hashes,
            diagnostics=diagnostics,
        ),
    )
    return result
