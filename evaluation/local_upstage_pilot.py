"""Authorized local PDF→real extraction→review pilot; no production or grading approval.

Use --invoke explicitly for model calls; reuse a state directory to view stored results.
All model calls share the pre-existing workspace USD 10 ledger. No automatic retries.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--pages", default="1")
    parser.add_argument("--report-year", type=int, required=True)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--model", choices=["solar-pro3", "solar-pro4"], default="solar-pro3")
    parser.add_argument("--invoke", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    pages = sorted(set(int(p) for p in args.pages.split(",")))
    if not 1 <= args.max_calls <= 20 or not pages or min(pages) < 1:
        parser.error("invalid declared pages/call limit")
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = state / "pilot.json"
    source = args.pdf.resolve().read_bytes()
    digest = sha256(source).hexdigest()
    origin = f"http://localhost:{args.port}"
    from proofops.application.ingest.graph_fusion import ParserProfile
    from proofops_agent.upstage_extraction import _profile

    if not manifest_path.exists():
        config = ParserProfile(
            str(uuid4()),
            java_executable="/opt/homebrew/opt/openjdk@21/bin/java",
            timeout_seconds=120,
        )
        (state / "parser.json").write_text(json.dumps(config.config_snapshot()))
        settings = dict(
            build_root=str(ROOT),
            extraction_profile=asdict(_profile(args.model)),
            extraction_limits=dict(max_calls=args.max_calls, max_output_tokens=1024),
            budget_limits=dict(
                input_tokens=100000,
                output_tokens=30000,
                max_attempts=1,
                roles=[
                    dict(
                        role="extractor",
                        max_calls=args.max_calls,
                        max_input_tokens=100000,
                        max_output_tokens=1024,
                        max_context_tokens=101024,
                    )
                ],
            ),
        )
        (state / "settings.json").write_text(json.dumps(settings))
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        APP_ORIGIN=origin,
        LOCAL_DATABASE_PATH=str(state / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="",
    )
    from fastapi.testclient import TestClient
    from proofops.adapters.local.auth_store import hash_token, new_session_id
    from proofops.application.authorization import MembershipRecord, SessionRecord
    from proofops.application.registry import artifact_sha256
    from proofops.application.rulepacks import RulePackRecord, compute_pack_sha256
    from proofops_api.auth import SESSION_COOKIE_NAME
    from proofops_api.main import app

    c = app.state.composition
    tenant = (
        json.loads(manifest_path.read_text())["tenant_id"]
        if manifest_path.exists()
        else str(uuid4())
    )
    user = "authorized-local-operator"
    csrf = secrets.token_urlsafe(32)
    session = new_session_id()
    now = time.time()
    c.auth_store.sessions.put_with_token(
        SessionRecord(session, user, tenant, hash_token(csrf), now + 3600, now + 3600, False), csrf
    )
    csrf = c.auth_store.sessions.csrf_token_for(session)
    c.auth_store.memberships.put(MembershipRecord(tenant, user, "admin", "active"))
    http = TestClient(app, base_url=f"https://localhost:{args.port}")
    http.cookies.set(SESSION_COOKIE_NAME, session)
    http.headers.update({"Origin": origin, "X-CSRF-Token": csrf})

    def post(url, body):
        response = http.post(
            url,
            json=body,
            headers={"Origin": origin, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
        )
        if response.status_code not in (200, 201, 202):
            raise ValueError(f"HTTP {response.status_code}: {response.text}")
        return response.json()

    if not manifest_path.exists():
        approved_at = datetime.now(UTC).isoformat()
        rights, runtime, consent, pack_id = (str(uuid4()) for _ in range(4))
        common = dict(
            tenant_id=tenant,
            status="approved",
            version="1",
            approved_by=user,
            approved_at=approved_at,
            purpose="local_test",
            provider="upstage",
            expires_at="2026-09-16T00:00:00Z",
        )
        profiles = [
            (
                "rights",
                rights,
                dict(
                    common,
                    rights_profile_id=rights,
                    source_sha256=digest,
                    approval_scope="user report local API test only; redistribution not approved",
                ),
            ),
            (
                "runtime",
                runtime,
                dict(
                    common,
                    runtime_binding_id=runtime,
                    role="extractor",
                    model_id=args.model,
                    endpoint="https://api.upstage.ai/v1/chat/completions",
                    budget_limit_usd="10.00",
                ),
            ),
            (
                "consent",
                consent,
                dict(
                    common,
                    consent_profile_id=consent,
                    allowed_source_sha256=[digest],
                    allowed_document_rights=[rights],
                    allow_cross_tenant_cache=False,
                    allow_agentcore_memory=False,
                ),
            ),
        ]
        for kind, identifier, artifact in profiles:
            c.registry.with_option(
                tenant,
                kind,
                identifier,
                "Local Upstage test authorization",
                status="approved",
                version="1",
                artifact=artifact,
                sha256=artifact_sha256(artifact),
                approved_by=user,
                approved_at=approved_at,
                local_synthetic=False,
            )
        c.registry.with_enabled_mode(tenant, "disclosure")
        data = yaml.safe_load((ROOT / "config/rule_pack_manifest.yaml").read_text())
        files = {p: yaml.safe_load((ROOT / "config" / p).read_text()) for p in data["files"]}
        data.update(rule_pack_id=pack_id, tenant_id=tenant, approved_by=None, approved_at=None)
        data["sha256"] = compute_pack_sha256(data, files)
        c.rulepack_store.add_pack(RulePackRecord.from_dict(data), files)
        company = post(
            "/v1/companies",
            dict(legal_name="실제 보고서 검토 시험", aliases=[], registration_identifier=None),
        )
        document = post(
            "/v1/documents",
            dict(
                company_id=company["company_id"],
                title=args.pdf.name,
                document_type="sustainability_report",
            ),
        )
        ticket = post(
            f"/v1/documents/{document['document_id']}/versions",
            dict(
                filename=args.pdf.name,
                size_bytes=len(source),
                sha256=digest,
                report_year=args.report_year,
                industry_system="unknown",
                period_start=args.period_start,
                period_end=args.period_end,
                rights_profile_id=rights,
            ),
        )
        uploaded = http.post(
            ticket["post_url"],
            data=ticket["post_fields"],
            files={"file": (args.pdf.name, source, "application/pdf")},
        )
        if uploaded.status_code != 204:
            raise ValueError(f"upload failed: {uploaded.status_code}")
        version = post(
            f"/v1/uploads/{ticket['upload_id']}/complete",
            dict(sha256=digest, size_bytes=len(source)),
        )
        run = post(
            "/v1/runs",
            dict(
                document_version_id=version["resource_id"],
                scope="declared_subset",
                selected_pages=pages,
                mode="disclosure",
                rule_pack_id=pack_id,
                runtime_binding_id=runtime,
                consent_profile_id=consent,
            ),
        )
        manifest = dict(
            tenant_id=tenant,
            run_id=run["run_id"],
            document_version_id=version["resource_id"],
            source_path=str(args.pdf.resolve()),
            source_sha256=digest,
            selected_pages=pages,
            rulepack_approval=None,
            authorization="user request 2026-09-12: actual model API integration",
            production_ready=False,
            model=args.model,
        )
        with manifest_path.open("x") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
    else:
        manifest = json.loads(manifest_path.read_text())
        if manifest["source_sha256"] != digest:
            raise ValueError("pilot source changed")
        if manifest.get("model", "solar-pro3") != args.model:
            raise ValueError("pilot model changed; create a new state directory")
    run_id = manifest["run_id"]
    if args.invoke:
        key_lines = (ROOT / ".env.upstage.local").read_text().splitlines()
        key = next(
            line.split("=", 1)[1].strip().strip('"').strip("'")
            for line in key_lines
            if line.startswith("UPSTAGE_API_KEY=")
        )
        os.environ["UPSTAGE_API_KEY"] = key
        from proofops_worker.composition import build_composition

        try:
            for stage in ("parse", "extract", "tag"):
                worker = build_composition(stage=stage)
                outcome = worker.run_once(tenant_id=tenant, run_id=run_id)
                print(stage, outcome, flush=True)
                if outcome in {"failed", "retry", "discarded"}:
                    break
        finally:
            os.environ.pop("UPSTAGE_API_KEY", None)
    response = http.get(f"/v1/runs/{run_id}/claims")
    result = dict(manifest, claims_http_status=response.status_code, claims=response.json())
    if response.status_code == 200 and response.json()["items"]:
        identifier = response.json()["items"][0]["claim_id"]
        detail = http.get(f"/v1/runs/{run_id}/claims/{identifier}")
        result.update(detail_http_status=detail.status_code, first_claim_detail=detail.json())
    cost = http.get(f"/v1/runs/{run_id}/cost")
    result.update(cost_http_status=cost.status_code, cost=cost.json())
    with (state / f"inspection-{time.time_ns()}.json").open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            dict(
                run_id=run_id,
                claims_http_status=response.status_code,
                claims=len(response.json().get("items", [])),
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.serve:
        import uvicorn
        from fastapi import HTTPException
        from fastapi.responses import FileResponse, RedirectResponse
        from fastapi.staticfiles import StaticFiles

        login_token = secrets.token_urlsafe(24)

        @app.get("/__local/" + login_token, include_in_schema=False)
        def login():
            response = RedirectResponse(f"/runs/{run_id}/claims", status_code=303)
            response.set_cookie(
                SESSION_COOKIE_NAME,
                session,
                secure=True,
                httponly=True,
                samesite="strict",
                path="/",
            )
            return response

        app.mount("/assets", StaticFiles(directory=ROOT / "apps/web/dist/assets"))

        @app.get("/{path:path}", include_in_schema=False)
        def web(path: str):
            if path.startswith(("v1/", "local/", "__local/")):
                raise HTTPException(404)
            return FileResponse(ROOT / "apps/web/dist/index.html")

        (state / "browser.json").write_text(
            json.dumps(dict(login_url=origin + "/__local/" + login_token, run_id=run_id))
        )
        (state / "browser.json").chmod(0o600)
        print("Local review server ready", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
