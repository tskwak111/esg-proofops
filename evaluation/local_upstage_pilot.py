"""Authorized local PDF→real extraction→review pilot; no production or grading approval.

Use --invoke explicitly for model calls; reuse a state directory to view stored results.
All model calls share the existing ledger, extended explicitly to USD20 on 2026-09-18.
No automatic retries.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket as socket
import sys
import time
from dataclasses import asdict as asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any
from typing import cast as cast
from uuid import UUID as UUID
from uuid import uuid4

# Direct file execution starts with evaluation/ on sys.path instead of its parent.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
from fastapi import Request as Request
from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES as PAGE_OCR_PROFILES

from evaluation import local_upstage_pilot_cli as _cli
from evaluation import local_upstage_pilot_profiles as _profiles
from evaluation import local_upstage_pilot_resume as _resume
from evaluation import local_upstage_pilot_runtime as _runtime
from evaluation import local_upstage_pilot_settings as _settings
from evaluation.local_upstage_pilot_profiles import FINALS_CANDIDATE as FINALS_CANDIDATE
from evaluation.local_upstage_pilot_profiles import FINALS_CANDIDATE_FLAGS as FINALS_CANDIDATE_FLAGS
from evaluation.local_upstage_pilot_profiles import (
    FINALS_CANDIDATE_FORBIDDEN as FINALS_CANDIDATE_FORBIDDEN,
)
from evaluation.local_upstage_pilot_profiles import FINALS_CANDIDATE_V2 as FINALS_CANDIDATE_V2
from evaluation.local_upstage_pilot_profiles import (
    FINALS_CANDIDATE_V2_FLAGS as FINALS_CANDIDATE_V2_FLAGS,
)
from evaluation.local_upstage_pilot_profiles import (
    FINALS_CANDIDATE_V2_FORBIDDEN as FINALS_CANDIDATE_V2_FORBIDDEN,
)
from evaluation.local_upstage_pilot_profiles import (
    FINALS_CANDIDATE_VALUES as FINALS_CANDIDATE_VALUES,
)
from evaluation.local_upstage_pilot_profiles import (
    claim_source_policy_for as claim_source_policy_for,
)
from evaluation.local_upstage_pilot_profiles import (
    extraction_budget_settings as extraction_budget_settings,
)
from evaluation.local_upstage_pilot_profiles import parser_java_executable as parser_java_executable
from evaluation.local_upstage_pilot_profiles import parser_memory_limit as parser_memory_limit
from evaluation.local_upstage_pilot_profiles import parser_output_limit as parser_output_limit
from evaluation.local_upstage_pilot_profiles import pilot_company_body as pilot_company_body
from evaluation.local_upstage_pilot_resume import (
    _validate_existing_pilot as _validate_existing_pilot,
)
from evaluation.local_upstage_pilot_runtime import _run_live_stages as _run_live_stages
from evaluation.local_upstage_pilot_runtime import local_login_response as local_login_response

if TYPE_CHECKING:
    import httpx
    from fastapi import FastAPI
    from proofops_api.composition import ApiComposition

ROOT = Path(__file__).resolve().parents[1]


# Helpers receive this module for dynamic hooks: keep caller monkeypatches and
# the file/-m __main__ entry point on the same original attribute lookup path.
def finals_candidate_profile(args: argparse.Namespace) -> str | None:
    return _profiles.finals_candidate_profile(sys.modules[__name__], args)


def apply_finals_candidate(args: argparse.Namespace, *, restoring: bool = False) -> None:
    "Expand the opt-in bundle, or verify its frozen flags during read-only resume."
    return _profiles.apply_finals_candidate(sys.modules[__name__], args, restoring=restoring)


def live_tagging_settings(
    max_calls: int,
    *,
    model_id: str = "solar-pro4",
    relations: bool = False,
    relation_profile: str = "source-quotes-v1",
    preliminary_context: bool = False,
    preliminary_table_context: bool = False,
    preliminary_table_role: bool = False,
    preliminary_goal_role: bool = False,
    preliminary_actor_role: bool = False,
    preliminary_pb1: bool = False,
    preliminary_sentence_context: bool = False,
    preliminary_sentence_fallback: bool = False,
    preliminary_p2: bool = False,
    preliminary_profile: str | None = None,
    compact_element_wire: bool = False,
    element_consistency: bool = False,
    position_context_order: bool = False,
    capacity_refresh: bool = False,
    prompt_profile: str | None = None,
    element_definition_profile: str | None = None,
) -> dict[str, Any]:
    "Explicit bounded pilot config; grants are registered separately by main."
    return _profiles.live_tagging_settings(
        sys.modules[__name__],
        max_calls,
        model_id=model_id,
        relations=relations,
        relation_profile=relation_profile,
        preliminary_context=preliminary_context,
        preliminary_table_context=preliminary_table_context,
        preliminary_table_role=preliminary_table_role,
        preliminary_goal_role=preliminary_goal_role,
        preliminary_actor_role=preliminary_actor_role,
        preliminary_pb1=preliminary_pb1,
        preliminary_sentence_context=preliminary_sentence_context,
        preliminary_sentence_fallback=preliminary_sentence_fallback,
        preliminary_p2=preliminary_p2,
        preliminary_profile=preliminary_profile,
        compact_element_wire=compact_element_wire,
        element_consistency=element_consistency,
        position_context_order=position_context_order,
        capacity_refresh=capacity_refresh,
        prompt_profile=prompt_profile,
        element_definition_profile=element_definition_profile,
    )


def raster_settings(*, max_pages: int, max_calls: int) -> dict[str, Any]:
    "Pin an explicit raster policy; registration and per-call consent remain separate."
    return _profiles.raster_settings(
        sys.modules[__name__], max_pages=max_pages, max_calls=max_calls
    )


def apply_resume_metadata(args: argparse.Namespace, saved: dict[str, Any]) -> None:
    """Restore saved create-time metadata without side effects; reject explicit conflicts."""
    return _resume.apply_resume_metadata(sys.modules[__name__], args, saved)


def _restore_resume_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    resume_state: Path,
    resume_manifest: Path,
) -> None:
    "Restore saved inputs and reject new capabilities on a read-only resume."
    return _resume._restore_resume_args(
        sys.modules[__name__], args, parser, resume_state, resume_manifest
    )


def _build_parser() -> argparse.ArgumentParser:
    "Construct the existing CLI without parsing or applying profiles."
    return _cli._build_parser(__doc__)


def _prepare_run_settings(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    state: Path,
    manifest_path: Path,
    pages: list[int],
    claim_pages: list[int] | None,
    extraction_budget: dict[str, Any],
    raster: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    "Write new-run settings; preserve existing parser and settings files on resume."
    return _settings._prepare_run_settings(
        sys.modules[__name__],
        args,
        parser,
        state=state,
        manifest_path=manifest_path,
        pages=pages,
        claim_pages=claim_pages,
        extraction_budget=extraction_budget,
        raster=raster,
    )


def _serve_pilot(
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
    "Serve authenticated local review and clean up an explicitly enabled worker."
    return _runtime._serve_pilot(
        sys.modules[__name__],
        args,
        response=response,
        app=app,
        c=c,
        user=user,
        tenant=tenant,
        run_id=run_id,
        manifest=manifest,
        state=state,
        origin=origin,
    )


def run_live_stages(args: argparse.Namespace, *, tenant_id: str, run_id: str) -> dict[str, Any]:
    if getattr(args, "pipeline_profile", None) in (
        "finals-unattended-v1",
        "finals-unattended-v2",
        "finals-unattended-j3-v1",
        "finals-unattended-j7-v1",
        "finals-unattended-j8-v1",
    ):
        from proofops.adapters.local.profile_runtime import spend_session

        with spend_session(run_id):
            return _run_live_stages(args, tenant_id=tenant_id, run_id=run_id)
    return _run_live_stages(args, tenant_id=tenant_id, run_id=run_id)


def main():
    # Use the installed CLI toolchain without changing the system Xcode selection.
    cli_tools = Path("/Library/Developer/CommandLineTools")
    if sys.platform == "darwin" and (cli_tools / "usr/bin/swift").is_file():
        os.environ.setdefault("DEVELOPER_DIR", str(cli_tools))
    parser = _build_parser()
    args = parser.parse_args()
    company_body = _cli.validate_arguments(sys.modules[__name__], args, parser)
    raster = (
        raster_settings(max_pages=args.raster_max_pages, max_calls=args.raster_max_calls)
        if args.raster_ocr
        else {}
    )
    if not 0 <= args.mixed_ocr_max_pages <= 30 or (
        args.mixed_ocr_max_pages and args.parser != "mixed-v1"
    ):
        parser.error("mixed OCR allowance requires mixed-v1 and 0..30 pages")
    if args.parser == "mixed-v1" and not args.claim_pages:
        parser.error("mixed-v1 requires explicit --claim-pages")
    pages = sorted(set(int(p) for p in args.pages.split(",")))
    from proofops.application.claim_scope import MAX_EXTRACTION_BATCH_CALLS

    if not 1 <= args.max_calls <= MAX_EXTRACTION_BATCH_CALLS or not pages or min(pages) < 1:
        parser.error("invalid declared pages/call limit")
    try:
        extraction_budget = extraction_budget_settings(args.max_calls, args.extraction_total_calls)
    except ValueError as exc:
        parser.error(str(exc))
    claim_pages: list[int] | None = None
    if args.claim_pages is not None:
        claim_pages = sorted(set(int(p) for p in args.claim_pages.split(",")))
        if not claim_pages or not set(claim_pages) <= set(pages):
            parser.error("--claim-pages must be a non-empty subset of --pages")
    from evaluation.scope_input import MAX_UPLOAD_BYTES

    limit = MAX_UPLOAD_BYTES
    try:
        source_size = args.pdf.stat().st_size
    except OSError as exc:
        parser.error(f"Cannot read --pdf: {exc}")
    if source_size > limit:
        parser.error(f"--pdf exceeds the supported upload limit of {limit} bytes (150 MiB)")
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = state / "pilot.json"
    source = args.pdf.resolve().read_bytes()
    digest = sha256(source).hexdigest()
    origin = f"http://localhost:{args.port}"
    settings, extraction_profile = _prepare_run_settings(
        args,
        parser,
        state=state,
        manifest_path=manifest_path,
        pages=pages,
        claim_pages=claim_pages,
        extraction_budget=extraction_budget,
        raster=raster,
    )
    os.environ.update(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        APP_ORIGIN=origin,
        LOCAL_DATABASE_PATH=str(state / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local" if args.live_tagging else "",
        LOCAL_LLM_PROVIDER=args.llm_provider,
    )
    from fastapi.testclient import TestClient
    from proofops.adapters.local.auth_store import hash_token, new_session_id
    from proofops.application.authorization import MembershipRecord, SessionRecord
    from proofops.application.registry import artifact_sha256
    from proofops.application.rulepacks import RulePackRecord, compute_pack_sha256
    from proofops_api.auth import SESSION_COOKIE_NAME
    from proofops_api.main import create_app

    # Bind this invocation to its own state and origin, even after prior API imports.
    app = create_app()
    c = app.state.composition
    tenant = (
        json.loads(manifest_path.read_text())["tenant_id"]
        if manifest_path.exists()
        else str(args.tenant_id or uuid4())
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
        now_dt = datetime.now(UTC)
        approved_at = now_dt.isoformat()
        expires_at = (now_dt + timedelta(hours=24)).isoformat()
        rights, runtime, consent, pack_id = (str(uuid4()) for _ in range(4))
        common = dict(
            tenant_id=tenant,
            status="approved",
            version="1",
            approved_by=user,
            approved_at=approved_at,
            purpose="local_test",
            provider=args.llm_provider,
            expires_at=expires_at,
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
                    model_sha256=settings["extraction_profile"]["model_sha256"],
                    endpoint=(
                        "https://api.openai.com/v1/chat/completions"
                        if args.llm_provider == "openai"
                        else "https://openrouter.ai/api/v1/chat/completions"
                    )
                    if args.llm_provider in ("openrouter", "openai")
                    else "https://api.upstage.ai/v1/chat/completions",
                    budget_limit_usd={"openai": "3.00", "openrouter": "5.00", "upstage": "20.00"}[
                        args.llm_provider
                    ],
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
        if args.vision_parse != "off" or args.parser in ("upstage", "mixed-v1"):
            profiles[-1][2]["allow_raster_upload"] = True
        if args.raster_ocr:
            from proofops.domain.provenance import canonical_hash

            profiles[-1][2]["allow_raster_upload"] = True
            profiles.append(
                (
                    "runtime",
                    raster["raster_runtime_binding_id"],
                    dict(
                        common,
                        provider="upstage",
                        runtime_binding_id=raster["raster_runtime_binding_id"],
                        schema="local_upstage_raster_binding_v1",
                        role="vision",
                        model_id="document-parse-260128",
                        endpoint="https://api.upstage.ai/v1/document-digitization",
                        budget_limit_usd="20.00",
                        mode="standard",
                        max_pages=args.raster_max_pages,
                        max_calls=args.raster_max_calls,
                        accepts_images=True,
                        image_input_verified=True,
                        raster_policy_sha256=canonical_hash(raster["raster_policy"]),
                    ),
                )
            )
        if args.live_tagging:
            from proofops.domain.provenance import canonical_hash

            settings = json.loads((state / "settings.json").read_text())
            for prefix in ("preliminary", "tagging") + (
                ("relation",) if args.live_relations else ()
            ):
                pinned = settings[prefix + "_settings"]
                identifier = pinned["binding"]["binding_id"]
                profiles.append(
                    (
                        "runtime",
                        identifier,
                        dict(
                            common,
                            runtime_binding_id=identifier,
                            role="tagger",
                            model_id=(
                                "gpt-6-luna"
                                if args.llm_provider == "openai"
                                else "openai/gpt-6-luna"
                            )
                            if args.llm_provider in ("openrouter", "openai")
                            else "solar-pro4",
                            endpoint=(
                                "https://api.openai.com/v1/chat/completions"
                                if args.llm_provider == "openai"
                                else "https://openrouter.ai/api/v1/chat/completions"
                            )
                            if args.llm_provider in ("openrouter", "openai")
                            else "https://api.upstage.ai/v1/chat/completions",
                            budget_limit_usd={
                                "openai": "3.00",
                                "openrouter": "5.00",
                                "upstage": "20.00",
                            }[args.llm_provider],
                            schema="local_upstage_tagger_binding_v1",
                            tagging_settings_sha256=canonical_hash(pinned),
                            input_reservation_policy_sha256=canonical_hash(
                                settings["input_reservation_policy"]
                            ),
                        ),
                    )
                )
        if "decision_settings" in settings:
            from proofops.application.tagging.decisions import MODELS, POLICY

            profiles[2][2]["allowed_decision_models"] = {p: c["model"] for p, c in MODELS.items()}
            for provider, identifier in settings["decision_settings"]["binding_ids"].items():
                profiles.append(
                    (
                        "runtime",
                        identifier,
                        dict(
                            common,
                            provider=provider,
                            runtime_binding_id=identifier,
                            schema="local_decision_binding_v1",
                            role="decision",
                            model_id=MODELS[provider]["model"],
                            endpoint=MODELS[provider]["endpoint"],
                            decision_policy_sha256=canonical_hash(POLICY),
                            budget_limit_usd="3.00" if provider == "openai" else "5.00",
                        ),
                    )
                )
        for kind, identifier, artifact in profiles:
            c.registry.with_option(
                tenant,
                kind,
                identifier,
                (
                    f"Upstage {artifact['role']} · {artifact['model_id']}"
                    if kind == "runtime"
                    else f"Local Upstage {kind} authorization"
                ),
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
        draft_pack = RulePackRecord.from_dict(data)
        if args.ai_project_review:
            from scripts.review_rulepack import promote_and_review_pack

            run_rule_pack_id = promote_and_review_pack(
                c.rulepack_store,
                tenant_id=tenant,
                draft_pack=draft_pack,
                files=files,
                reviewer="codex-coordinator",
                reviewed_at=datetime.now(UTC).isoformat(),
                source_authority="user delegation 2026-09-20",
                note="project explicit rubric only; preserves GAPs, not legal approval",
                now=time.time(),
            )
        else:
            c.rulepack_store.add_pack(draft_pack, files)
            run_rule_pack_id = pack_id
        company = post("/v1/companies", company_body)
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
                rule_pack_id=run_rule_pack_id,
                runtime_binding_id=runtime,
                consent_profile_id=consent,
            ),
        )
        manifest = dict(
            tenant_id=tenant,
            company_id=company["company_id"],
            company_legal_name=company_body["legal_name"],
            company_registration_identifier=company_body["registration_identifier"],
            run_id=run["run_id"],
            document_version_id=version["resource_id"],
            source_path=str(args.pdf.resolve()),
            source_sha256=digest,
            report_year=args.report_year,
            period_start=args.period_start,
            period_end=args.period_end,
            selected_pages=pages,
            claim_pages=claim_pages,
            parser_max_output_bytes=parser_output_limit(args.parser_max_output_bytes),
            parser_memory_bytes=parser_memory_limit(args.parser_memory_bytes),
            vision_parse=args.vision_parse,
            parser_mode=args.parser,
            extraction_batch_calls=args.max_calls,
            extraction_total_calls=args.extraction_total_calls,
            rulepack_approval="ai_delegated_review" if args.ai_project_review else None,
            authorization="user request 2026-09-18: actual model integration; cumulative USD20",
            production_ready=False,
            verify_paragraphs=args.verify_paragraphs,
            verify_tables=args.verify_tables,
            verify_merged_tables=args.verify_merged_tables,
            repair_table_headers=args.repair_table_headers,
            verify_claim_spans=args.verify_claim_spans,
            model=args.model,
            pipeline_profile=args.pipeline_profile,
            analysis_policy_sha256=args.analysis_policy_sha256,
            live_tagging=args.live_tagging,
            tagging_max_calls=args.tagging_max_calls if args.live_tagging else None,
        )
        if args.raster_ocr:
            manifest.update(raster_ocr=True, raster_policy=raster["raster_policy"])
        if args.preliminary_profile is not None:
            manifest["preliminary_profile"] = args.preliminary_profile
        if args.parser_source_recovery is not None:
            manifest["parser_source_recovery"] = args.parser_source_recovery
        if args.relation_profile != "source-quotes-v1":
            manifest["relation_profile"] = args.relation_profile
        if args.parser == "mixed-v1":
            manifest["mixed_ocr_max_pages"] = args.mixed_ocr_max_pages
        if args.claim_source_profile is not None:
            manifest["claim_source_profile"] = args.claim_source_profile
        if args.display_text_profile is not None:
            manifest["display_text_profile"] = args.display_text_profile
        if args.live_relations:
            manifest["live_relations"] = True
        if args.preliminary_context:
            manifest["preliminary_context"] = True
        if args.preliminary_table_context:
            manifest["preliminary_table_context"] = True
        if args.preliminary_table_role:
            manifest["preliminary_table_role"] = True
        if args.preliminary_goal_role:
            manifest["preliminary_goal_role"] = True
        if args.preliminary_sentence_fallback:
            manifest["preliminary_sentence_fallback"] = True
        if args.preliminary_sentence_context:
            manifest["preliminary_sentence_context"] = True
        if args.preliminary_actor_role:
            manifest["preliminary_actor_role"] = True
        if args.preliminary_p2:
            manifest["preliminary_p2"] = True
        if args.element_consistency:
            manifest["element_consistency"] = True
        if args.compact_element_wire:
            manifest["compact_element_wire"] = True
        if args.position_context_order:
            from proofops.application.tagging.preliminary import CONTEXT_POSITION_ORDER

            manifest["position_context_order"] = CONTEXT_POSITION_ORDER
        if args.verify_selected_cells:
            manifest["verify_selected_cells"] = True
        if args.claim_span_render_resolution:
            manifest["claim_span_render_resolution"] = True
        if args.claim_span_bullet_spacing:
            manifest["claim_span_bullet_spacing"] = True
        if args.claim_span_typography:
            manifest["claim_span_typography"] = True
        if args.native_quote_typography:
            manifest["native_quote_typography"] = True
        if args.extraction_year_notation:
            manifest["extraction_year_notation"] = True
        if args.extraction_context:
            manifest["extraction_context"] = True
        if args.extraction_table_context:
            manifest["extraction_table_context"] = True
        if args.extraction_table_rows:
            from proofops.application.ingest.table_row_candidates import POLICY as ROW_POLICY
            from proofops.domain.provenance import canonical_hash

            manifest["extraction_table_rows"] = True
            manifest["table_row_policy_sha256"] = canonical_hash(ROW_POLICY)
        if args.extraction_recall_prompt:
            manifest["extraction_recall_prompt"] = True
        if args.extraction_atomic:
            from proofops.application.ingest.atomic_candidates import POLICY, PROFILE
            from proofops.domain.provenance import canonical_hash

            manifest.update(
                extraction_atomic=True,
                extraction_profile_name=PROFILE,
                extraction_profile=extraction_profile,
                atomic_policy_sha256=canonical_hash(POLICY),
            )
        if args.extraction_atomic_v3:
            from proofops.application.ingest.atomic_candidates import POLICY_V3, PROFILE_V3
            from proofops.domain.provenance import canonical_hash

            manifest.update(
                extraction_atomic_v3=True,
                extraction_profile_name=PROFILE_V3,
                extraction_profile=extraction_profile,
                atomic_policy_sha256=canonical_hash(POLICY_V3),
            )
        if args.extraction_failure_diagnostics:
            manifest["extraction_failure_diagnostics"] = True
        if args.extraction_source_ids:
            manifest["extraction_source_ids"] = True
        if args.extraction_assertion_prompt:
            manifest["extraction_assertion_prompt"] = True
        if args.extraction_complete_selection:
            manifest["extraction_complete_selection"] = True
        if args.extraction_content_bounds:
            manifest["extraction_content_bounds"] = True
        if args.extraction_linewrap_join:
            manifest["extraction_linewrap_join"] = True
        if args.extraction_sentence_prefix:
            manifest["extraction_sentence_prefix"] = True
        if args.extraction_k1:
            manifest["extraction_k1"] = True
        if args.extraction_pb1_context_guard:
            manifest["extraction_pb1_context_guard"] = True
        if args.extraction_w9:
            manifest["extraction_w9"] = True
        if args.extraction_k3:
            manifest["extraction_k3"] = True
        if args.extraction_table_footnotes:
            manifest["extraction_table_footnotes"] = True
        if getattr(args, "extraction_located_table_context", False):
            manifest["extraction_located_table_context"] = True
        if args.extraction_j8:
            manifest["extraction_j8"] = True
        if args.extraction_k6:
            manifest["extraction_k6"] = True
        if args.extraction_q1:
            manifest["extraction_q1"] = True
        if args.extraction_qt1:
            manifest["extraction_qt1"] = True
        if args.extraction_i4_identity:
            manifest["extraction_i4_identity"] = True
        if getattr(args, "extraction_fxg_split", False):
            manifest["extraction_fxg_split"] = True
        if getattr(args, "extraction_qt1_goal_split", False):
            manifest["extraction_qt1_goal_split"] = True
        if args.extraction_qc_native_figures:
            manifest["extraction_qc_native_figures"] = True
        if args.extraction_i3_wire:
            manifest["extraction_i3_wire"] = True
        if getattr(args, "extraction_h1", False):
            manifest["extraction_h1"] = True
        if getattr(args, "extraction_i5_tables", False):
            manifest["extraction_i5_tables"] = True
        if args.extraction_j3:
            manifest["extraction_j3"] = True
        if args.extraction_j7:
            manifest["extraction_j7"] = True
        if args.extraction_pb1:
            manifest["extraction_pb1"] = True
        if args.extraction_fragment_guard:
            manifest["extraction_fragment_guard"] = True
        if args.capacity_refresh:
            manifest["capacity_refresh"] = True
        if finals_candidate_profile(args):
            manifest["r108_profile"] = finals_candidate_profile(args)
        with manifest_path.open("x") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
    else:
        manifest = json.loads(manifest_path.read_text())
        _validate_existing_pilot(
            args, parser, manifest, raster=raster, digest=digest, claim_pages=claim_pages
        )
    run_id = manifest["run_id"]
    pipeline_outcome = dict(stage=None, status="not_run", exit_code=0)
    if args.invoke:
        key_lines = args.key_file.read_text().splitlines()
        key_name = {
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "upstage": "UPSTAGE_API_KEY",
        }[args.llm_provider]
        key = next(
            line.split("=", 1)[1].strip().strip('"').strip("'")
            for line in key_lines
            if line.startswith(key_name + "=")
        )
        os.environ[key_name] = key
        if args.parser in ("upstage", "mixed-v1") and key_name != "UPSTAGE_API_KEY":
            os.environ["UPSTAGE_API_KEY"] = next(
                line.split("=", 1)[1].strip().strip('"').strip("'")
                for line in (ROOT / ".env.upstage.local").read_text().splitlines()
                if line.startswith("UPSTAGE_API_KEY=")
            )
        if args.vision_parse != "off" and key_name != "OPENROUTER_API_KEY":
            os.environ["OPENROUTER_API_KEY"] = next(
                line.split("=", 1)[1].strip().strip('"').strip("'")
                for line in (ROOT / ".env.openrouter.local").read_text().splitlines()
                if line.startswith("OPENROUTER_API_KEY=")
            )
        try:
            pipeline_outcome = run_live_stages(args, tenant_id=tenant, run_id=run_id)
        finally:
            os.environ.pop(key_name, None)
            if key_name != "OPENROUTER_API_KEY":
                os.environ.pop("OPENROUTER_API_KEY", None)
            if key_name != "UPSTAGE_API_KEY":
                os.environ.pop("UPSTAGE_API_KEY", None)
    # run_live_stages can run for hours (many extraction/tagging batches); the
    # fixture session minted at process start has a fixed absolute+idle TTL
    # (see SessionRecord above) and can expire well before inspection. Re-mint
    # a fresh local session/CSRF pair for the same tenant/user right before
    # reading results, so a slow pipeline never turns a real 200 into a
    # SESSION_EXPIRED 401 on the inspection calls below. This only replaces
    # this fixture's own session record; it does not change session TTL
    # policy, auth store behavior, or any production authorization path.
    csrf = secrets.token_urlsafe(32)
    session = new_session_id()
    now = time.time()
    c.auth_store.sessions.put_with_token(
        SessionRecord(session, user, tenant, hash_token(csrf), now + 3600, now + 3600, False), csrf
    )
    csrf = c.auth_store.sessions.csrf_token_for(session)
    http.cookies.set(SESSION_COOKIE_NAME, session)
    http.headers.update({"X-CSRF-Token": csrf})
    response = http.get(f"/v1/runs/{run_id}/claims")
    result = dict(
        manifest,
        claims_http_status=response.status_code,
        claims=response.json(),
        pipeline_outcome=pipeline_outcome,
    )
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
                selected_pages=manifest.get("selected_pages"),
                claim_pages=manifest.get("claim_pages"),
                claims_http_status=response.status_code,
                claims=len(response.json().get("items", [])),
                pipeline_outcome=pipeline_outcome,
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.serve:
        _serve_pilot(
            args,
            response=response,
            app=app,
            c=c,
            user=user,
            tenant=tenant,
            run_id=run_id,
            manifest=manifest,
            state=state,
            origin=origin,
        )

    return pipeline_outcome["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
