"""Explicit local parser composition; no runtime discovery or synthetic model result."""

from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import asdict
from pathlib import Path

from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.claims import ClaimExtractorPort
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops.application.registry import Registry
from proofops.application.telemetry import Telemetry
from proofops.application.uploads import UploadService
from proofops.composition import build_composition as build_proofops_composition

from proofops_worker.extract_runner import LocalExtractRunner
from proofops_worker.local_runner import LocalParserRunner
from proofops_worker.tag_runner import LocalTagRunner


def build_composition(
    *,
    stage: str = "parse",
    review_table_notes: bool = False,
    verify_paragraphs: bool = False,
    native_typography_tolerance: bool = False,
    raster_ocr: bool = False,
    provider_factories=None,
    provider_ledgers=None,
    claim_progress=None,
) -> LocalParserRunner | LocalExtractRunner | LocalTagRunner:
    if type(native_typography_tolerance) is not bool or (
        native_typography_tolerance and (not verify_paragraphs or stage != "parse" or raster_ocr)
    ):
        raise ValueError("NATIVE_TYPOGRAPHY_REQUIRE_NATIVE_PARSE_WITHOUT_RASTER")
    if type(raster_ocr) is not bool or (
        raster_ocr
        and (type(verify_paragraphs) is not bool or not verify_paragraphs or stage != "parse")
    ):
        raise ValueError("RASTER_OCR_REQUIRE_NATIVE_PARSE_STAGE")
    if type(verify_paragraphs) is not bool or (verify_paragraphs and stage != "parse"):
        raise ValueError("NATIVE_PARAGRAPHS_REQUIRE_PARSE_STAGE")
    if type(review_table_notes) is not bool or (review_table_notes and stage != "parse"):
        raise ValueError("NOTE_REVIEWS_REQUIRE_PARSE_STAGE")
    if stage not in {"parse", "extract", "tag"}:
        raise ValueError("STAGE_INVALID")
    try:
        max_workers = int(os.environ.get("LOCAL_LLM_MAX_WORKERS", "8"))
    except ValueError:
        raise ValueError("LOCAL_LLM_CONFIGURATION_INVALID") from None
    if not 1 <= max_workers <= 24:
        raise ValueError("LOCAL_LLM_CONFIGURATION_INVALID")
    if stage == "tag" and os.environ.get("LOCAL_TAGGING_MODE") not in {
        None,
        "",
        "local_synthetic",
        "upstage_local",
    }:
        raise ValueError("LOCAL_TAGGING_MODE_UNSUPPORTED")
    if stage == "extract" and os.environ.get("LOCAL_EXTRACTION_MODE") not in {
        "local_synthetic",
        "upstage_probe",
    }:
        raise ValueError("EXPLICIT_LOCAL_SYNTHETIC_EXTRACTION_REQUIRED")
    note_ledger = Path(__file__).resolve().parents[4] / ".local/upstage/budget.sqlite3"
    openai_ledger = Path(__file__).resolve().parents[4] / ".local/openai/budget.sqlite3"
    luna_ledger = Path(__file__).resolve().parents[4] / ".local/openrouter/budget.sqlite3"
    if provider_ledgers is not None:
        note_ledger, luna_ledger = provider_ledgers
    if raster_ocr and not note_ledger.is_file():
        raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
    build_proofops_composition(
        app_env=os.environ.get("APP_ENV", "local"),
        model_adapter=os.environ.get("MODEL_ADAPTER", "synthetic"),
    )
    config_path = os.environ.get("LOCAL_PARSER_PROFILE_PATH")
    if not config_path:
        raise ValueError("PARSER_CONFIG_REQUIRED")
    config = json.loads(Path(config_path).read_text())
    profile = ParserProfile(parse_manifest_id="00000000-0000-4000-8000-000000000000", **config)
    if profile.config_snapshot() != config:
        raise ValueError("PARSER_CONFIG_INVALID")
    database = Path(os.environ.get("LOCAL_DATABASE_PATH", ".local/state.sqlite3"))
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    registry = Registry.sqlite(database)
    uploads = UploadService(database, database.parent / "objects", registry)
    note_client = None
    if review_table_notes:
        from proofops.adapters.local.upstage import UpstageProbe

        if not note_ledger.is_file():
            raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
        note_client = UpstageProbe(os.environ.get("UPSTAGE_API_KEY", ""), note_ledger)
    raster_probe = None
    if raster_ocr:
        from proofops.adapters.local.upstage_parse import UpstageParseProbe

        raster_probe = UpstageParseProbe(os.environ.get("UPSTAGE_API_KEY", ""), note_ledger)
    upstage_probe = None
    if profile.parser_mode in ("upstage", "mixed-v1"):
        from proofops.adapters.local.upstage_parse import UpstageParseProbe

        if not note_ledger.is_file():
            raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
        upstage_probe = (
            provider_factories["parse"](note_ledger)
            if provider_factories
            else UpstageParseProbe(os.environ.get("UPSTAGE_API_KEY", ""), note_ledger)
        )
    runner = LocalParserRunner(
        LocalSQLiteRunStore(database),
        uploads,
        OpenDataLoaderParser(database.parent / "parser-prepared", upstage_probe=upstage_probe),
        profile=profile,
        verify_paragraphs=verify_paragraphs,
        native_typography_tolerance=native_typography_tolerance,
        note_client=note_client,
        note_ledger=note_ledger,
        raster_probe=raster_probe,
        raster_ledger=note_ledger if raster_ocr else None,
        telemetry=Telemetry(
            service="worker", env="local", stream=sys.stdout, hash_key=secrets.token_bytes(32)
        ),
    )

    if stage == "tag":
        from proofops_agent.synthetic_tagging import SyntheticTaggingTransport

        live_factory = None
        if os.environ.get("LOCAL_TAGGING_MODE") == "upstage_local":
            from proofops.adapters.local.openai import OpenAIProbe
            from proofops.adapters.local.openrouter import MODEL as LUNA_MODEL
            from proofops.adapters.local.openrouter import OpenRouterProbe
            from proofops.adapters.local.upstage import MODEL_PRO4, UpstageProbe

            from proofops_worker.live_tagging import LiveTaggingRuntime

            def live_factory(owner, snapshot, graph, lease, usage):
                if provider_factories and "decision_settings" in snapshot:
                    # Hosted profiles do not authorize Decisions transports. Never
                    # silently compose research ledgers/keys from a hosted worker.
                    raise ValueError("HOSTED_DECISION_BINDING_UNAVAILABLE")
                model = snapshot["tagging_settings"]["model_id"]
                if model == LUNA_MODEL:
                    ledger = luna_ledger
                    probe = (provider_factories["llm"] if provider_factories else OpenRouterProbe)(
                        os.environ.get("OPENROUTER_API_KEY", ""),
                        ledger,
                        wire_policy_version=snapshot["tagging_settings"].get(
                            "wire_policy_version", 1
                        ),
                    )
                elif model == "gpt-6-luna":
                    if provider_factories:
                        ledger = luna_ledger
                        probe = provider_factories["llm"](
                            os.environ.get("OPENAI_API_KEY", ""),
                            ledger,
                            wire_policy_version=2,
                        )
                    else:
                        if not openai_ledger.is_file():
                            raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
                        ledger = openai_ledger
                        probe = OpenAIProbe(os.environ.get("OPENAI_API_KEY", ""), ledger)
                elif model == MODEL_PRO4:
                    if not note_ledger.is_file():
                        raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
                    ledger = note_ledger
                    probe = UpstageProbe(os.environ.get("UPSTAGE_API_KEY", ""), ledger, model=model)
                else:
                    raise ValueError("TAGGING_MODEL_UNSUPPORTED")
                return LiveTaggingRuntime(
                    owner,
                    snapshot,
                    graph,
                    lease,
                    usage,
                    probe=probe,
                    ledger=ledger,
                    receipts=database.parent / "tagging-receipts" / snapshot["run_id"],
                )

        return LocalTagRunner(
            runner.store,
            runner.uploads,
            runner.parser,
            telemetry=runner.telemetry,
            transport=SyntheticTaggingTransport()
            if os.environ.get("LOCAL_TAGGING_MODE") == "local_synthetic"
            else None,
            live_factory=live_factory,
            max_workers=max_workers,
            claim_progress=claim_progress,
        )
    if stage == "extract":
        from proofops_agent.extraction import SyntheticClaimExtractor

        extractor: ClaimExtractorPort = SyntheticClaimExtractor()
        if os.environ.get("LOCAL_EXTRACTION_MODE") == "upstage_probe":
            from proofops.adapters.local.openai import OpenAIProbe
            from proofops.adapters.local.openrouter import MODEL as LUNA_MODEL
            from proofops.adapters.local.openrouter import OpenRouterProbe
            from proofops.adapters.local.upstage import MODEL, MODEL_PRO4, UpstageProbe
            from proofops_agent.upstage_extraction import (
                UpstageClaimExtractor,
                _profile_with_options,
            )

            # The existing user-authorized ledger must exist; never mint another allowance.
            ledger = note_ledger
            settings_path = os.environ.get("LOCAL_RUN_SETTINGS_PATH")
            if not settings_path:
                raise ValueError("LOCAL_RUN_SETTINGS_REQUIRED")
            settings = json.loads(Path(settings_path).read_text())
            maximum = settings.get("extraction_limits", {}).get("max_output_tokens")
            if type(maximum) is not int or not 1 <= maximum <= 1024:
                raise ValueError("LOCAL_RUNTIME_CONFIG_INVALID")
            frozen_profile = settings.get("extraction_profile")
            if not isinstance(frozen_profile, dict):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            frozen_model_hash = frozen_profile.get("model_sha256")
            model_match = next(
                (
                    (m, version)
                    for m, version in (
                        (MODEL, 1),
                        (MODEL_PRO4, 1),
                        (LUNA_MODEL, 1),
                        (LUNA_MODEL, 2),
                        ("gpt-6-luna", 2),
                    )
                    if _profile_with_options(m, wire_policy_version=version).model_sha256
                    == frozen_model_hash
                ),
                None,
            )
            if model_match is None:
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            model, wire_policy_version = model_match
            if model == LUNA_MODEL:
                probe = (provider_factories["llm"] if provider_factories else OpenRouterProbe)(
                    os.environ.get("OPENROUTER_API_KEY", ""),
                    luna_ledger,
                    wire_policy_version=wire_policy_version,
                )
            elif model == "gpt-6-luna":
                if provider_factories:
                    probe = provider_factories["llm"](
                        os.environ.get("OPENAI_API_KEY", ""),
                        luna_ledger,
                        wire_policy_version=2,
                    )
                else:
                    if not openai_ledger.is_file():
                        raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
                    probe = OpenAIProbe(os.environ.get("OPENAI_API_KEY", ""), openai_ledger)
            else:
                if not ledger.is_file():
                    raise ValueError("SHARED_BUDGET_LEDGER_REQUIRED")
                probe = UpstageProbe(os.environ.get("UPSTAGE_API_KEY", ""), ledger, model=model)
            display_profile = None
            if "display_text_policy" in settings:
                from proofops.application.ingest.display_text import POLICY, PROFILE

                if settings["display_text_policy"] != POLICY:
                    raise ValueError("DISPLAY_POLICY_MISMATCH")
                display_profile = PROFILE
            year_notation = settings.get("extraction_year_notation") is True
            context_opt_in = settings.get("extraction_context") is True
            table_context_opt_in = settings.get("extraction_table_context") is True
            rows_opt_in = settings.get("extraction_table_rows", False)
            recall_opt_in = settings.get("extraction_recall_prompt", False)
            if type(rows_opt_in) is not bool or type(recall_opt_in) is not bool:
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            source_ids_opt_in = settings.get("extraction_source_ids") is True
            atomic_opt_in = settings.get("extraction_atomic") is True
            atomic_v3_opt_in = settings.get("extraction_atomic_v3") is True
            failure_diagnostics_opt_in = settings.get("extraction_failure_diagnostics") is True
            linewrap_join = settings.get("extraction_linewrap_join") is True
            fragment_guard = settings.get("extraction_fragment_guard", False)
            if type(fragment_guard) is not bool:
                raise ValueError("UPSTAGE_EXTRACTION_FRAGMENT_GUARD_INVALID")
            if "extraction_linewrap_join" in settings and (
                not linewrap_join
                or settings.get("extraction_source_ids") is not True
                or atomic_opt_in
            ):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            if "extraction_atomic" in settings and (
                not atomic_opt_in or settings.get("extraction_source_ids") is not True
            ):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            if "extraction_atomic_v3" in settings and (
                not atomic_v3_opt_in or not (atomic_opt_in or rows_opt_in) or not source_ids_opt_in
            ):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            if "extraction_failure_diagnostics" in settings and (
                not failure_diagnostics_opt_in or not source_ids_opt_in
            ):
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            assertion_prompt_opt_in = settings.get("extraction_assertion_prompt") is True
            complete_selection_opt_in = settings.get("extraction_complete_selection") is True
            content_bounds_opt_in = settings.get("extraction_content_bounds") is True
            from proofops.application.tagging.preliminary import CONTEXT_POSITION_ORDER

            position_order = settings.get("position_context_order") == CONTEXT_POSITION_ORDER
            if settings.get("position_context_order") is not None and not position_order:
                raise ValueError("EXTRACTION_CONTEXT_ORDER_MISMATCH")
            if (
                year_notation
                or context_opt_in
                or source_ids_opt_in
                or display_profile
                or atomic_v3_opt_in
                or failure_diagnostics_opt_in
            ):
                # New-run opt-in only: the frozen settings must carry the exact
                # option-combination profile hash, otherwise fail closed.
                if frozen_profile != asdict(
                    _profile_with_options(
                        model,
                        year_notation=year_notation,
                        extraction_context=context_opt_in,
                        extraction_table_context=table_context_opt_in,
                        source_ids=source_ids_opt_in,
                        extraction_atomic=atomic_opt_in,
                        extraction_atomic_v3=atomic_v3_opt_in,
                        extraction_failure_diagnostics=failure_diagnostics_opt_in,
                        extraction_linewrap_join=linewrap_join,
                        extraction_fragment_guard=fragment_guard,
                        extraction_sentence_prefix=settings.get(
                            "extraction_sentence_prefix", False
                        ),
                        extraction_k1=settings.get("extraction_k1", False),
                        extraction_table_footnotes=settings.get(
                            "extraction_table_footnotes", False
                        ),
                        extraction_located_table_context=settings.get(
                            "extraction_located_table_context", False
                        ),
                        extraction_pb1=settings.get("extraction_pb1", False),
                        extraction_w9=settings.get("extraction_w9", False),
                        extraction_j3=settings.get("extraction_j3", False),
                        extraction_k3=settings.get("extraction_k3", False),
                        extraction_j7=settings.get("extraction_j7", False),
                        extraction_j8=settings.get("extraction_j8", False),
                        extraction_i3_wire=settings.get("extraction_i3_wire", False),
                        extraction_i4_identity=settings.get("extraction_i4_identity", False),
                        extraction_fxg_split=settings.get("extraction_fxg_split", False),
                        extraction_qt1_goal_split=settings.get("extraction_qt1_goal_split", False),
                        extraction_qc_native_figures=settings.get(
                            "extraction_qc_native_figures", False
                        ),
                        extraction_h1=settings.get("extraction_h1", False),
                        extraction_i5_tables=settings.get("extraction_i5_tables", False),
                        extraction_k6=settings.get("extraction_k6", False),
                        extraction_q1=settings.get("extraction_q1", False),
                        extraction_qt1=settings.get("extraction_qt1", False),
                        extraction_pb1_context_guard=settings.get(
                            "extraction_pb1_context_guard", False
                        ),
                        extraction_table_rows=rows_opt_in,
                        extraction_recall_prompt=recall_opt_in,
                        assertion_prompt=assertion_prompt_opt_in,
                        complete_selection=complete_selection_opt_in,
                        extraction_content_bounds=content_bounds_opt_in,
                        position_order=position_order,
                        wire_policy_version=wire_policy_version,
                        display_text_profile=display_profile,
                    )
                ):
                    raise ValueError("EXTRACTION_PROFILE_MISMATCH")
                extractor = UpstageClaimExtractor(
                    probe,
                    database.parent / "extraction-receipts",
                    max_tokens=maximum,
                    extraction_year_notation=year_notation,
                    extraction_context=context_opt_in,
                    extraction_table_context=table_context_opt_in,
                    extraction_source_ids=source_ids_opt_in,
                    extraction_atomic=atomic_opt_in,
                    extraction_atomic_v3=atomic_v3_opt_in,
                    extraction_failure_diagnostics=failure_diagnostics_opt_in,
                    extraction_linewrap_join=linewrap_join,
                    extraction_fragment_guard=fragment_guard,
                    extraction_sentence_prefix=settings.get("extraction_sentence_prefix", False),
                    extraction_k1=settings.get("extraction_k1", False),
                    extraction_table_footnotes=settings.get("extraction_table_footnotes", False),
                    extraction_located_table_context=settings.get(
                        "extraction_located_table_context", False
                    ),
                    extraction_pb1=settings.get("extraction_pb1", False),
                    extraction_w9=settings.get("extraction_w9", False),
                    extraction_j3=settings.get("extraction_j3", False),
                    extraction_k3=settings.get("extraction_k3", False),
                    extraction_j7=settings.get("extraction_j7", False),
                    extraction_j8=settings.get("extraction_j8", False),
                    extraction_i3_wire=settings.get("extraction_i3_wire", False),
                    extraction_i4_identity=settings.get("extraction_i4_identity", False),
                    extraction_fxg_split=settings.get("extraction_fxg_split", False),
                    extraction_qt1_goal_split=settings.get("extraction_qt1_goal_split", False),
                    extraction_qc_native_figures=settings.get(
                        "extraction_qc_native_figures", False
                    ),
                    extraction_h1=settings.get("extraction_h1", False),
                    extraction_i5_tables=settings.get("extraction_i5_tables", False),
                    extraction_k6=settings.get("extraction_k6", False),
                    extraction_q1=settings.get("extraction_q1", False),
                    extraction_qt1=settings.get("extraction_qt1", False),
                    extraction_pb1_context_guard=settings.get(
                        "extraction_pb1_context_guard", False
                    ),
                    extraction_table_rows=rows_opt_in,
                    extraction_recall_prompt=recall_opt_in,
                    extraction_assertion_prompt=assertion_prompt_opt_in,
                    extraction_complete_selection=complete_selection_opt_in,
                    extraction_content_bounds=content_bounds_opt_in,
                    position_order=position_order,
                    display_text_profile=display_profile,
                )
            elif (
                rows_opt_in
                or recall_opt_in
                or table_context_opt_in
                or assertion_prompt_opt_in
                or complete_selection_opt_in
                or content_bounds_opt_in
            ):
                # Table context refines the context profile; assertion prompt refines
                # source-ID selection; complete selection refines assertion mode;
                # content bounds refines source-ID.
                # None can stand alone without their required dependencies.
                raise ValueError("EXTRACTION_PROFILE_MISMATCH")
            else:
                extractor = UpstageClaimExtractor(
                    probe,
                    database.parent / "extraction-receipts",
                    max_tokens=maximum,
                )
        return LocalExtractRunner(
            runner.store,
            runner.uploads,
            runner.parser,
            extractor=extractor,
            telemetry=runner.telemetry,
            max_workers=max_workers,
            tag_composition=lambda: build_composition(
                stage="tag",
                provider_factories=provider_factories,
                provider_ledgers=provider_ledgers,
                claim_progress=claim_progress,
            ),
        )
    return runner
