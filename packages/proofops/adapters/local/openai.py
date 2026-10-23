"""Budgeted direct OpenAI chat transport; shares the existing USD3 Decisions ledger."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from proofops.adapters.local.openai_connections import OpenAIConnections
import hashlib as hashlib
import http as http
import http.client
import json as json
import math
import os as os
import re as re
import sqlite3
import time as time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4 as uuid4

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from proofops.adapters.local import openai_http
from proofops.adapters.local.decisions import OPENAI_POLICY as POLICY
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.adapters.local.sqlite_busy import connection
from proofops.application.openai_retry import POLICY as _HTTP_RETRY_POLICY
from proofops.application.openai_retry import POLICY_HASH as HTTP_RETRY_POLICY_HASH
from proofops.domain.provenance import canonical_hash as canonical_hash

# Ledger policy remains byte-identical to existing Decisions policy: never reset spend.

HTTP_RETRY_POLICY: dict[str, Any] = _HTTP_RETRY_POLICY

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/chat/completions"
PRICE_RECHECK_AT = datetime(2026, 10, 21, tzinfo=UTC)
PRICE = {"input": "0.10", "cached_input": "0.01", "cache_write": "0.125", "output": "0.50"}
HTTP_ERROR_POLICY: dict[str, Any] = {
    "schema": "openai-http-error-diagnostic-t1-v2",
    "body": "bounded-sha256-only",
    "identifiers": "bounded-snake-case-no-key",
    "headers": ["x-request-id", "retry-after", "server", "content-type", "cf-ray"],
    "context": "utc-wire-bytes-model-local-request-admission-latency",
    "storage": "private-immutable-sidecar-best-effort",
}
WIRE_POLICY: dict[str, Any] = {
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
CAPACITY_POLICY: dict[str, Any] = {
    "schema": "openai-luna-input-reservation-v1",
    "model_id": MODEL,
    "reservation_input_tokens": 32768,
    "request_bytes": 16384,
    "model_binding_sha256": canonical_hash(WIRE_POLICY),
}


def now() -> datetime:
    return datetime.now(UTC)


class OpenAITransient403(ValueError):
    """Explicit overload evidence, never created for an opaque denial."""

    def __init__(self, *, delay: float, diagnostic: dict[str, Any]) -> None:
        super().__init__("OPENAI_HTTP_403")
        self.retry_after_seconds = delay
        self.diagnostic = diagnostic
        self.policy_sha256 = HTTP_RETRY_POLICY_HASH


def _retry_after(value: object) -> float | None:
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


def validate_capacity_policy(policy: object, *, model_id: str) -> int:
    if model_id != MODEL or policy != CAPACITY_POLICY:
        raise ValueError("OPENAI_CAPACITY_POLICY_MISMATCH")
    if now() >= PRICE_RECHECK_AT:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    return cast(int, CAPACITY_POLICY["reservation_input_tokens"])


def token_cost(usage: dict[str, Any]) -> Decimal:
    incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_write_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (incoming, outgoing, cached, written)):
        raise ValueError("INVALID_USAGE")
    if incoming > 32768 or cached + written > incoming:
        raise ValueError("INVALID_USAGE")
    cost: Decimal = (
        (
            (incoming - cached - written) * Decimal(PRICE["input"])
            + cached * Decimal(PRICE["cached_input"])
            + written * Decimal(PRICE["cache_write"])
            + outgoing * Decimal(PRICE["output"])
        )
        / Decimal(1000000)
        * Decimal("1.10")
    )

    return cost


class OpenAIProbe(OpenRouterProbe):
    _response_context: ContextVar[tuple[str, int] | None] = ContextVar(
        "openai_response_context", default=None
    )
    _cache_request_context: ContextVar[dict[str, Any] | None] = ContextVar(
        "openai_cache_request_context", default=None
    )
    _dispatch_context: ContextVar[dict[str, Any] | None] = ContextVar(
        "openai_dispatch_context", default=None
    )
    response_cache_path: Path | None = None
    response_policy: dict[str, Any] | None = None
    wire_policy = WIRE_POLICY
    http_retry_policy: dict[str, Any] | None = None
    provider_resilience: dict[str, Any] | None = None
    http_dispatch_guard = False
    response_uncertainty_policy: dict[str, Any] | None = None
    http_diagnostic_policy: dict[str, Any] | None = None
    transport_policy: dict[str, Any] | None = None
    connection_pool: OpenAIConnections | None = None
    max_request_bytes = WIRE_POLICY["max_request_bytes"]
    rate_limit_headers: dict[str, str | None]
    provider_scheduler: dict[str, Any] | None

    if TYPE_CHECKING:
        # Supplied by hosted subclasses only; keep optional runtime hooks absent here.
        def http_attempt_scope(self) -> AbstractContextManager[object]: ...
        def http_transport_pacing(self) -> None: ...
        def http_admission_snapshot(self) -> dict[str, Any]: ...
        def http_recent_request_counts(self) -> dict[str, Any]: ...

    def _authorize_response_request(self) -> None:
        """Hosted adapters recheck their live owner/source before cache access."""

    def configure_response_policy(self, snapshot: dict[str, Any], *, role: str) -> None:
        from proofops.application.analysis_profile import MODEL_RESPONSE_POLICY

        policy = snapshot.get("analysis_profile_policy", {})
        from proofops.application.fxh_policy import POLICY as FXH_POLICY
        from proofops.application.fxh_policy import enabled as fxh_enabled

        # Untyped dependency is outside S_ADB ownership.
        fxh = fxh_enabled(policy)  # type: ignore[no-untyped-call]
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
            with connection(self.ledger) as db:
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
    def response_context(self, *, role: str, replica: int) -> Iterator[None]:
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

    def __init__(
        self, api_key: str, ledger: Path, *, model: str = MODEL, wire_policy_version: int = 2
    ) -> None:
        if model != MODEL:
            raise ValueError("UNSUPPORTED_MODEL")
        if not api_key or any(c.isspace() for c in api_key):
            raise ValueError("OPENAI_API_KEY_MISSING_OR_INVALID")
        if wire_policy_version != 2:
            raise ValueError("OPENAI_WIRE_POLICY_INVALID")
        self.model, self._key, self.ledger = model, api_key, Path(ledger)
        self.wire_policy_version = wire_policy_version
        self.ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with connection(self.ledger) as db:
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

    def _total(self, db: sqlite3.Connection) -> Decimal:
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

    def summary(self) -> dict[str, Any]:
        with connection(self.ledger, readonly=True) as db:
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

    request_body = openai_http.request_body

    _record_http_error = openai_http._record_http_error

    def physical_attempt_scope(self) -> AbstractContextManager[object]:
        if getattr(self, "provider_scheduler", None) is None:
            return nullcontext()
        if not hasattr(self, "http_attempt_scope"):
            raise ValueError("PROVIDER_SCHEDULER_BINDING_REQUIRED")
        return self.http_attempt_scope()

    def _post(
        self, body: dict[str, Any], *, client_request_id: str | None = None
    ) -> dict[str, Any]:
        from proofops.adapters.local.openai_connections import (
            OpenAIConnectNotSent,
            OpenAIControlNotSent,
        )

        # Hosted transport has already admitted before its broker reservation.
        scope = self.physical_attempt_scope() if client_request_id is None else nullcontext()
        if not self.transport_policy or client_request_id is not None:
            try:
                with scope:
                    return self._post_admitted(body, client_request_id=client_request_id)
            except OpenAIControlNotSent as error:
                if client_request_id is None:
                    raise error.signal from None
                raise  # The hosted broker still needs the pre-send proof.
        from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen
        from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred

        dispatch = cast(dict[str, Any], self._dispatch_context.get())
        for attempt in range(2):
            attempt_id = str(uuid4())
            # A distinct physical reservation is bounded by the still-reserved
            # logical USD.02 envelope. The first proven-unsent attempt costs zero.
            # No two possibly delivered attempts share this retry authorization.
            with connection(self.ledger) as db:
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
            except OpenAIControlNotSent as error:
                self._finish_transport_attempt(attempt_id, "never_sent", None)
                self._settle_never_sent(dispatch["request_id"])
                raise error.signal from None
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

    def _finish_transport_attempt(
        self, attempt_id: str, state: str, diagnostic: str | None
    ) -> None:
        with connection(self.ledger) as db:
            db.execute(
                "UPDATE probe_transport_attempts SET state=?,diagnostic=? "
                "WHERE attempt_id=? AND state='reserved'",
                (state, diagnostic, attempt_id),
            )

    def _settle_never_sent(self, request_id: str) -> None:
        with connection(self.ledger) as db:
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

    _post_admitted = openai_http._post_admitted

    def complete(
        self,
        system: str,
        user_json: str,
        *,
        request_id: str,
        max_tokens: int = 1024,
        json_mode: bool = False,
        schema_json: str | None = None,
    ) -> dict[str, Any]:
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
        with connection(self.ledger, readonly=True) as db:
            if db.execute("SELECT 1 FROM probe_calls WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError("DUPLICATE_PROBE_REQUEST")
        self._authorize_response_request()
        # Untyped dependency is outside S_ADB ownership.
        cache = ModelResponseCache(  # type: ignore[no-untyped-call]
            self.response_cache_path or self.ledger.parent / "model-responses.sqlite3"
        )
        # Untyped dependency is outside S_ADB ownership.
        hit = cache.claim(key, self.ledger, request_id)  # type: ignore[no-untyped-call]
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
            with connection(self.ledger) as db:
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
            return cast("dict[str, Any]", result)
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
                # Untyped dependency is outside S_ADB ownership.
                cache.publish(key, result)  # type: ignore[no-untyped-call]
            else:
                # Untyped dependency is outside S_ADB ownership.
                cache.release_unsent_or_invalid(key, self.ledger, request_id)  # type: ignore[no-untyped-call]
            return result
        except Exception:
            # Untyped dependency is outside S_ADB ownership.
            cache.release_unsent_or_invalid(key, self.ledger, request_id)  # type: ignore[no-untyped-call]
            raise
        finally:
            self._cache_request_context.reset(context_token)

    def _complete_uncached(
        self,
        system: str,
        user_json: str,
        *,
        request_id: str,
        max_tokens: int = 1024,
        json_mode: bool = False,
        schema_json: str | None = None,
    ) -> dict[str, Any]:
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
        self,
        system: str,
        user_json: str,
        *,
        request_id: str,
        max_tokens: int = 1024,
        json_mode: bool = False,
        schema_json: str | None = None,
    ) -> dict[str, Any]:
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
        with connection(self.ledger) as db:
            if db.execute("SELECT 1 FROM probe_calls WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError("DUPLICATE_PROBE_REQUEST")
            if self._total(db) + Decimal(POLICY["reservation_usd"]) > Decimal(POLICY["limit_usd"]):
                raise ValueError("BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO probe_calls VALUES (?,?,?,NULL)",
                (request_id, canonical_hash(body), POLICY["reservation_usd"]),
            )
        if getattr(self, "provider_scheduler", None):
            cast(dict[str, Any], self._dispatch_context.get())["local_reserved_monotonic"] = (
                time.monotonic()
            )
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
                from proofops.application.ports.jobs import LeaseLost
                from proofops.application.provider_resilience import ISOLATED_CODES

                if isinstance(error, BudgetExceeded | LeaseLost):
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
                    if (
                        attempt == 0
                        and not cast(dict[str, Any], self._dispatch_context.get())[
                            "transport_retries"
                        ]
                    ):
                        with connection(self.ledger) as db:
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
        scope = cast(dict[str, Any], self._dispatch_context.get())
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
        with connection(self.ledger) as db:
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
            with connection(self.ledger) as db:
                db.execute(
                    "UPDATE probe_transport_attempts SET state='settled' "
                    "WHERE request_id=? AND state='response_received'",
                    (request_id,),
                )
        return {**receipt, "content": content}
