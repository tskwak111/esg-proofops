"""Immutable receipt replay, sanitized failures, and retained truncation proofs.

Look up the public module at call time so historical monkeypatch hooks still
control both live failure handling and replay, without an import cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from proofops_agent.extraction_parts.contracts import DisplayCatalog

if TYPE_CHECKING:
    from proofops_agent.upstage_extraction import UpstageClaimExtractor


def _replay_receipt(
    self: UpstageClaimExtractor,
    directory: Path,
    packet: dict[str, Any],
    packet_sha: str,
    request_id: str,
    context_graph: Any = None,
    display_catalog: DisplayCatalog | None = None,
    expected_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reuse an existing receipt for this exact packet; never re-issue its call.

    A retained receipt means the provider request for this packet was already
    made, so repeating it could be charged twice. The stored packet must be
    byte-identical to this one and its profile must match before anything is
    reused; otherwise the old refusal stands. In order:

    * ``failure.json`` -- the stored failure is raised again, deterministically;
    * ``raw_response.json`` -- required for any model result (missing raw cannot
      claim a model result); quotes are always reconstructed and validated from
      raw provider content;
    * ``result.json`` -- if present, must match identity and equal the
      reconstructed validated spans identically; a forged or mismatched result
      is refused;
    * nothing retained -- raises ``EXTRACTION_RECEIPT_UNSETTLED`` and leaves
      reconciliation to the ledger instead of guessing.

    No provider call, reservation or usage entry is created on this path.
    In context mode the graph is required again and the stored request is
    byte-compared against the recomputed wire first: a changed context
    addresses a different receipt directory already, and any tampering
    with the stored request fails closed here.
    """
    from proofops_agent import upstage_extraction as facade

    text = self._packet_text(packet)
    if self._display_text_profile:
        request_path = directory / "request.json"
        if (
            expected_body is None
            or not request_path.is_file()
            or request_path.read_text(encoding="utf-8") != facade.canonical_json(expected_body)
        ):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
    if self._source_ids:
        self._require_graph(packet, context_graph)
        system_prompt, user_data, recomputed_id = self._source_id_wire(
            packet, text, packet_sha, context_graph, display_catalog
        )
        if recomputed_id != request_id:
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        user_json = facade.json.dumps(
            user_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        expected_body = self._context_request_body(system_prompt, user_json, request_id)
        request_path = directory / "request.json"
        if not request_path.is_file() or request_path.read_text(
            encoding="utf-8"
        ) != facade.canonical_json(expected_body):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
    elif self._context:
        if context_graph is None:
            raise ValueError("EXTRACTION_CONTEXT_REQUIRED")
        self._validate_context_graph(packet, context_graph)
        system_prompt, user_data, recomputed_id = self._context_wire(
            packet, text, packet_sha, context_graph, display_catalog
        )
        if recomputed_id != request_id:
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        user_json = facade.json.dumps(
            user_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        expected_body = self._context_request_body(system_prompt, user_json, request_id)
        request_path = directory / "request.json"
        if not request_path.is_file() or request_path.read_text(
            encoding="utf-8"
        ) != facade.canonical_json(expected_body):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
    elif context_graph is not None and not self._display_text_profile:
        raise ValueError("EXTRACTION_CONTEXT_UNEXPECTED")
    failure_path = directory / "failure.json"
    if failure_path.is_file():
        stored = facade.json.loads(failure_path.read_text(encoding="utf-8"))
        if stored.get("packet_sha256") != packet_sha or (
            (self._context or self._source_ids) and stored.get("request_id") != request_id
        ):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        error = stored.get("error")
        from proofops.application.provider_resilience import ISOLATED_CODES

        if getattr(self._probe, "provider_resilience", None) and error in ISOLATED_CODES:
            raise facade.ExtractionOutputError(error)
        if error in {"UPSTAGE_REQUEST_FAILED", "UPSTREAM_UNAVAILABLE"}:
            # A fresh network failure still stops its batch in _fail. On an
            # explicit continuation, retain this source as failed/unknown
            # without repeating its possibly billed call or halting every
            # later source. Budget/auth/integrity stops remain unchanged.
            raise facade.ExtractionOutputError(
                "PREVIOUS_TRANSPORT_FAILED",
                failure_code=(
                    stored.get("reason_code") or error if self._failure_diagnostics else None
                ),
            )
        if error in facade.UPSTAGE_TRANSPORT_STOP_CODES:
            if self._recorded_truncation(directory, request_id, error):
                raise facade.ExtractionOutputError("MODEL_OUTPUT_TRUNCATED")
            raise ValueError(error)
        raise facade.ExtractionOutputError(
            error or "MODEL_SPAN_OR_SCHEMA_INVALID",
            failure_code=(stored.get("reason_code") if self._failure_diagnostics else None),
        )

    # Missing raw cannot claim model result
    raw_path = directory / "raw_response.json"
    if not raw_path.is_file():
        raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")

    # Validate packet and request identity in both raw/result paths
    stored_packet = directory / "packet.json"
    if not stored_packet.is_file() or stored_packet.read_text(
        encoding="utf-8"
    ) != facade.canonical_json(packet):
        raise ValueError("EXTRACTION_RECEIPT_EXISTS")

    request_path = directory / "request.json"
    if not request_path.is_file():
        raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")
    try:
        stored_req = facade.json.loads(request_path.read_text(encoding="utf-8"))
        if stored_req.get("request_id") != request_id:
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
    except (ValueError, UnicodeDecodeError):
        raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")

    try:
        metadata = facade.json.loads(raw_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("content"), str):
        raise ValueError("EXTRACTION_RECEIPT_UNSETTLED")

    # Reconstruct and validate spans strictly from the raw model response
    text = self._packet_text(packet)
    try:
        payload = facade.json.loads(metadata["content"])
        spans, rejected = self._resolve_payload(
            payload,
            text,
            packet["untrusted_document_data"]["source_id"],
            packet.get("display_text"),
            packet=packet,
            context_graph=context_graph,
        )
    except (ValueError, TypeError, KeyError, facade.json.JSONDecodeError):
        raise facade.ExtractionOutputError("MODEL_SPAN_OR_SCHEMA_INVALID") from None

    resolved = [
        {
            "char_start": span.char_start,
            "char_end": span.char_end,
            "quote": span.quote,
            "kind": span.kind,
            "reason": span.reason,
            "topic_ids": list(span.topic_ids),
        }
        for span in spans
    ]

    result_path = directory / "result.json"
    if result_path.is_file():
        try:
            stored_result = facade.json.loads(result_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        if (
            stored_result.get("request_id") != request_id
            or stored_result.get("packet_sha256") != packet_sha
            or stored_result.get("profile") != facade.asdict(self._profile)
            or (
                self._position_order
                and stored_result.get("context_ordering") != self._context_order_policy()
            )
            or (
                self._j3
                and any(
                    stored_result.get(key) != rejected.get(key)
                    for key in (
                        ("j7_refinements", "j7_refinement_rejected")
                        if self._j7
                        else ("j3_refinements", "j3_refinement_rejected")
                    )
                )
            )
            or not isinstance(stored_result.get("spans"), list)
            or stored_result.get("spans") != resolved
        ):
            raise ValueError("EXTRACTION_RECEIPT_EXISTS")
        return {"spans": resolved}

    try:
        self._write(
            directory / "result.json",
            facade.canonical_json(
                {
                    "request_id": request_id,
                    "packet_sha256": packet_sha,
                    "profile": facade.asdict(self._profile),
                    "provider_model": metadata.get("provider_model"),
                    "response_sha256": metadata.get("response_sha256"),
                    "content_sha256": facade.canonical_hash(metadata["content"]),
                    "spans": resolved,
                    **rejected,
                    **(
                        {"context_ordering": self._context_order_policy()}
                        if self._position_order
                        else {}
                    ),
                }
            ),
        )
    except FileExistsError:
        pass
    return {"spans": resolved}


def _write(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    path.chmod(0o400)


def _fail(
    self: UpstageClaimExtractor,
    directory: Path,
    packet_sha: str,
    request_id: str,
    code: str,
    *,
    transport: bool = False,
) -> NoReturn:
    from proofops_agent import upstage_extraction as facade

    if transport:
        error = code if code in facade.UPSTAGE_TRANSPORT_STOP_CODES else "UPSTREAM_UNAVAILABLE"
        from proofops.application.provider_resilience import ISOLATED_CODES

        if getattr(self._probe, "provider_resilience", None) and code in ISOLATED_CODES:
            error = code
    else:
        error = "MODEL_SPAN_OR_SCHEMA_INVALID"
    self._write(
        directory / "failure.json",
        facade.canonical_json(
            {"request_id": request_id, "packet_sha256": packet_sha, "error": error}
            | (
                {"reason_code": code}
                if (self._located_table_context or self._failure_diagnostics)
                and not transport
                and code
                in {
                    "MODEL_JSON_INVALID",
                    "MODEL_SCHEMA_INVALID",
                    "MODEL_SELECTOR_INVALID",
                    "MODEL_SPAN_INVALID",
                }
                else {}
            )
        ),
    )
    if transport:
        if getattr(self._probe, "provider_resilience", None) and code in ISOLATED_CODES:
            raise facade.ExtractionOutputError(
                error, failure_code=code if self._failure_diagnostics else None
            )
        if self._recorded_truncation(directory, request_id, error):
            raise facade.ExtractionOutputError(
                "MODEL_OUTPUT_TRUNCATED",
                failure_code=code if self._failure_diagnostics else None,
            )
        raise ValueError(error)
    raise facade.ExtractionOutputError(
        error, failure_code=code if self._failure_diagnostics else None
    )


def _recorded_truncation(
    self: UpstageClaimExtractor, directory: Path, request_id: str, error: str
) -> bool:
    from proofops_agent import upstage_extraction as facade

    if error != "UPSTAGE_RECEIPT_INVALID_RESERVATION_RETAINED":
        return False
    check = getattr(self._probe, "is_recorded_output_truncation", None)
    if check is None:
        return False
    try:
        request = facade.json.loads((directory / "request.json").read_text())
        return check(request, request_id=request_id) is True
    except (OSError, ValueError, TypeError):
        return False
