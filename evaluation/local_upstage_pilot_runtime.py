"""Pilot stage execution and authenticated loopback review serving."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from proofops.adapters.local.auth_store import InMemorySessionStore

if TYPE_CHECKING:
    from threading import Thread

    from proofops_api.composition import ApiComposition
    from proofops_worker.extract_runner import LocalExtractRunner
    from proofops_worker.local_runner import LocalParserRunner
    from proofops_worker.tag_runner import LocalTagRunner


def local_login_response(
    sessions: InMemorySessionStore,
    user: str,
    tenant: str,
    run_id: str,
    *,
    new_analysis: bool = False,
) -> RedirectResponse:
    """The secret loopback login link renews an expired demo session on each visit."""
    from fastapi.responses import RedirectResponse
    from proofops.adapters.local.auth_store import hash_token, new_session_id
    from proofops.application.authorization import SessionRecord
    from proofops_api.auth import SESSION_COOKIE_NAME

    session, csrf, now = new_session_id(), secrets.token_urlsafe(32), time.time()
    sessions.put_with_token(
        SessionRecord(session, user, tenant, hash_token(csrf), now + 3600, now + 3600, False), csrf
    )
    response = RedirectResponse(
        "/documents/new" if new_analysis else f"/runs/{run_id}/claims", status_code=303
    )
    response.set_cookie(
        SESSION_COOKIE_NAME, session, secure=True, httponly=True, samesite="strict", path="/"
    )
    return response


def _run_live_stages(args: argparse.Namespace, *, tenant_id: str, run_id: str) -> dict[str, Any]:
    """Drive paid stages, preserving a machine-readable stop before inspection."""
    from proofops_worker.composition import build_composition

    tenant = tenant_id
    result: dict[str, Any] = dict(stage=None, status="not_run", exit_code=0, stage_seconds={})
    for stage in ("parse", "extract", "tag"):
        stage_started = time.monotonic()
        worker = build_composition(
            stage=stage,
            verify_paragraphs=args.verify_paragraphs and stage == "parse",
            native_typography_tolerance=args.native_quote_typography and stage == "parse",
            raster_ocr=args.raster_ocr and stage == "parse",
        )
        try:
            outcome = worker.run_once(tenant_id=tenant, run_id=run_id)
            print(stage, outcome, flush=True)
            result.update(stage=stage, status=outcome)
            if (
                stage == "extract"
                and outcome in {"committed", "pending_downstream", "ignored", "idle"}
                and args.extraction_total_calls is not None
                and args.extraction_total_calls > args.max_calls
                and not (
                    getattr(args, "pipeline_profile", None)
                    in (
                        "unattended-v1",
                        "finals-unattended-v1",
                        "finals-unattended-v2",
                        "finals-unattended-j3-v1",
                        "finals-unattended-j7-v1",
                        "finals-unattended-j8-v1",
                    )
                    and "tag_job" in worker.store.jobs.get_run(tenant, run_id)
                )
            ):
                from proofops_worker.extract_batch import run_batches
                from proofops_worker.extract_runner import LocalExtractRunner

                batches = run_batches(
                    cast(LocalExtractRunner, worker), tenant_id=tenant, run_id=run_id, batches=100
                )
                print(
                    "extract_batches",
                    json.dumps(
                        [
                            {
                                k: len(v) if isinstance(v, list | dict) and k != "usage" else v
                                for k, v in batch.items()
                            }
                            for batch in batches
                        ]
                    ),
                    flush=True,
                )
                last = batches[-1] if batches else {"status": "no_revision"}
                if last["status"] != "complete" and not (
                    last["status"] == "committed"
                    and last.get("pending_after") == []
                    and not last.get("stop_code")
                ):
                    result.update(
                        status=last.get("stop_code")
                        or (
                            "extraction_pending"
                            if last["status"] == "committed"
                            else last["status"]
                        ),
                        exit_code=1,
                    )
                    break
            elif stage == "extract" and outcome in {"idle", "ignored"}:
                # A delivery result alone does not prove extraction was published.
                run = worker.store.jobs.get_run(tenant, run_id)
                if "extract_job" not in run:
                    result.update(status="no_revision", exit_code=1)
                    break
            if outcome in {"failed", "retry", "discarded", "cancelled", "deferred"}:
                result["exit_code"] = 1
                break
        finally:
            result["stage_seconds"][stage] = round(time.monotonic() - stage_started, 2)
            worker.uploads.close()
            worker.uploads.registry.close()
    return result


def _serve_pilot(
    pilot: ModuleType,
    args: argparse.Namespace,
    *,
    response: httpx.Response,
    app: FastAPI,
    c: ApiComposition,
    user: str,
    tenant: str,
    run_id: str,
    manifest: dict[str, Any],
    state: Path,
    origin: str,
) -> None:
    """Serve authenticated local review and clean up an explicitly enabled worker."""
    # A fresh worker session has no published claims yet. Serve its upload
    # entry without invoking the initial queued run or weakening read-only replays.
    fresh_worker = (
        args.serve_worker
        and response.status_code == 409
        and c.runs.store.jobs.get_run(tenant, run_id).get("status") == "queued"
    )
    if response.status_code != 200 and not fresh_worker:
        raise SystemExit(
            f"Cannot serve this run: claims HTTP {response.status_code}; "
            "inspect the saved inspection JSON"
        )
    import uvicorn
    from fastapi import HTTPException
    from fastapi.staticfiles import StaticFiles

    login_token = secrets.token_urlsafe(24)

    @app.get("/__local/" + login_token, include_in_schema=False)
    def login() -> RedirectResponse:
        return pilot.local_login_response(
            c.auth_store.sessions, user, tenant, run_id, new_analysis=fresh_worker
        )

    app.mount("/assets", StaticFiles(directory=pilot.ROOT / "apps/web/dist/assets"))

    # Authoritative candidate rule pack comes from the created run's frozen
    # META, never fabricated: the pilot registers only a draft pack, so this
    # id is a tagging-only reference the frontend labels as such. It is never
    # an approval and does not activate anything.
    run_meta = c.runs.store.jobs.get_run(tenant, run_id)
    candidate_rule_pack_id = run_meta.get("rule_pack_id")
    served_pages = list(manifest.get("selected_pages", []))

    @app.get("/local/submission", include_in_schema=False)
    def local_submission(request: Request) -> Response:
        from fastapi.responses import JSONResponse
        from proofops_api.auth import _authorize
        from starlette.responses import Response as _Response

        # Reuse the shared tenant authorization + HTTP error mapping.
        result = _authorize(request, c.auth_store, time.time(), "viewer")
        if isinstance(result, _Response):
            return result
        if result.tenant_id != tenant:
            return JSONResponse(
                {"error": {"code": "RESOURCE_NOT_FOUND", "message": "tenant not found"}},
                status_code=404,
            )
        return JSONResponse(
            dict(
                worker_enabled=bool(worker_thread and worker_thread.is_alive()),
                candidate_rule_pack_id=candidate_rule_pack_id,
                selected_pages=served_pages,
            ),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        if path.startswith(("v1/", "local/", "__local/")):
            raise HTTPException(404)
        return FileResponse(pilot.ROOT / "apps/web/dist/index.html")

    worker_thread = worker_stop = None
    if args.serve_worker:
        # Paid consent: reuse the same Upstage key + shared USD20 ledger the
        # one-shot --invoke path uses; the loop mints no new allowance.
        key_lines = args.key_file.read_text().splitlines()
        key_name = {
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "upstage": "UPSTAGE_API_KEY",
        }[args.llm_provider]
        os.environ[key_name] = next(
            line.split("=", 1)[1].strip().strip('"').strip("'")
            for line in key_lines
            if line.startswith(key_name + "=")
        )
        if args.parser in ("upstage", "mixed-v1") and key_name != "UPSTAGE_API_KEY":
            os.environ["UPSTAGE_API_KEY"] = next(
                line.split("=", 1)[1].strip().strip('"').strip("'")
                for line in (pilot.ROOT / ".env.upstage.local").read_text().splitlines()
                if line.startswith("UPSTAGE_API_KEY=")
            )
        if args.vision_parse != "off" and key_name != "OPENROUTER_API_KEY":
            os.environ["OPENROUTER_API_KEY"] = next(
                line.split("=", 1)[1].strip().strip('"').strip("'")
                for line in (pilot.ROOT / ".env.openrouter.local").read_text().splitlines()
                if line.startswith("OPENROUTER_API_KEY=")
            )
        from proofops_worker.composition import build_composition

        from evaluation.serve_worker import start_background

        def build_stage(*, stage: str) -> LocalParserRunner | LocalExtractRunner | LocalTagRunner:
            return build_composition(
                stage=stage,
                verify_paragraphs=args.verify_paragraphs and stage == "parse",
                native_typography_tolerance=args.native_quote_typography and stage == "parse",
                raster_ocr=args.raster_ocr and stage == "parse",
            )

        worker_thread, worker_stop = start_background(build_stage, c.runs, tenant)
        print("Local serve-worker enabled: driving new web-queued runs", flush=True)

    (state / "browser.json").write_text(
        json.dumps(dict(login_url=origin + "/__local/" + login_token, run_id=run_id))
    )
    (state / "browser.json").chmod(0o600)
    print("Open review: " + origin + "/__local/" + login_token, flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    finally:
        if worker_stop is not None:
            worker_stop.set()
            # start_background returns the thread and stop event together.
            cast("Thread", worker_thread).join(timeout=10)
            os.environ.pop(key_name, None)
