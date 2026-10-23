"""Hosted money; every operation uses the facade's shared transaction context."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from decimal import Decimal
from http.client import HTTPException
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from proofops.adapters.local.provider_errors import provider_error_code

from proofops_api.hosted_contracts import (
    PROVIDER_LIMIT_CODES,
    PROVIDER_LIMIT_MESSAGE,
    TERMINAL,
    HostedError,
    micros,
    usd,
)

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore


def dispatch(
    store: HostedStore,
    job: dict[str, Any],
    provider: str,
    call_id: str,
    input_sha: str,
    bound: Decimal,
    transport: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    now: float,
    allow_transient_403: bool = False,
    allow_model_partial: bool = False,
    allow_response_uncertainty: bool = False,
    allow_connect_not_sent: bool = False,
    allow_ops2_fallback: bool = False,
    diagnostic_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Broker boundary for a future approved adapter. No HTTP/provider implementation here."""
    if (
        not provider
        or not call_id
        or len(input_sha) != 64
        or any(c not in "0123456789abcdef" for c in input_sha)
    ):
        raise HostedError("DISPATCH_INVALID", 422)
    reserved = micros(bound)
    if reserved <= 0:
        raise HostedError("DISPATCH_INVALID", 422)
    phase = "reservation"
    try:
        started = time.monotonic()
        with store.transaction(lock_wait_seconds=30, operation="dispatch_reserve") as db:
            row = store._fenced(db, job, now + time.monotonic() - started)
            if db.execute(
                "SELECT 1 FROM deletion.costs WHERE run_id=? AND call_id=?",
                (job["run_id"], call_id),
            ).fetchone():
                raise HostedError("DISPATCH_ALREADY_RECORDED")
            total = db.execute(
                "SELECT coalesce(sum(CASE WHEN status='settled' THEN actual ELSE bound END),0) "
                "FROM deletion.costs WHERE run_id=?",
                (job["run_id"],),
            ).fetchone()[0]
            if total + reserved > row["envelope"]:
                raise HostedError("BUDGET_EXCEEDED", 429)
            request = {
                "request_id": str(uuid4()),
                "provider": provider,
                "input_sha256": input_sha,
            }
            db.execute(
                "INSERT INTO deletion.costs VALUES (?,?,?,?,?,?,NULL,'reserved',?)",
                (
                    job["run_id"],
                    call_id,
                    request["request_id"],
                    provider,
                    input_sha,
                    reserved,
                    now,
                ),
            )
        phase = "transport"
        response = transport(request)
        phase = "receipt_validation"
        if any(response.get(k) != v for k, v in request.items()):
            raise HostedError("RECEIPT_MISMATCH")
        actual = micros(response["actual_usd"])
        if actual > reserved:
            raise HostedError("RECEIPT_BOUND_EXCEEDED")
        phase = "settlement"
        # A response and its cost already exist; tolerate the same bounded
        # writer contention as lease renewal without replaying transport.
        with store.transaction(lock_wait_seconds=30, operation="dispatch_settle") as db:
            db.execute(
                "INSERT INTO ops2_provider_observations VALUES (?,?,NULL) "
                "ON CONFLICT(provider) DO UPDATE SET observed=excluded.observed,"
                "error_code=NULL "
                "WHERE excluded.observed>=ops2_provider_observations.observed",
                (provider, time.time()),
            )
            # A late cancelled/deleted result may settle money, but cannot publish payload.
            db.execute(
                "UPDATE deletion.costs SET actual=?,status='settled' "
                "WHERE run_id=? AND call_id=? "
                "AND status='reserved'",
                (actual, job["run_id"], call_id),
            )
            state = db.execute(
                "SELECT status FROM runs WHERE run_id=?", (job["run_id"],)
            ).fetchone()
            if state is None or state[0] in TERMINAL:
                store._settle_envelope(db, job["run_id"])
        return response
    except BaseException as exc:
        from proofops_api.hosted_diagnostics import record_dispatch_failure

        record_dispatch_failure(
            store, job, call_id, provider, input_sha, phase, exc, diagnostic_context
        )
        if phase == "reservation":
            # Admission failed before transport. Preserve its original error
            # and all money/ownership state; diagnostics never authorize retry.
            raise
        # A rejected quota call is terminal, but its unknown cost still needs
        # operator reconciliation. Never release reservations or redeliver it.
        limit_code = str(exc)
        observation_code = (
            "OPENAI_INSUFFICIENT_QUOTA"
            if provider == "openai"
            and getattr(exc, "provider_error_code", None) == "billing_not_active"
            else limit_code
        )
        quota_blocked = limit_code in PROVIDER_LIMIT_CODES.get(provider, ())
        from proofops_api.hosted_ops2 import fallback_trigger

        ops2_failure = (
            allow_ops2_fallback is True and provider == "openai" and bool(fallback_trigger(exc))
        )
        # External API is untyped and outside this work package.
        cause = provider_error_code(provider, limit_code)  # type: ignore[no-untyped-call]
        if cause:
            logging.getLogger("proofops_api.hosted_store").warning(
                "hosted provider failure run=%s provider=%s cause=%s raw=%s",
                job["run_id"],
                provider,
                cause,
                limit_code
                if limit_code.startswith(("UPSTAGE_", "OPENAI_", "OPENROUTER_"))
                else cause,
            )
        # An uncertain model transport is a per-claim hold, not a lost run fence.
        # Unknown receipts and non-model failures retain the existing terminal guard.
        from proofops.adapters.local.openai import OpenAITransient403
        from proofops.adapters.local.openai_connections import (
            OpenAIConnectNotSent,
            OpenAIControlNotSent,
        )

        if (
            phase == "transport"
            and provider == "openai"
            and (
                isinstance(exc, OpenAIControlNotSent)
                or (allow_connect_not_sent is True and isinstance(exc, OpenAIConnectNotSent))
            )
        ):
            # This typed proof originates exclusively before HTTP request().
            # Settle only this reservation. Control stops propagate without retry;
            # a connect retry still needs its existing policy and a new call_id.
            with store.transaction(lock_wait_seconds=30) as db:
                db.execute(
                    "UPDATE deletion.costs SET actual=0,status='settled' "
                    "WHERE run_id=? AND call_id=? AND status='reserved'",
                    (job["run_id"], call_id),
                )
            raise
        transient_denial = (
            allow_transient_403 is True
            and provider == "openai"
            and isinstance(exc, OpenAITransient403)
        )
        model_network_failure = provider in {"openai", "openrouter"} and (
            isinstance(exc, OSError) or limit_code == "PROCESSING_UNCERTAIN"
        )
        isolated_model_failure = (
            allow_model_partial is True
            and provider == "openai"
            and (
                cause in {"PROVIDER_ACCESS_DENIED", "PROVIDER_UNAVAILABLE"}
                or model_network_failure
                or (
                    allow_response_uncertainty is True
                    and isinstance(exc, json.JSONDecodeError | UnicodeError | HTTPException)
                )
            )
        )
        with store.transaction(lock_wait_seconds=30) as db:
            if observation_code in PROVIDER_LIMIT_CODES.get(provider, ()):
                db.execute(
                    "INSERT INTO ops2_provider_observations VALUES (?,?,?) "
                    "ON CONFLICT(provider) DO UPDATE SET observed=excluded.observed,"
                    "error_code=excluded.error_code "
                    "WHERE excluded.observed>=ops2_provider_observations.observed",
                    (provider, time.time(), observation_code),
                )
            db.execute(
                "UPDATE deletion.costs SET status='accounting_pending' "
                "WHERE run_id=? AND call_id=? "
                "AND status='reserved'",
                (job["run_id"], call_id),
            )
            if (
                not ops2_failure
                and not model_network_failure
                and not transient_denial
                and not isolated_model_failure
            ):
                db.execute(
                    "UPDATE runs SET "
                    "status=?,fence=fence+1,error_code=?,lease_until=0 "
                    "WHERE run_id=? AND status='running' AND fence=?",
                    (
                        "failed" if quota_blocked else "accounting_pending",
                        limit_code if quota_blocked else cause or "ACCOUNTING_PENDING",
                        job["run_id"],
                        job["fence"],
                    ),
                )
            db.execute(
                "UPDATE deletion.spend SET status='accounting_pending' WHERE run_id=?",
                (job["run_id"],),
            )
        if model_network_failure:
            raise HostedError("PROCESSING_UNCERTAIN") from None
        raise


