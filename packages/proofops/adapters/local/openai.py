"""Budgeted direct OpenAI chat transport; shares the existing USD3 Decisions ledger."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

# Ledger policy remains byte-identical to existing Decisions policy: never reset spend.
from proofops.adapters.local.decisions import OPENAI_POLICY as POLICY
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.application.openai_retry import POLICY as HTTP_RETRY_POLICY
from proofops.application.openai_retry import POLICY_HASH as HTTP_RETRY_POLICY_HASH
from proofops.domain.provenance import canonical_hash

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/chat/completions"
PRICE_RECHECK_AT = datetime(2026, 10, 21, tzinfo=UTC)
PRICE = {"input": "0.10", "cached_input": "0.01", "cache_write": "0.125", "output": "0.50"}
HTTP_ERROR_POLICY = {
    "schema": "openai-http-error-diagnostic-t1-v2",
    "body": "bounded-sha256-only",
    "identifiers": "bounded-snake-case-no-key",
    "headers": ["x-request-id", "retry-after", "server", "content-type", "cf-ray"],
    "context": "utc-wire-bytes-model-local-request-admission-latency",
    "storage": "private-immutable-sidecar-best-effort",
}
WIRE_POLICY = {
    "provider": "openai",
    "endpoint": ENDPOINT,
    "model": MODEL,
    "reasoning_effort": "none",
    "temperature": 0,
    "store": False,
    "service_tier": "default",
    "price_per_million": PRICE,
    "pricing_source": "https://developers.openai.com/api/docs/models/gpt-6-luna",
    "captured_at": "2026-10-09",
    "price_recheck_at": "2026-10-21T00:00:00Z",
    "max_request_bytes": 16384,
    "max_response_bytes": 1048576,
    "max_attempts": 2,
    "vat_reserve": "1.10",
}
CAPACITY_POLICY = {
    "schema": "openai-luna-input-reservation-v1",
    "model_id": MODEL,
    "reservation_input_tokens": 32768,
    "request_bytes": 16384,
    "model_binding_sha256": canonical_hash(WIRE_POLICY),
}


def now():
    return datetime.now(UTC)


class OpenAITransient403(ValueError):
    """Explicit overload evidence, never created for an opaque denial."""

    def __init__(self, *, delay, diagnostic):
        super().__init__("OPENAI_HTTP_403")
        self.retry_after_seconds = delay
        self.diagnostic = diagnostic
        self.policy_sha256 = HTTP_RETRY_POLICY_HASH


def _retry_after(value):
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                return None
            seconds = (deadline - now()).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) and seconds >= 0 else None


def validate_capacity_policy(policy, *, model_id):
    if model_id != MODEL or policy != CAPACITY_POLICY:
        raise ValueError("OPENAI_CAPACITY_POLICY_MISMATCH")
    if now() >= PRICE_RECHECK_AT:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    return CAPACITY_POLICY["reservation_input_tokens"]


def token_cost(usage):
    incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_write_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (incoming, outgoing, cached, written)):
        raise ValueError("INVALID_USAGE")
    if incoming > 32768 or cached + written > incoming:
        raise ValueError("INVALID_USAGE")
    return (
        (
            (incoming - cached - written) * Decimal(PRICE["input"])
            + cached * Decimal(PRICE["cached_input"])
            + written * Decimal(PRICE["cache_write"])
            + outgoing * Decimal(PRICE["output"])
        )
        / Decimal(1000000)
        * Decimal("1.10")
    )


class OpenAIProbe(OpenRouterProbe):
    _response_context = ContextVar("openai_response_context", default=None)
    _cache_request_context = ContextVar("openai_cache_request_context", default=None)
    _dispatch_context = ContextVar("openai_dispatch_context", default=None)
    response_cache_path = None
    response_policy = None
    wire_policy = WIRE_POLICY
    http_retry_policy = None
    provider_resilience = None
    http_dispatch_guard = False
    response_uncertainty_policy = None
    http_diagnostic_policy = None
    transport_policy = None
    connection_pool = None
    max_request_bytes = WIRE_POLICY["max_request_bytes"]

    def _authorize_response_request(self):
        """Hosted adapters recheck their live owner/source before cache access."""

    def configure_response_policy(self, snapshot, *, role):
        from proofops.application.analysis_profile import MODEL_RESPONSE_POLICY

        policy = snapshot.get("analysis_profile_policy", {})
        from proofops.application.fxh_policy import POLICY as FXH_POLICY
        from proofops.application.fxh_policy import enabled as fxh_enabled

        fxh = fxh_enabled(policy)
        self.max_request_bytes = WIRE_POLICY["max_request_bytes"]
        self.http_retry_policy = None
        self.provider_resilience = None
        self.provider_scheduler = None
        self.http_dispatch_guard = False
        self.response_uncertainty_policy = None
        self.http_diagnostic_policy = None
        self.transport_policy = None
        if "model_response_policy" not in policy:
            self.response_policy = None
            self.wire_policy = WIRE_POLICY
            return  # Historical snapshots keep their original wire and receipts.
        if (
            policy["model_response_policy"] != MODEL_RESPONSE_POLICY
            or snapshot.get("analysis_profile_policy_sha256") != canonical_hash(policy)
            or not isinstance(snapshot.get("tenant_id"), str)
            or not snapshot["tenant_id"]
            or len(snapshot.get("document", {}).get("sha256", "")) != 64
            or any(c not in "0123456789abcdef" for c in snapshot["document"]["sha256"])
            or role not in {"extract", "elements", "preliminary", "relation"}
        ):
            raise ValueError("MODEL_RESPONSE_POLICY_MISMATCH")
        self.response_policy = dict(
            tenant_id=snapshot["tenant_id"],
            source_sha256=snapshot["document"]["sha256"],
            analysis_policy_sha256=canonical_hash(policy),
        )
        self.response_role = role
        if "openai_transport_policy" in policy:
            from proofops.adapters.local.openai_connections import OpenAIConnections
            from proofops.application.openai_transport import POLICY as transport_policy

            if policy["openai_transport_policy"] != transport_policy or policy.get(
                "openai_transport_policy_sha256"
            ) != canonical_hash(transport_policy):
                raise ValueError("OPENAI_TRANSPORT_POLICY_MISMATCH")
            self.transport_policy = transport_policy
            if self.connection_pool is None:
                self.connection_pool = OpenAIConnections()
            with sqlite3.connect(self.ledger) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS probe_transport_attempts ("
                    "attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, bound TEXT NOT NULL, "
                    "state TEXT NOT NULL, diagnostic TEXT)"
                )
        if "http_diagnostic_policy" in policy:
            from proofops.application.provider_resilience import HTTP_DIAGNOSTIC_POLICY

            if policy["http_diagnostic_policy"] != HTTP_DIAGNOSTIC_POLICY:
                raise ValueError("HTTP_DIAGNOSTIC_POLICY_MISMATCH")
            self.http_diagnostic_policy = HTTP_DIAGNOSTIC_POLICY
        if "provider_resilience" in policy:
            from proofops.application.provider_resilience import POLICY as resilience

            if policy["provider_resilience"] != resilience:
                raise ValueError("PROVIDER_RESILIENCE_POLICY_MISMATCH")
            self.provider_resilience = resilience
            from proofops.application.provider_resilience import (
                SCHEDULER_C24_POLICY,
                SCHEDULER_POLICY,
            )

            if "provider_scheduler" in policy and policy["provider_scheduler"] not in (
                SCHEDULER_POLICY,
                SCHEDULER_C24_POLICY,
            ):
                raise ValueError("PROVIDER_SCHEDULER_POLICY_MISMATCH")
            self.provider_scheduler = policy.get("provider_scheduler")
            self.http_dispatch_guard = policy.get("http_dispatch_guard") in (
                "physical-attempt-paced4-denial3-f1-v2",
                SCHEDULER_POLICY["profile"],
                SCHEDULER_C24_POLICY["profile"],
            )
            if "response_uncertainty_policy" in policy:
                from proofops.application.provider_resilience import (
                    RESPONSE_ERROR_DIAGNOSTIC_POLICY,
                )

                if policy["response_uncertainty_policy"] != RESPONSE_ERROR_DIAGNOSTIC_POLICY:
                    raise ValueError("RESPONSE_UNCERTAINTY_POLICY_MISMATCH")
                self.response_uncertainty_policy = RESPONSE_ERROR_DIAGNOSTIC_POLICY
        self.wire_policy = WIRE_POLICY | dict(
            top_p=1, model_response_policy_sha256=canonical_hash(MODEL_RESPONSE_POLICY)
        )
        if self.transport_policy:
            self.wire_policy = self.wire_policy | dict(
                transport_policy_sha256=canonical_hash(self.transport_policy)
            )
        if "openai_retry_policy" in policy:
            if policy["openai_retry_policy"] != HTTP_RETRY_POLICY:
                raise ValueError("OPENAI_RETRY_POLICY_MISMATCH")
            self.http_retry_policy = HTTP_RETRY_POLICY
            self.wire_policy = self.wire_policy | dict(
                http_retry_policy_sha256=HTTP_RETRY_POLICY_HASH
            )
        if fxh:
            self.max_request_bytes = FXH_POLICY["max_request_bytes"]

    @contextmanager
    def response_context(self, *, role, replica):
        if (
            role not in {"extract", "elements", "preliminary", "relation"}
            or type(replica) is not int
            or not 0 <= replica <= 3
        ):
            raise ValueError("MODEL_RESPONSE_CONTEXT_INVALID")
        token = self._response_context.set((role, replica))
        try:
            yield
        finally:
            self._response_context.reset(token)

    def __init__(self, api_key: str, ledger: Path, *, model: str = MODEL, wire_policy_version=2):
        if model != MODEL:
            raise ValueError("UNSUPPORTED_MODEL")
        if not api_key or any(c.isspace() for c in api_key):
            raise ValueError("OPENAI_API_KEY_MISSING_OR_INVALID")
        if wire_policy_version != 2:
            raise ValueError("OPENAI_WIRE_POLICY_INVALID")
        self.model, self._key, self.ledger = model, api_key, Path(ledger)
        self.wire_policy_version = wire_policy_version
        self.ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.ledger) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS probe_policy (id INTEGER PRIMARY KEY, body TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS probe_calls (request_id TEXT PRIMARY KEY, "
                "signature TEXT NOT NULL, committed TEXT NOT NULL, receipt TEXT)"
            )
            policy = json.dumps(POLICY, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO probe_policy VALUES (1, ?)", (policy,))
            stored = db.execute("SELECT body FROM probe_policy WHERE id=1").fetchone()[0]
            if stored != policy:
                raise ValueError("BUDGET_POLICY_MISMATCH")
        self.ledger.chmod(0o600)
        self._responses = self.ledger.with_name(self.ledger.name + ".responses")
        self._responses.mkdir(mode=0o700, exist_ok=True)
        self._responses.chmod(0o700)

    def _total(self, db):
        if db.execute("SELECT body FROM probe_policy WHERE id=1").fetchone() != (
            json.dumps(POLICY, sort_keys=True),
        ):
            raise ValueError("BUDGET_POLICY_MISMATCH")
        total = Decimal(0)
        for raw, receipt in db.execute("SELECT committed, receipt FROM probe_calls"):
            try:
                amount = Decimal(raw)
                if (
                    not amount.is_finite()
                    or amount < 0
                    or amount > Decimal(POLICY["reservation_usd"])
                ):
                    raise ValueError
                if receipt is None and amount != Decimal(POLICY["reservation_usd"]):
                    raise ValueError
                if (
                    receipt is not None
                    and Decimal(json.loads(receipt)["cost_with_vat_reserve_usd"]) != amount
                ):
                    raise ValueError
            except (InvalidOperation, KeyError, TypeError, ValueError):
                raise ValueError("BUDGET_LEDGER_INVALID") from None
            total += amount
        return total

    def summary(self):
        with sqlite3.connect(self.ledger) as db:
            total = self._total(db)
            calls, unsettled = db.execute(
                "SELECT count(*), sum(receipt IS NULL) FROM probe_calls"
            ).fetchone()
        return {
            "limit_usd": POLICY["limit_usd"],
            "calls": calls,
            "unsettled_calls": unsettled or 0,
            "committed_usd": str(total),
        }

    def request_body(self, system, user_json, *, request_id, max_tokens=1024, json_mode=False):
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
        body = {
            "model": MODEL,
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
            len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
            > self.max_request_bytes
        ):
            raise ValueError("PROBE_REQUEST_TOO_LARGE")
        return body

    def _record_http_error(
        self,
        body,
        status,
        raw,
        error,
        request_id,
        retry_after,
        *,
        client_request_id=None,
        headers=None,
        latency_ms=None,
        response_failure=None,
        transport_context=None,
    ):
        """Keep denial identifiers without persisting messages, inputs or cookies."""

        def identifier(value):
            return (
                value
                if isinstance(value, str)
                and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
                and not value.startswith("sk_")
                and self._key not in value
                else None
            )

        error = error if isinstance(error, dict) else {}
        local_request_id = (self._dispatch_context.get() or {}).get("request_id")
        if not (
            isinstance(local_request_id, str)
            and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", local_request_id)
            and self._key not in local_request_id
            and not local_request_id.startswith("sk-")
        ):
            local_request_id = None
        diagnostic = {
            "diagnostic_policy_sha256": canonical_hash(HTTP_ERROR_POLICY),
            "request_sha256": canonical_hash(body),
            "http_status": status,
            "http_request_id": (
                request_id
                if isinstance(request_id, str)
                and re.fullmatch(r"req_[a-zA-Z0-9]{1,128}", request_id)
                and self._key not in request_id
                else None
            ),
            "retry_after": (
                retry_after
                if isinstance(retry_after, str) and re.fullmatch(r"[0-9]{1,8}", retry_after)
                else None
            ),
            "error_code": identifier(error.get("code")),
            "error_type": identifier(error.get("type")),
            "response_body_sha256": hashlib.sha256(raw).hexdigest(),
            "response_body_bytes_read": len(raw),
            "response_body_truncated": len(raw) > 1_048_576,
        }
        diagnostic.update(
            observed_at=now().isoformat(),
            model=MODEL,
            request_bytes=len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()),
            client_request_id=(
                client_request_id
                if isinstance(client_request_id, str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", client_request_id)
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
                and re.fullmatch(r"[a-zA-Z0-9 .,;:=/+_-]+", value)
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
                diagnostic_policy_sha256=canonical_hash(RESPONSE_ERROR_DIAGNOSTIC_POLICY),
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
            path = directory / (canonical_hash(diagnostic) + ".http-error.json")
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
                json.dump(diagnostic, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            # A duplicate or unwritable sidecar must not change the HTTP failure,
            # release uncertain spend, or trigger another provider dispatch.
            pass
        return diagnostic

    def physical_attempt_scope(self):
        if getattr(self, "provider_scheduler", None) is None:
            return nullcontext()
        if not hasattr(self, "http_attempt_scope"):
            raise ValueError("PROVIDER_SCHEDULER_BINDING_REQUIRED")
        return self.http_attempt_scope()

    def _post(self, body, *, client_request_id=None):
        # Hosted transport has already admitted before its broker reservation.
        scope = self.physical_attempt_scope() if client_request_id is None else nullcontext()
        if not self.transport_policy or client_request_id is not None:
            with scope:
                return self._post_admitted(body, client_request_id=client_request_id)
        from proofops.adapters.local.openai_connections import OpenAIConnectNotSent
        from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen
        from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred

        dispatch = self._dispatch_context.get()
        for attempt in range(2):
            attempt_id = str(uuid4())
            # A distinct physical reservation is bounded by the still-reserved
            # logical USD.02 envelope. The first proven-unsent attempt costs zero.
            # No two possibly delivered attempts share this retry authorization.
            with sqlite3.connect(self.ledger, timeout=30) as db:
                row = db.execute(
                    "SELECT receipt FROM probe_calls WHERE request_id=?", (dispatch["request_id"],)
                ).fetchone()
                if row != (None,):
                    raise ValueError("TRANSPORT_RESERVATION_REQUIRED")
                db.execute(
                    "INSERT INTO probe_transport_attempts VALUES (?,?,?,'reserved',NULL)",
                    (attempt_id, dispatch["request_id"], POLICY["reservation_usd"]),
                )
            try:
                with self.physical_attempt_scope():
                    data = self._post_admitted(body, client_request_id=attempt_id)
                state, diagnostic = "response_received", None
            except OpenAIConnectNotSent as error:
                state, diagnostic = "never_sent", json.dumps(error.diagnostic, sort_keys=True)
                self._finish_transport_attempt(attempt_id, state, diagnostic)
                if attempt == 0 and not dispatch["transport_retries"]:
                    dispatch["transport_retries"].append(
                        dict(
                            policy_sha256=canonical_hash(self.transport_policy),
                            failed_attempt_id=attempt_id,
                            dispatch_state="never_sent",
                            diagnostic_sha256=canonical_hash(error.diagnostic),
                        )
                    )
                    self._authorize_response_request()
                    if now() >= PRICE_RECHECK_AT:
                        self._settle_never_sent(dispatch["request_id"])
                        raise ValueError("PRICE_RECHECK_REQUIRED")
                    continue
                self._settle_never_sent(dispatch["request_id"])
                raise ValueError("PROVIDER_PROCESSING_FAILED") from None
            except (ProviderCircuitOpen, ProviderAdmissionDeferred):
                self._finish_transport_attempt(attempt_id, "never_sent", None)
                self._settle_never_sent(dispatch["request_id"])
                raise
            except BaseException:
                self._finish_transport_attempt(attempt_id, "unknown", None)
                raise
            self._finish_transport_attempt(attempt_id, state, diagnostic)
            return data
        raise ValueError("PROVIDER_PROCESSING_FAILED")

    def _finish_transport_attempt(self, attempt_id, state, diagnostic):
        with sqlite3.connect(self.ledger, timeout=30) as db:
            db.execute(
                "UPDATE probe_transport_attempts SET state=?,diagnostic=? "
                "WHERE attempt_id=? AND state='reserved'",
                (state, diagnostic, attempt_id),
            )

    def _settle_never_sent(self, request_id):
        with sqlite3.connect(self.ledger, timeout=30) as db:
            states = [
                r[0]
                for r in db.execute(
                    "SELECT state FROM probe_transport_attempts WHERE request_id=?", (request_id,)
                )
            ]
            if not states or any(state != "never_sent" for state in states):
                return  # A prior schema attempt may already have reached the provider.
            receipt = dict(
                request_id=request_id,
                schema_valid=False,
                cost_with_vat_reserve_usd="0",
                dispatch_state="never_sent",
                cost_source="explicit_connect_failure_before_http_send",
            )
            db.execute(
                "UPDATE probe_calls SET committed='0',receipt=? "
                "WHERE request_id=? AND receipt IS NULL",
                (json.dumps(receipt), request_id),
            )

    def _post_admitted(self, body, *, client_request_id=None):
        # Hosted adapters admit each physical attempt before broker reservation.
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
            connection = http.client.HTTPSConnection("api.openai.com", timeout=90)
            connection_id, reused = str(uuid4()), False
        reusable = False
        request_started = False
        started = time.monotonic()
        response = raw = None
        trace = None
        if self.http_diagnostic_policy:
            trace = dict(
                started_at=now().isoformat(),
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

        def transport_context():
            if trace is None:
                return None
            from proofops.adapters.local.http_diagnostics import error_context

            finished = time.monotonic()
            return error_context(
                self,
                trace
                | dict(
                    finished_at=now().isoformat(),
                    finished_monotonic=finished,
                    total_ms=round((finished - started) * 1000, 2),
                ),
                response,
                client_request_id,
            )

        try:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            headers = {
                "Authorization": "Bearer " + self._key,
                "Content-Type": "application/json",
                **({"X-Client-Request-Id": client_request_id} if client_request_id else {}),
            }
            if getattr(self, "provider_scheduler", None):
                self.http_transport_pacing()
            if trace is not None:
                trace.update(
                    wire_sha256=hashlib.sha256(encoded).hexdigest(),
                    transport_started_monotonic=time.monotonic(),
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
                    connecting = time.monotonic()
                    connection.connect()
                    trace["connect_tls_ms"] = round((time.monotonic() - connecting) * 1000, 2)
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
                    (time.monotonic() - trace["transport_started_monotonic"]) * 1000, 2
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
                        error = json.loads(raw).get("error", {})
                    except (AttributeError, json.JSONDecodeError, TypeError):
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
                        name: response.getheader(name)
                        for name in ("server", "content-type", "cf-ray")
                    },
                    latency_ms=round((time.monotonic() - started) * 1000, 2),
                    transport_context=transport_context(),
                )
                if isinstance(error, dict) and error.get("code") in {
                    "insufficient_quota",
                    "organization_spend_limit_exceeded",
                    "project_spend_limit_exceeded",
                }:
                    raise ValueError("OPENAI_INSUFFICIENT_QUOTA")
                delay = _retry_after(response.getheader("retry-after"))
                if (
                    self.http_retry_policy == HTTP_RETRY_POLICY
                    and response.status == 403
                    and 0 < len(raw) <= 1_048_576
                    and isinstance(error, dict)
                    and error.get("code") == HTTP_RETRY_POLICY["error_code"]
                    and error.get("type") == HTTP_RETRY_POLICY["error_type"]
                    and diagnostic["http_request_id"] is not None
                    and delay is not None
                    and delay <= HTTP_RETRY_POLICY["max_delay_seconds"]
                ):
                    raise OpenAITransient403(delay=delay, diagnostic=diagnostic)
                problem = ValueError(f"OPENAI_HTTP_{response.status}")
                if isinstance(error, dict) and error.get("code") == "billing_not_active":
                    problem.provider_error_code = "billing_not_active"
                if response.status == 429:
                    # Preserve the finite code; never expose the response body.
                    setattr(
                        problem,
                        "retry_after_seconds",
                        _retry_after(response.getheader("Retry-After")),
                    )
                raise problem
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("OPENAI_RESPONSE_TOO_LARGE")
            data = json.loads(raw)
            data["openai_request_id"] = response.getheader("x-request-id")
            reusable = pool is not None and not response.will_close
            if self.transport_policy and self._dispatch_context.get() is not None:
                self._dispatch_context.get().setdefault("connection_attempts", []).append(
                    dict(
                        connection_id=connection_id,
                        connection_reused=reused,
                        connect_tls_ms=trace.get("connect_tls_ms") if trace else None,
                        tls_session_reused=trace.get("tls_session_reused") if trace else None,
                        total_ms=round((time.monotonic() - started) * 1000, 2),
                    )
                )
            return data
        except (OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeError) as error:
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
                        name: response.getheader(name)
                        for name in ("server", "content-type", "cf-ray")
                    }
                    if response is not None
                    else {},
                    latency_ms=round((time.monotonic() - started) * 1000, 2),
                    response_failure=dict(
                        exception_type=type(error).__name__,
                        response_received=response is not None,
                        body_received=raw is not None,
                        **(
                            dict(
                                request_started=request_started,
                                delivery_state="unknown" if request_started else "never_sent",
                                transport_policy_sha256=canonical_hash(self.transport_policy),
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
                pool.release(connection, connection_id)
            else:
                connection.close()

    def complete(
        self, system, user_json, *, request_id, max_tokens=1024, json_mode=False, schema_json=None
    ):
        if self.response_policy is None:
            return self._complete_uncached(
                system,
                user_json,
                request_id=request_id,
                max_tokens=max_tokens,
                json_mode=json_mode,
                schema_json=schema_json,
            )
        from proofops.adapters.local.model_response_cache import ModelResponseCache

        if now() >= PRICE_RECHECK_AT:
            raise ValueError("PRICE_RECHECK_REQUIRED")
        body = self.request_body(
            system, user_json, request_id=request_id, max_tokens=max_tokens, json_mode=json_mode
        )
        if schema_json is not None:
            Draft202012Validator.check_schema(json.loads(schema_json))
        role, replica = self._response_context.get() or (self.response_role, 0)
        # Preliminary wire does not contain replica_id. A caller must bind it
        # explicitly; otherwise fail closed instead of merging the ensemble.
        if role != "extract" and replica not in (1, 2, 3):
            raise ValueError("MODEL_RESPONSE_REPLICA_REQUIRED")
        response_request = self.response_policy | dict(
            role=role,
            replica=replica,
            wire_sha256=canonical_hash(body),
            schema_sha256=canonical_hash(schema_json),
        )
        key = canonical_hash(response_request)
        with sqlite3.connect(self.ledger, timeout=30) as db:
            if db.execute("SELECT 1 FROM probe_calls WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError("DUPLICATE_PROBE_REQUEST")
        self._authorize_response_request()
        cache = ModelResponseCache(
            self.response_cache_path or self.ledger.parent / "model-responses.sqlite3"
        )
        hit = cache.claim(key, self.ledger, request_id)
        if hit is not None:
            self._authorize_response_request()  # A single-flight wait may outlive its owner.
            source, source_hash = hit
            result = source | dict(
                request_id=request_id,
                input_tokens=0,
                output_tokens=0,
                cached_tokens=0,
                cache_write_tokens=0,
                cost_with_vat_reserve_usd="0",
                attempts=[],
                cost_source="exact_response_reuse_no_provider_dispatch",
                response_reuse=dict(
                    policy="exact-model-response-v1",
                    key=key,
                    role=role,
                    replica=replica,
                    source_request_id=source["request_id"],
                    source_receipt_sha256=source_hash,
                    source_response_sha256=source["response_sha256"],
                ),
            )
            receipt = {k: v for k, v in result.items() if k != "content"}
            with sqlite3.connect(self.ledger, timeout=30) as db:
                db.execute("BEGIN IMMEDIATE")
                self._total(db)
                try:
                    db.execute(
                        "INSERT INTO probe_calls VALUES (?,?,?,?)",
                        (
                            request_id,
                            canonical_hash(body),
                            "0",
                            json.dumps(receipt, sort_keys=True),
                        ),
                    )
                except sqlite3.IntegrityError:
                    raise ValueError("DUPLICATE_PROBE_REQUEST") from None
            return result
        context_token = self._cache_request_context.set(response_request)
        try:
            result = self._complete_uncached(
                system,
                user_json,
                request_id=request_id,
                max_tokens=max_tokens,
                json_mode=json_mode,
                schema_json=schema_json,
            )
            if result["schema_valid"] is True:
                cache.publish(key, result)
            else:
                cache.release_unsent_or_invalid(key, self.ledger, request_id)
            return result
        except Exception:
            cache.release_unsent_or_invalid(key, self.ledger, request_id)
            raise
        finally:
            self._cache_request_context.reset(context_token)

    def _complete_uncached(
        self, system, user_json, *, request_id, max_tokens=1024, json_mode=False, schema_json=None
    ):
        token = self._dispatch_context.set({"transport_retries": [], "request_id": request_id})
        try:
            return self._complete_reserved(
                system,
                user_json,
                request_id=request_id,
                max_tokens=max_tokens,
                json_mode=json_mode,
                schema_json=schema_json,
            )
        finally:
            self._dispatch_context.reset(token)

    def _complete_reserved(
        self, system, user_json, *, request_id, max_tokens=1024, json_mode=False, schema_json=None
    ):
        if now() >= PRICE_RECHECK_AT:
            raise ValueError("PRICE_RECHECK_REQUIRED")
        body = self.request_body(
            system, user_json, request_id=request_id, max_tokens=max_tokens, json_mode=json_mode
        )
        validator = (
            Draft202012Validator(json.loads(schema_json), format_checker=FormatChecker())
            if schema_json is not None
            else None
        )
        with sqlite3.connect(self.ledger, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM probe_calls WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError("DUPLICATE_PROBE_REQUEST")
            if self._total(db) + Decimal(POLICY["reservation_usd"]) > Decimal(POLICY["limit_usd"]):
                raise ValueError("BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO probe_calls VALUES (?,?,?,NULL)",
                (request_id, canonical_hash(body), POLICY["reservation_usd"]),
            )
        if getattr(self, "provider_scheduler", None):
            self._dispatch_context.get()["local_reserved_monotonic"] = time.monotonic()
        attempts, total_cost, input_tokens, output_tokens = [], Decimal(0), 0, 0
        for attempt in range(2):
            if now() >= PRICE_RECHECK_AT:
                raise ValueError("PRICE_RECHECK_REQUIRED")
            try:
                started = time.monotonic()
                data = self._post(body)
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                path = self._responses / (canonical_hash(f"{request_id}:{attempt}") + ".json")
                with os.fdopen(
                    os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
                ) as stream:
                    json.dump(
                        {"request_id": request_id, "attempt": attempt, "provider_response": data},
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception as error:
                from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen
                from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred
                from proofops.application.budget import BudgetExceeded
                from proofops.application.provider_resilience import ISOLATED_CODES

                if isinstance(error, BudgetExceeded):
                    raise
                if self.http_dispatch_guard and isinstance(
                    error, ProviderCircuitOpen | ProviderAdmissionDeferred
                ):
                    # This typed rejection is raised before transport and broker
                    # admission. It proves this attempt was never sent; actual
                    # provider failures keep their full uncertain reservation.
                    receipt = dict(
                        request_id=request_id,
                        schema_valid=False,
                        cost_with_vat_reserve_usd="0",
                        error=str(error),
                        dispatch_state="never_sent",
                        cost_source="physical_admission_denied",
                    )
                    if attempt == 0 and not self._dispatch_context.get()["transport_retries"]:
                        with sqlite3.connect(self.ledger, timeout=30) as db:
                            db.execute(
                                "UPDATE probe_calls SET committed='0',receipt=? "
                                "WHERE request_id=? AND receipt IS NULL",
                                (json.dumps(receipt, sort_keys=True), request_id),
                            )
                    raise ValueError(str(error)) from None
                code = str(error)
                if self.provider_resilience and (
                    code in ISOLATED_CODES | {"PROCESSING_UNCERTAIN", "OPENAI_REQUEST_FAILED"}
                    or code == "OPENAI_HTTP_403"
                    or re.fullmatch(r"OPENAI_HTTP_5\d\d", code)
                    or isinstance(error, OSError)
                    or (
                        self.response_uncertainty_policy
                        and isinstance(
                            error, json.JSONDecodeError | UnicodeError | http.client.HTTPException
                        )
                    )
                ):
                    raise ValueError("PROVIDER_PROCESSING_FAILED") from None
                if code not in {
                    f"OPENAI_HTTP_{n}" for n in (400, 401, 403, 404, 429, 500, 502, 503)
                } | {"OPENAI_INSUFFICIENT_QUOTA", "PROCESSING_UNCERTAIN", "PRICE_RECHECK_REQUIRED"}:
                    code = "OPENAI_REQUEST_FAILED"
                raise ValueError(code) from None
            try:
                usage = data["usage"]
                cost = token_cost(usage)
                incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
                choice = data["choices"][0]
                content = choice["message"]["content"]
                if (
                    data["model"] != MODEL
                    or type(incoming) is not int
                    or type(outgoing) is not int
                    or incoming < 0
                    or not 0 <= outgoing <= max_tokens
                    or not cost.is_finite()
                    or cost < 0
                    or not isinstance(content, str)
                    or not isinstance(data["id"], str)
                ):
                    raise ValueError
                if (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) != 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError, IndexError, InvalidOperation, AttributeError):
                raise ValueError("OPENAI_RECEIPT_INVALID_RESERVATION_RETAINED") from None
            total_cost += cost
            input_tokens += incoming
            output_tokens += outgoing
            attempts.append(
                {
                    "provider_request_id": data["id"],
                    "cost_usd": str(cost),
                    "response_sha256": canonical_hash(data),
                    "latency_ms": latency_ms,
                }
            )
            try:
                parsed = json.loads(content)
                if validator is not None:
                    validator.validate(parsed)
                valid = isinstance(parsed, dict) and choice["finish_reason"] == "stop"
            except (ValueError, TypeError, KeyError):
                valid = False
            except ValidationError:
                valid = False
            if valid or attempt == 1:
                break
        if total_cost > Decimal(POLICY["reservation_usd"]):
            raise ValueError("BUDGET_SETTLEMENT_INVALID")
        receipt = {
            "provider": "openai",
            "request_id": request_id,
            "endpoint": ENDPOINT,
            "model_binding_sha256": canonical_hash(self.wire_policy),
            "price_snapshot": self.wire_policy,
            "http_request_id": data.get("openai_request_id"),
            "model": MODEL,
            "provider_model": data["model"],
            "provider_request_id": data["id"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_with_vat_reserve_usd": str(total_cost),
            "cost_source": "official_token_prices_with_vat_reserve",
            "response_sha256": canonical_hash(data),
            "attempts": attempts,
            "schema_valid": valid,
            "response_format": {"type": "json_object"},
        }
        if self.wire_policy_version == 2:
            receipt["wire_policy"] = self.wire_policy
            details = usage.get("prompt_tokens_details") or {}
            receipt["cached_tokens"] = details.get("cached_tokens")
            receipt["cache_write_tokens"] = details.get("cache_write_tokens")
        if self.response_policy is not None:
            receipt["response_request"] = self._cache_request_context.get()
        scope = self._dispatch_context.get()
        if scope and scope["transport_retries"]:
            receipt["transport_retries"] = scope["transport_retries"]
        if self.transport_policy:
            receipt["connection_attempts"] = scope.get("connection_attempts", [])
        if getattr(self, "provider_scheduler", None):
            receipt["provider_scheduler"] = dict(
                policy_sha256=canonical_hash(self.provider_scheduler),
                local_reserved_monotonic=scope.get("local_reserved_monotonic"),
                attempts=scope.get("physical_attempts", []),
                receipt_persist_started_monotonic=time.monotonic(),
            )
        with sqlite3.connect(self.ledger) as db:
            changed = db.execute(
                "UPDATE probe_calls SET committed=?, receipt=? WHERE request_id=? "
                "AND receipt IS NULL AND committed=?",
                (
                    str(total_cost),
                    json.dumps(receipt, sort_keys=True),
                    request_id,
                    POLICY["reservation_usd"],
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("BUDGET_SETTLEMENT_INVALID")
        if self.transport_policy:
            with sqlite3.connect(self.ledger, timeout=30) as db:
                db.execute(
                    "UPDATE probe_transport_attempts SET state='settled' "
                    "WHERE request_id=? AND state='response_received'",
                    (request_id,),
                )
        return {**receipt, "content": content}
