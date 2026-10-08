"""Explicit hosted FastAPI composition. No local adapter, OIDC seed or paid transport."""

import asyncio
import fcntl
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from proofops.application.authorization import (
    AuthContext,
    CapabilityDeniedError,
    SessionExpiredError,
    TenantNotFoundError,
    authorize,
    get_live_session,
    select_tenant,
)
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from proofops_api.auth import SESSION_COOKIE_NAME, AuthStore, _epoch_to_rfc3339
from proofops_api.hosted_store import HostedError, HostedSettings, HostedStore
from proofops_api.middleware import BrowserSecurityHeadersMiddleware, verify_csrf

UPLOAD_NOTICE = (
    "업로드한 원본 PDF는 이 서버에서 7일 동안 보관한 뒤 자동 삭제합니다. "
    "업로더 본인과 관리자는 보관 기간이 끝나기 전에 삭제를 요청할 수 있습니다. "
    "외부 분석 전송 범위는 선택한 최대 2쪽이며, 현재 유료 분석은 비활성화되어 있습니다."
)


class Invitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: Annotated[str, Field(min_length=32, max_length=128)]


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    selected_pages: (
        Annotated[list[Annotated[int, Field(strict=True)]], Field(min_length=1, max_length=2)]
        | None
    ) = None


class TenantSelect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID


