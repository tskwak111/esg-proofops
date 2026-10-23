"""OpenAI wire encoding, bounded HTTP I/O and private diagnostic sidecars.

Read patchable runtime names through the public adapter module. Price checks,
reservations and settlement remain owned by OpenAIProbe.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.openai_connections import OpenAIConnections


def request_body(
    self: OpenAIProbe,
    system: str,
    user_json: str,
    *,
    request_id: str,
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> dict[str, Any]:
    from proofops.adapters.local import openai as api

    if (
        not isinstance(system, str)
        or not isinstance(user_json, str)
        or not isinstance(request_id, str)
        or not 1 <= len(request_id) <= 128
        or type(max_tokens) is not int
        or not 1 <= max_tokens <= 4096
        or type(json_mode) is not bool
    ):
        raise ValueError("INVALID_PROBE_REQUEST")
    body: dict[str, Any] = {
        "model": api.MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_json},
        ],
        "max_completion_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
        "reasoning_effort": "none",
        "store": False,
        "service_tier": "default",
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if self.response_policy is not None:
        body["top_p"] = 1
    if (
        len(api.json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
        > self.max_request_bytes
    ):
        raise ValueError("PROBE_REQUEST_TOO_LARGE")
    return body


def _record_http_error(
    self: OpenAIProbe,
    body: dict[str, Any],
    status: int | None,
    raw: bytes,
    error: object,
    request_id: str | None,
    retry_after: str | None,
    *,
    client_request_id: str | None = None,
    headers: Mapping[str, str | None] | None = None,
    latency_ms: float | None = None,
    response_failure: dict[str, Any] | None = None,
    transport_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep denial identifiers without persisting messages, inputs or cookies."""
    from proofops.adapters.local import openai as api

    def identifier(value: object) -> str | None:
        return (
            value
            if isinstance(value, str)
            and api.re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
            and not value.startswith("sk_")
            and self._key not in value
            else None
        )

    error_data = error if isinstance(error, dict) else {}
    local_request_id = (self._dispatch_context.get() or {}).get("request_id")
    if not (
        isinstance(local_request_id, str)
        and api.re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", local_request_id)
        and self._key not in local_request_id
        and not local_request_id.startswith("sk-")
    ):
        local_request_id = None
    diagnostic: dict[str, Any] = {
        "diagnostic_policy_sha256": api.canonical_hash(api.HTTP_ERROR_POLICY),
        "request_sha256": api.canonical_hash(body),
        "http_status": status,
        "http_request_id": (
            request_id
            if isinstance(request_id, str)
            and api.re.fullmatch(r"req_[a-zA-Z0-9]{1,128}", request_id)
            and self._key not in request_id
            else None
        ),
        "retry_after": (
            retry_after
            if isinstance(retry_after, str) and api.re.fullmatch(r"[0-9]{1,8}", retry_after)
            else None
        ),
        "error_code": identifier(error_data.get("code")),
        "error_type": identifier(error_data.get("type")),
        "response_body_sha256": api.hashlib.sha256(raw).hexdigest(),
        "response_body_bytes_read": len(raw),
        "response_body_truncated": len(raw) > 1_048_576,
    }
    diagnostic.update(
        observed_at=api.now().isoformat(),
        model=api.MODEL,
        request_bytes=len(api.json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()),
        client_request_id=(
            client_request_id
            if isinstance(client_request_id, str)
            and api.re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", client_request_id)
            and self._key not in client_request_id
            and not client_request_id.startswith("sk-")
            else None
        ),
        latency_ms=latency_ms,
        local_request_id=local_request_id,
        headers={
            name: value
            for name, value in (headers or {}).items()
            if name in {"server", "content-type", "cf-ray"}
            and isinstance(value, str)
            and len(value) <= 160
            and api.re.fullmatch(r"[a-zA-Z0-9 .,;:=/+_-]+", value)
            and self._key not in value
            and "sk-" not in value
        },
        admission=(
            self.http_admission_snapshot() if hasattr(self, "http_admission_snapshot") else None
        ),
    )
    if response_failure is not None:
        from proofops.application.provider_resilience import RESPONSE_ERROR_DIAGNOSTIC_POLICY

        diagnostic.update(
            diagnostic_policy_sha256=api.canonical_hash(RESPONSE_ERROR_DIAGNOSTIC_POLICY),
            **response_failure,
        )
        if not response_failure["body_received"]:
            diagnostic.update(
                response_body_sha256=None,
                response_body_bytes_read=None,
                response_body_truncated=None,
            )
    if transport_context is not None:
        diagnostic.update(transport_context)
    try:
        directory = getattr(self, "http_error_directory", self._responses)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / (api.canonical_hash(diagnostic) + ".http-error.json")
        with api.os.fdopen(
            api.os.open(path, api.os.O_WRONLY | api.os.O_CREAT | api.os.O_EXCL, 0o600), "w"
        ) as f:
            api.json.dump(diagnostic, f, sort_keys=True)
            f.flush()
            api.os.fsync(f.fileno())
    except OSError:
        # A duplicate or unwritable sidecar must not change the HTTP failure,
        # release uncertain spend, or trigger another provider dispatch.
        pass
    return diagnostic


