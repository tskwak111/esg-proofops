"""Opt-in provider failover; original reservations and publication guards survive."""

import sqlite3
import time
from collections.abc import Callable
from contextvars import ContextVar
from http.client import HTTPException
from pathlib import Path
from threading import Lock
from typing import Any, cast

from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen
from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred
from proofops.domain.provenance import canonical_hash

from proofops_api.hosted_analysis import HostedLunaProbe, HostedOpenAILunaProbe


def fallback_trigger(error: BaseException) -> str | None:
    # Admission rejection is not an observed provider/network failure.
    if isinstance(error, ProviderCircuitOpen | ProviderAdmissionDeferred):
        return None
    if getattr(error, "provider_error_code", None) == "billing_not_active":
        return "billing_not_active"
    if isinstance(error, OSError | HTTPException) or str(error) in {
        "PROCESSING_UNCERTAIN",
        "OPENAI_CONNECT_NEVER_SENT",
    }:
        return "network_failure"
    if str(error) in {"OPENAI_HTTP_429", "OPENAI_HTTP_403"}:
        return "http_429_403_k3"
    return None


class FallbackState:
    """Shared by all model roles/replicas within one run, never across tenants."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.http_lock = Lock()
        self.consecutive = 0
        self.reason: str | None = None
        self.receipts: list[dict[str, Any]] = []
        self.last_dispatch = 0.0

    def observe(self, trigger: str | None) -> None:
        with self.lock:
            if trigger == "http_429_403_k3":
                self.consecutive += 1
                if self.consecutive >= 3:
                    self.reason = trigger
            elif trigger in {"billing_not_active", "network_failure"}:
                self.reason = trigger
            else:
                self.consecutive = 0

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return dict(
                profile="ops2_openrouter_fallback_v1",
                triggered_by=self.reason,
                primary_model="gpt-6-luna",
                fallback_model="openai/gpt-6-luna",
                model_family_changed=False,
                model_identifier_changed=bool(self.receipts),
                bounded_c3="openai_bound_only; fallback_cannot_confirm",
                provider_changed=bool(self.receipts),
                calls=list(self.receipts),
                recovered_primary_failures=sum(
                    receipt["recovered_primary_failures"] for receipt in self.receipts
                ),
                publication="existing_three_replica_authentication_required",
            )


class PacedFallbackProbe(HostedLunaProbe):
    def __init__(self, *args: Any, fallback_state: FallbackState, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fallback_state = fallback_state

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        state = self.fallback_state
        # Conservative serial fallback: every physical attempt remains brokered.
        with state.http_lock:
            time.sleep(max(0, state.last_dispatch + 0.25 - time.monotonic()))
            state.last_dispatch = time.monotonic()
            return super()._post(body)


class OPS2Probe(HostedOpenAILunaProbe):
    ops2_enabled = True

    def __init__(
        self,
        *args: Any,
        fallback_state: FallbackState,
        fallback_key: Callable[[], str],
        fallback_post: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.ops2_state = fallback_state
        self.ops2_key = fallback_key
        self.ops2_post = fallback_post
        self.ops2_failure: ContextVar[dict[str, Any] | None] = ContextVar(
            "ops2_failure", default=None
        )

    # Existing broker override intentionally omits the base transport-only keyword.
    def _post(self, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
        try:
            response = super()._post(body)
        except Exception as error:
            from proofops.adapters.local.i27_inventory_execution import current, transient_code

            # Optional SC1 timeouts/5xx stay local to the chunk. Billing and
            # 429/403 still follow the existing run-wide fallback policy.
            trigger = (
                None
                if current.get() is not None
                and (
                    # External API is untyped and outside this work package.
                    transient_code(error)  # type: ignore[no-untyped-call]
                    or cast(dict[str, Any], current.get())["terminal_code"]
                    == "SC1_PROVIDER_TIMEOUT"
                )
                else fallback_trigger(error)
            )
            # The scheduler has already closed each physical attempt. Retain
            # only this logical request's failures; other requests remain blocked.
            attempts = cast(dict[str, Any], self._dispatch_context.get() or {}).get(
                "physical_attempts", []
            )
            self.ops2_failure.set(
                dict(
                    trigger=trigger,
                    failed_calls=sum(attempt.get("error_code") is not None for attempt in attempts),
                )
                if trigger is not None
                else None
            )
            self.ops2_state.observe(trigger)
            raise
        self.ops2_state.observe(None)
        return response

    def complete(
        self, system: str, user_json: str, *, request_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        recovered = 0
        if self.ops2_state.reason is not None:
            with sqlite3.connect(self.ledger) as db:
                if db.execute(
                    "SELECT 1 FROM probe_calls WHERE request_id=?", (request_id,)
                ).fetchone():
                    raise ValueError("DUPLICATE_PROBE_REQUEST")
        if self.ops2_state.reason is None:
            token = self.ops2_failure.set(None)
            try:
                return cast(
                    dict[str, Any],
                    # External API is untyped and outside this work package.
                    super().complete(system, user_json, request_id=request_id, **kwargs),  # type: ignore[no-untyped-call]
                )
            except Exception:
                if self.ops2_failure.get() is None or self.ops2_state.reason is None:
                    raise
                recovered = cast(dict[str, Any], self.ops2_failure.get())["failed_calls"]
            finally:
                self.ops2_failure.reset(token)
        self._authorize_response_request()
        if self.response_policy is not None:
            role, replica = self._response_context.get() or (self.response_role, 0)
            if role != "extract" and replica not in (1, 2, 3):
                raise ValueError("MODEL_RESPONSE_REPLICA_REQUIRED")
        # Separate immutable adapter ledger; same hosted broker/run/day/event envelope.
        # No cache/replay: each replica keeps its own request ID and paid receipt.
        ledger = Path(str(self.ledger) + ".ops2-openrouter")
        probe = PacedFallbackProbe(
            self.ops2_key(),
            ledger,
            store=self.store,
            job=self.job,
            post=self.ops2_post,
            fallback_state=self.ops2_state,
        )
        # External API is untyped and outside this work package.
        result = probe.complete(system, user_json, request_id=request_id, **kwargs)  # type: ignore[no-untyped-call]
        with self.ops2_state.lock:
            self.ops2_state.receipts.append(
                dict(
                    request_id=request_id,
                    provider=result["provider"],
                    model=result["model"],
                    provider_request_id=result["provider_request_id"],
                    receipt_sha256=canonical_hash(
                        {k: v for k, v in result.items() if k != "content"}
                    ),
                    cost_usd=result["cost_with_vat_reserve_usd"],
                    recovered_primary_failures=recovered if result["schema_valid"] is True else 0,
                )
            )
        return cast(dict[str, Any], result)
