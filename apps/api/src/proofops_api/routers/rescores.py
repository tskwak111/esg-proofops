"""Rules-only rescore HTTP boundary; ready means a committed local rules batch."""

import sqlite3
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie
from proofops.application.rescores import RescoreRejected
from proofops.application.reviews import ReviewRejected
from proofops.application.runs import RunRejected
from proofops.domain.errors import DomainValidationError
from proofops_api.auth import (
    SESSION_COOKIE_NAME,
    _authorize,
    _error_response,
    _request_limit_response,
    _verify_csrf,
)
from proofops_api.middleware import RequestBodyTooLarge, read_bounded_json
from proofops_api.routers.documents import JobAccepted, StrictDTO, _request_schema
from proofops_api.rulepacks import _ERROR_RESPONSES
from pydantic import Field
from starlette.concurrency import run_in_threadpool


def _retag_required_message(service, tenant_id: str, run_id: str) -> str:
    """Return actionable, tenant-scoped guidance without changing rescore state."""
    claim_ids = []
    store = getattr(service, "store", None)
    jobs = getattr(store, "jobs", None)
    transaction = getattr(jobs, "_transaction", None)
    claims_reader = getattr(store, "_claims", None)
    claims = None
    if callable(transaction) and callable(claims_reader):
        try:
            with transaction() as db:
                claims = claims_reader(db, tenant_id, run_id)
            claim_ids = sorted(
                claim_id
                for claim_id, current in claims.items()
                if current["tag"].get("confirmed_tags") is None
            )
        except Exception:
            # Preserve the original guard response when this adapter cannot
            # provide a read-only claim snapshot.
            claims = None
    if claim_ids:
        return (
            "재채점이 보류되었습니다. 미확정 주장 ID: "
            + ", ".join(claim_ids)
            + ". 해당 주장을 다시 태깅하고 검토자가 확정한 뒤 재채점하세요."
        )
    if claims:
        return (
            "재채점이 보류되었습니다. 다시 태깅할 주장 ID: "
            + ", ".join(sorted(claims))
            + ". 해당 주장을 다시 태깅하고 검토자가 확정한 뒤 재채점하세요."
        )
    return (
        "재채점 가능한 공개 주장 head가 없거나 확인이 필요합니다. 주장 목록을 확인하고, "
        "필요한 주장을 다시 태깅한 뒤 검토자가 확정하고 재채점하세요."
    )


class RescoreCreate(StrictDTO):
    rule_pack_id: UUID
    reason: Annotated[str, Field(min_length=5, max_length=1000)]


def build_rescores_router(service, auth_store, *, allowed_origin: str, clock=time.time):
    router = APIRouter(
        responses=_ERROR_RESPONSES,
        dependencies=[
            Security(
                APIKeyCookie(
                    name=SESSION_COOKIE_NAME, scheme_name="sessionCookie", auto_error=False
                )
            )
        ],
    )

    @router.post(
        "/v1/runs/{run_id}/rescores",
        operation_id="rescore",
        status_code=202,
        response_model=JobAccepted,
        openapi_extra=_request_schema(RescoreCreate) | {"x-minimum-role": "reviewer"},
    )
    async def create(request: Request, run_id: UUID):
        now = clock()
        auth = _authorize(request, auth_store, now, "reviewer")
        if isinstance(auth, JSONResponse):
            return auth
        session = auth_store.sessions.get(auth.session_id)
        if session is None or not _verify_csrf(
            request, session.csrf_hash, allowed_origin=allowed_origin
        ):
            return _error_response(403, "CSRF_INVALID", "Invalid session or request origin.")
        limited = _request_limit_response(
            auth_store, user_sub=auth.user_sub, operation_id="rescore", requests=10, now=now
        )
        if limited is not None:
            return limited
        try:
            body = await read_bounded_json(request)
            result = await run_in_threadpool(
                service.create_rescore,
                auth,
                str(run_id),
                body,
                request.headers.get("Idempotency-Key"),
                request.headers.get("If-Match"),
            )
            return JSONResponse(result, status_code=202, headers={"Cache-Control": "no-store"})
        except (RescoreRejected, ReviewRejected, RunRejected) as error:
            message = (
                _retag_required_message(service, auth.tenant_id, str(run_id))
                if isinstance(error, RescoreRejected) and error.code == "RETAG_REQUIRED"
                else "Rescore could not be completed."
            )
            return _error_response(error.status, error.code, message)
        except (RequestBodyTooLarge, DomainValidationError, ValueError, TypeError):
            return _error_response(422, "VALIDATION_ERROR", "Invalid rescore request or inputs.")
        except sqlite3.DatabaseError:
            return _error_response(
                409, "RESCORE_CONFLICT", "Rescore transaction could not be committed."
            )

    @router.get(
        "/v1/runs/{run_id}/rescores/{rescore_id}",
        operation_id="rescore_get",
        response_model=JobAccepted,
        openapi_extra={
            "x-minimum-role": "viewer",
            "x-rate-limit": "120/min/user",
            "x-idempotency-required": False,
        },
    )
    def get(request: Request, run_id: UUID, rescore_id: UUID):
        now = clock()
        auth = _authorize(request, auth_store, now, "viewer")
        if isinstance(auth, JSONResponse):
            return auth
        limited = _request_limit_response(
            auth_store, user_sub=auth.user_sub, operation_id="rescore_get", requests=120, now=now
        )
        if limited is not None:
            return limited
        try:
            result = service.store.get(auth.tenant_id, str(run_id), str(rescore_id))
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except RescoreRejected as error:
            return _error_response(error.status, error.code, "Rescore not available.")
        except sqlite3.DatabaseError:
            return _error_response(409, "RESCORE_CONFLICT", "Rescore not available.")

    return router