def _post_admitted(
    self: OpenAIProbe, body: dict[str, Any], *, client_request_id: str | None = None
) -> dict[str, Any]:
    from proofops.adapters.local import openai as api
    from proofops.adapters.local.openai_connections import (
        OpenAIControlNotSent,
        control_before_send,
    )
    from proofops.application.ports.jobs import JobControlSignal, LeaseLost

    # Hosted adapters admit each physical attempt before broker reservation.
    with control_before_send():
        if (
            self.http_dispatch_guard
            and client_request_id is None
            and not getattr(self, "provider_scheduler", None)
        ):
            admission = getattr(self, "http_dispatch_admission", None)
            if admission is not None:
                admission()
        pool = self.connection_pool if self.transport_policy else None
        if pool:
            connection, connection_id, reused = pool.take()
        else:
            connection = api.http.client.HTTPSConnection("api.openai.com", timeout=90)
            connection_id, reused = str(api.uuid4()), False
    reusable = False
    request_started = False
    started = api.time.monotonic()
    response = raw = None
    trace: dict[str, Any] | None = None
    if self.http_diagnostic_policy:
        trace = dict(
            started_at=api.now().isoformat(),
            started_monotonic=started,
            connection_id=connection_id,
            connection_new=not reused,
            connection_reused=reused,
            dns_ms=None,
            connect_ms=None,
            tls_ms=None,
            connect_tls_ms=None,
            ttfb_ms=None,
        )

    def transport_context() -> dict[str, Any] | None:
        if trace is None:
            return None
        from proofops.adapters.local.http_diagnostics import error_context

        finished = api.time.monotonic()
        return error_context(
            self,
            trace
            | dict(
                finished_at=api.now().isoformat(),
                finished_monotonic=finished,
                total_ms=round((finished - started) * 1000, 2),
            ),
            response,
            client_request_id,
        )

    try:
        encoded = api.json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {
            "Authorization": "Bearer " + self._key,
            "Content-Type": "application/json",
            **({"X-Client-Request-Id": client_request_id} if client_request_id else {}),
        }
        if getattr(self, "provider_scheduler", None):
            self.http_transport_pacing()
        if trace is not None:
            trace.update(
                wire_sha256=api.hashlib.sha256(encoded).hexdigest(),
                transport_started_monotonic=api.time.monotonic(),
                request_header_names=sorted(
                    set(headers) | {"Host", "Accept-Encoding", "Content-Length"}
                ),
                request_header_settings={
                    "content-type": "application/json",
                    "host": "api.openai.com",
                    "accept-encoding": "identity",
                    "content-length": str(len(encoded)),
                },
            )
            # The regular request() also calls connect(). This separates the
            # combined DNS/TCP/TLS stage without changing Host/SNI/TLS/wire.
            if not reused and hasattr(connection, "connect"):
                connecting = api.time.monotonic()
                connection.connect()
                trace["connect_tls_ms"] = round((api.time.monotonic() - connecting) * 1000, 2)
                trace["tls_session_reused"] = getattr(connection.sock, "session_reused", None)
            if reused:
                connection.auto_open = 0  # Never reconnect implicitly after request starts.
        request_started = True
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=encoded,
            headers=headers,
        )
        response = connection.getresponse()
        if trace is not None:
            trace["ttfb_ms"] = round(
                (api.time.monotonic() - trace["transport_started_monotonic"]) * 1000, 2
            )
        self.rate_limit_headers = {
            name: response.getheader(name)
            for name in (
                "x-ratelimit-limit-requests",
                "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-requests",
                "x-ratelimit-remaining-tokens",
                "x-ratelimit-reset-requests",
                "x-ratelimit-reset-tokens",
            )
        }
        if response.status != 200:
            raw = response.read(1_048_577)
            error = {}
            if len(raw) <= 1_048_576:
                try:
                    error = api.json.loads(raw).get("error", {})
                except (AttributeError, api.json.JSONDecodeError, TypeError):
                    error = {}
            diagnostic = self._record_http_error(
                body,
                response.status,
                raw,
                error,
                response.getheader("x-request-id"),
                response.getheader("retry-after"),
                client_request_id=client_request_id,
                headers={
                    name: response.getheader(name) for name in ("server", "content-type", "cf-ray")
                },
                latency_ms=round((api.time.monotonic() - started) * 1000, 2),
                transport_context=transport_context(),
            )
            if isinstance(error, dict) and error.get("code") in {
                "insufficient_quota",
                "organization_spend_limit_exceeded",
                "project_spend_limit_exceeded",
            }:
                raise ValueError("OPENAI_INSUFFICIENT_QUOTA")
            delay = api._retry_after(response.getheader("retry-after"))
            if (
                self.http_retry_policy == api.HTTP_RETRY_POLICY
                and response.status == 403
                and 0 < len(raw) <= 1_048_576
                and isinstance(error, dict)
                and error.get("code") == api.HTTP_RETRY_POLICY["error_code"]
                and error.get("type") == api.HTTP_RETRY_POLICY["error_type"]
                and diagnostic["http_request_id"] is not None
                and delay is not None
                and delay <= api.HTTP_RETRY_POLICY["max_delay_seconds"]
            ):
                raise api.OpenAITransient403(delay=delay, diagnostic=diagnostic)
            problem = ValueError(f"OPENAI_HTTP_{response.status}")
            if isinstance(error, dict) and error.get("code") == "billing_not_active":
                setattr(problem, "provider_error_code", "billing_not_active")
            if response.status == 429:
                # Preserve the finite code; never expose the response body.
                setattr(
                    problem,
                    "retry_after_seconds",
                    api._retry_after(response.getheader("Retry-After")),
                )
            raise problem
        raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("OPENAI_RESPONSE_TOO_LARGE")
        data = api.json.loads(raw)
        data["openai_request_id"] = response.getheader("x-request-id")
        reusable = pool is not None and not response.will_close
        if self.transport_policy and self._dispatch_context.get() is not None:
            cast(dict[str, Any], self._dispatch_context.get()).setdefault(
                "connection_attempts", []
            ).append(
                dict(
                    connection_id=connection_id,
                    connection_reused=reused,
                    connect_tls_ms=trace.get("connect_tls_ms") if trace else None,
                    tls_session_reused=trace.get("tls_session_reused") if trace else None,
                    total_ms=round((api.time.monotonic() - started) * 1000, 2),
                )
            )
        return cast("dict[str, Any]", data)
    except (JobControlSignal, LeaseLost) as error:
        if not request_started:
            raise OpenAIControlNotSent(error) from None
        raise
    except (
        OSError,
        api.http.client.HTTPException,
        api.json.JSONDecodeError,
        UnicodeError,
    ) as error:
        diagnostic = None
        if self.response_uncertainty_policy:
            diagnostic = self._record_http_error(
                body,
                response.status if response is not None else None,
                raw or b"",
                {},
                response.getheader("x-request-id") if response is not None else None,
                response.getheader("retry-after") if response is not None else None,
                client_request_id=client_request_id,
                headers={
                    name: response.getheader(name) for name in ("server", "content-type", "cf-ray")
                }
                if response is not None
                else {},
                latency_ms=round((api.time.monotonic() - started) * 1000, 2),
                response_failure=dict(
                    exception_type=type(error).__name__,
                    response_received=response is not None,
                    body_received=raw is not None,
                    **(
                        dict(
                            request_started=request_started,
                            delivery_state="unknown" if request_started else "never_sent",
                            transport_policy_sha256=api.canonical_hash(self.transport_policy),
                        )
                        if self.transport_policy
                        else {}
                    ),
                ),
                transport_context=transport_context(),
            )
        if self.transport_policy and not request_started:
            from proofops.adapters.local.openai_connections import OpenAIConnectNotSent

            raise OpenAIConnectNotSent(diagnostic) from None
        raise
    finally:
        if reusable:
            cast("OpenAIConnections", pool).release(connection, connection_id)
        else:
            connection.close()