def _settle_envelope(store: HostedStore, db: sqlite3.Connection, run: str) -> None:
    unknown = db.execute(
        "SELECT 1 FROM deletion.costs WHERE run_id=? AND status!='settled'", (run,)
    ).fetchone()
    if unknown:
        db.execute("UPDATE deletion.spend SET status='accounting_pending' WHERE run_id=?", (run,))
    else:
        actual = db.execute(
            "SELECT coalesce(sum(actual),0) FROM deletion.costs WHERE run_id=?", (run,)
        ).fetchone()[0]
        db.execute(
            "UPDATE deletion.spend SET amount=?,status='settled' WHERE run_id=?", (actual, run)
        )


def finish(store: HostedStore, job: dict[str, Any], status: str, *, now: float) -> None:
    if status not in TERMINAL or status == "completed":
        # Completion is available only through fenced analysis artifact publication.
        raise HostedError("ANALYSIS_RESULT_UNAVAILABLE")
    with store.transaction() as db:
        store._fenced(db, job, now)
        db.execute(
            "UPDATE runs SET status=?,lease_until=0,error_code=? WHERE run_id=?",
            (
                status,
                "LIVE_BINDING_UNAVAILABLE" if status == "partial_blocked" else None,
                job["run_id"],
            ),
        )
        store._settle_envelope(db, job["run_id"])