class DeletionReason(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Annotated[str, Field(min_length=5, max_length=1000)]


class BodyLimitMiddleware:
    """Enforce actual receive bytes even for chunked or misleading declared lengths."""

    def __init__(self, app: Any, maximum: int, data_dir: Any):
        self.app, self.maximum, self.data_dir = app, maximum, data_dir
        self.inflight: set = set()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        maximum = self.maximum if scope["path"] == "/v1/documents" else 65536
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = -1
        if length < 0 or length > maximum:
            response = JSONResponse({"error": {"code": "PAYLOAD_TOO_LARGE"}}, status_code=413)
            await response(scope, receive, send)
            return
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise HostedError("PAYLOAD_TOO_LARGE", 413)
            return message

        if scope["method"] != "POST" or scope["path"] != "/v1/documents":
            await self.app(scope, bounded_receive, send)
            return
        # One cross-process upload/validator slot bounds body copies + child RSS
        # on the4GiB host; the independent analysis worker may still prepare pages.
        lease = (self.data_dir / "upload.lock").open("a+b")
        os.fchmod(lease.fileno(), 0o600)
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease.close()
            response = JSONResponse(
                {"error": {"code": "UPLOAD_BUSY"}}, status_code=429, headers={"Retry-After": "1"}
            )
            await response(scope, receive, send)
            return

        async def admitted():
            try:
                await self.app(scope, bounded_receive, send)
            finally:
                lease.close()

        def finished(task):
            self.inflight.discard(task)
            if not task.cancelled():
                task.exception()

        task = asyncio.create_task(admitted())
        self.inflight.add(task)
        task.add_done_callback(finished)
        # A disconnect cannot free the slot while a native/subprocess validator
        # is still working in the request's threadpool.
        await asyncio.shield(task)


def create_hosted_app(settings: HostedSettings | None = None) -> FastAPI:
    settings = settings or HostedSettings.from_env(os.environ)
    store = HostedStore(settings)
    auth_store = AuthStore(sessions=store.sessions, memberships=store.memberships)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(store.maintain, now=time.time())

        async def maintenance():
            while True:
                await asyncio.sleep(60)
                await run_in_threadpool(store.maintain, now=time.time())

        task = asyncio.create_task(maintenance())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="ProofOps Hosted API", version="1.1.0", lifespan=lifespan)
    app.state.composition = store
    app.state.auth_store = auth_store
    app.add_middleware(
        BodyLimitMiddleware, maximum=settings.max_upload_bytes, data_dir=settings.root
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "If-Match"],
        expose_headers=["Retry-After"],
    )
    app.add_middleware(BrowserSecurityHeadersMiddleware)

    @app.exception_handler(HostedError)
    async def hosted_error(request: Request, exc: HostedError):
        return JSONResponse(
            {"error": {"code": exc.code}},
            status_code=exc.status,
            headers={"Retry-After": "60"} if exc.status == 429 else {},
        )

    @app.exception_handler(sqlite3.DatabaseError)
    @app.exception_handler(OSError)
    async def storage_error(request: Request, exc: Exception):
        return JSONResponse({"error": {"code": "DEPENDENCY_UNAVAILABLE"}}, status_code=503)

    def current(request: Request) -> AuthContext:
        try:
            sid = request.cookies.get(SESSION_COOKIE_NAME, "")
            now = time.time()
            capability = "viewer" if request.method == "GET" else "editor"
            if request.url.path.endswith("/deletion-requests"):
                capability = "viewer"
            if request.url.path.endswith("/resolve"):
                capability = "reviewer"
            if request.url.path in {"/v1/auth/logout", "/v1/session/tenant"}:
                capability = "viewer"
            auth = authorize(
                session_id=sid,
                now=now,
                session_port=store.sessions,
                membership_port=store.memberships,
                required_capability=capability,
            )  # type: ignore[arg-type]
            session = store.sessions.get(sid)
            if request.method != "GET" and (
                session is None
                or not verify_csrf(
                    origin=request.headers.get("Origin"),
                    csrf_token=request.headers.get("X-CSRF-Token"),
                    csrf_hash=session.csrf_hash,
                    allowed_origin=settings.origin,
                )
            ):
                raise HostedError("CSRF_INVALID", 403)
            store.consume(
                auth.user_sub + (":read" if request.method == "GET" else ":write"),
                60 if request.method == "GET" else 10,
                now,
            )
            store.sessions.touch(sid, now)
            return auth
        except SessionExpiredError:
            raise HostedError("AUTH_REQUIRED", 401) from None
        except CapabilityDeniedError:
            raise HostedError("FORBIDDEN", 403) from None
        except TenantNotFoundError:
            raise HostedError("RESOURCE_NOT_FOUND", 404) from None

    def session_body(sid: str) -> dict:
        record = get_live_session(session_id=sid, now=time.time(), session_port=store.sessions)
        membership = store.memberships.get(record.active_tenant_id or "", record.user_sub)
        return {
            "user_id": record.user_sub,
            "tenant_id": record.active_tenant_id,
            "role": membership.role if membership else None,
            "csrf_token": store.sessions.csrf_token_for(sid),
            "expires_at": _epoch_to_rfc3339(record.expires_at),
        }

    def set_cookie(response: Response, sid: str) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME, sid, secure=True, httponly=True, samesite="lax", path="/"
        )

    @app.post("/v1/auth/invitation")
    def redeem(body: Invitation, request: Request, response: Response) -> dict:
        if request.headers.get("Origin") != settings.origin:
            raise HostedError("CSRF_INVALID", 403)
        store.consume("invitation-login", 10, time.time())
        sid = store.redeem(body.code, now=time.time())
        set_cookie(response, sid)
        return session_body(sid)

    @app.get("/v1/session")
    def session(request: Request, auth: Annotated[AuthContext, Depends(current)]) -> dict:
        return session_body(auth.session_id)

    @app.post("/v1/auth/logout", status_code=204)
    def logout(response: Response, auth: Annotated[AuthContext, Depends(current)]) -> None:
        store.sessions.revoke(auth.session_id)
        response.delete_cookie(
            SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
        )

    @app.post("/v1/session/tenant")
    def switch(
        body: TenantSelect, response: Response, auth: Annotated[AuthContext, Depends(current)]
    ) -> dict:
        try:
            selected = select_tenant(
                session_id=auth.session_id,
                tenant_id=str(body.tenant_id),
                now=time.time(),
                session_port=store.sessions,
                membership_port=store.memberships,
            )
        except TenantNotFoundError:
            raise HostedError("RESOURCE_NOT_FOUND", 404) from None
        set_cookie(response, selected.session_id)
        return session_body(selected.session_id)

    @app.get("/v1/runtime")
    def runtime() -> dict:
        from proofops_api.hosted_analysis import runtime_profiles

        profiles = runtime_profiles(settings)
        return {
            "app_env": "hosted",
            "profile": "r108-hosted-sprint5-v1",
            "analysis_backend": settings.backend,
            "accept_new_runs": settings.accept_runs,
            "accept_uploads": settings.accept_uploads,
            "live_disabled": settings.live_disabled,
            "live_analysis": not settings.live_disabled
            and profiles["source_reader"] != "unresolved",
            "source_verifier": profiles["source_reader"],
            "analysis_profile": profiles["analysis_profile"],
            "rendered_reader_gate_report_sha256": profiles["rendered_reader_gate_report_sha256"],
            "delete_policy": "uploader_or_admin",
            "review_role": "reviewer",
            "result_schema": "r108-hosted-result-v1",
            "upload_notice": UPLOAD_NOTICE
            if settings.live_disabled
            else UPLOAD_NOTICE.replace(
                "현재 유료 분석은 비활성화되어 있습니다.",
                "운영자 설정에 따라 Upstage·OpenRouter로 분석을 전송합니다.",
            ),
            "consent_version": settings.consent_version,
            "limits": {
                "max_upload_bytes": settings.max_upload_bytes,
                "max_pdf_pages": 300,
                "selected_pages": 2,
                "active": 1,
                "queued": 8,
                "user_outstanding": 1,
                "run_usd": str(settings.run_usd),
                "day_usd": str(settings.day_usd),
                "event_usd": str(settings.event_usd),
                "original_days": settings.active_days,
                "backup_days": settings.backup_days,
                "audit_days": settings.audit_days,
            },
        }

    @app.get("/v1/health/live")
    def live() -> dict:
        return {"status": "ok", "app_env": "hosted"}

    @app.get("/v1/health/ready")
    def ready() -> dict:
        from proofops_api.hosted_analysis import runtime_profiles

        with store.transaction() as db:
            db.execute("SELECT version FROM hosted_schema").fetchone()
            failed = db.execute("SELECT 1 FROM deletion.attempts WHERE status='failed'").fetchone()
        return {
            "status": "not_ready" if failed else "ok",
            "control_plane": not bool(failed),
            "live_analysis": not settings.live_disabled
            and runtime_profiles(settings)["source_reader"] != "unresolved",
            "checks": ["sqlite", "durable_auth", "purge_guards", "hosted_broker"],
        }

    @app.post("/v1/documents", status_code=201)
    async def upload(request: Request, auth: Annotated[AuthContext, Depends(current)]) -> dict:
        if not settings.accept_uploads:
            raise HostedError("UPLOAD_DISABLED", 503)
        if request.headers.get("Content-Type", "").split(";")[0] != "application/pdf":
            raise HostedError("PDF_CONTENT_TYPE_REQUIRED", 415)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > settings.max_upload_bytes:
                raise HostedError("PAYLOAD_TOO_LARGE", 413)
            data.extend(chunk)
        return await run_in_threadpool(
            store.upload,
            auth,
            bytes(data),
            request.headers.get("Idempotency-Key", ""),
            now=time.time(),
        )

    @app.get("/v1/documents/{document_id}")
    def document(document_id: UUID, auth: Annotated[AuthContext, Depends(current)]) -> dict:
        return store.get_document(auth.tenant_id, str(document_id))

    @app.post("/v1/runs", status_code=202)
    def run_create(
        body: RunCreate, request: Request, auth: Annotated[AuthContext, Depends(current)]
    ) -> dict:
        return store.create_run(
            auth,
            str(body.document_id),
            body.selected_pages,
            request.headers.get("Idempotency-Key", ""),
            now=time.time(),
        )

    @app.get("/v1/runs/{run_id}")
    def run_get(run_id: UUID, auth: Annotated[AuthContext, Depends(current)]) -> dict:
        return store.get_run(auth.tenant_id, str(run_id))

    @app.get("/v1/runs/{run_id}/result")
    def result(run_id: UUID, auth: Annotated[AuthContext, Depends(current)]) -> dict:
        return store.get_result(auth.tenant_id, str(run_id))

    @app.post("/v1/runs/{run_id}/reviews/{review_id}/resolve")
    def resolve_review(
        run_id: UUID,
        review_id: UUID,
        body: dict,
        request: Request,
        auth: Annotated[AuthContext, Depends(current)],
    ) -> dict:
        from pydantic import ValidationError

        from proofops_api.routers.reviews import ReviewResolve

        try:
            validated = ReviewResolve.model_validate(body).model_dump(mode="json")
        except ValidationError:
            raise HostedError("VALIDATION_ERROR", 422) from None
        return store.resolve_review(
            auth,
            str(run_id),
            str(review_id),
            validated,
            request.headers.get("If-Match"),
            request.headers.get("Idempotency-Key", ""),
        )

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel(run_id: UUID, auth: Annotated[AuthContext, Depends(current)]) -> dict:
        return store.cancel(auth, str(run_id), now=time.time())

    @app.post("/v1/documents/{document_id}/deletion-requests", status_code=202)
    def deletion(
        document_id: UUID,
        body: DeletionReason,
        request: Request,
        auth: Annotated[AuthContext, Depends(current)],
    ) -> dict:
        return store.delete_document(
            auth, str(document_id), request.headers.get("Idempotency-Key", ""), now=time.time()
        )

    return app