def budget_totals(store: HostedStore) -> dict[str, Any]:
    with store.transaction(readonly=True) as db:
        total = db.execute(
            "SELECT coalesce(sum(amount),0) FROM deletion.spend WHERE event_id=?",
            (store.settings.event_id,),
        ).fetchone()[0]
        archived = db.execute(
            "SELECT amount FROM deletion.event_totals WHERE event_id=?",
            (store.settings.event_id,),
        ).fetchone()
        total += archived[0] if archived else 0
    return {"event_reserved_usd": usd(total)}


def provider_limits(store: HostedStore) -> dict[str, Any]:
    """Observed service availability only; never probe providers on public GETs."""
    limits = {}
    with store.transaction(readonly=True) as db:
        for provider, codes in PROVIDER_LIMIT_CODES.items():
            parameters = tuple(sorted(codes))
            placeholders = ",".join("?" for _ in parameters)
            row = db.execute(
                f"SELECT error_code,created FROM runs WHERE error_code IN ({placeholders}) "
                "ORDER BY created DESC,run_id DESC LIMIT 1",
                parameters,
            ).fetchone()
            observed = db.execute(
                "SELECT error_code,observed FROM ops2_provider_observations WHERE provider=?",
                (provider,),
            ).fetchone()
            recovered = bool(
                observed and observed[0] is None and (row is None or observed[1] >= row[1])
            )
            if observed and observed[0] in codes and (row is None or observed[1] >= row[1]):
                row = observed
            if recovered:
                row = None
            limits[provider] = {
                "status": "blocked" if row else "available" if recovered else "unknown",
                "error_code": row[0] if row else None,
                "remaining_usd": None,
                "source": "observed_http_failure"
                if row
                else "observed_http_success"
                if recovered
                else "not_queried",
                "retryable": False,
                "message": PROVIDER_LIMIT_MESSAGE if row else None,
            }
    return limits
