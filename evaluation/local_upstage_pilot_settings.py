"""Persist parser and model settings once, preserving existing resume files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES


def _prepare_run_settings(
    pilot: ModuleType,
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
    """Write new-run settings; preserve existing parser and settings files on resume."""
    from proofops.application.ingest.graph_fusion import ParserProfile

    from evaluation.pilot_preparation import build_extraction_settings
    from evaluation.scope_input import MAX_UPLOAD_BYTES

    if not manifest_path.exists():
        from proofops.adapters.local.table_source_verification import policy_sha256 as table_policy

        if args.verify_merged_tables:
            from proofops.adapters.local.merged_table_verification import (
                policy_sha256 as table_policy,
            )
        elif args.verify_selected_cells:
            from proofops.adapters.local.selected_cell_table_verification import (
                policy_sha256 as table_policy,
            )

        if args.claim_source_profile in PAGE_OCR_PROFILES:
            if args.raster_ocr or args.native_quote_typography:
                parser.error("page OCR requires no raster/native quote-typography composition")
            if args.verify_tables or args.verify_merged_tables or args.verify_selected_cells:
                from proofops.adapters.local.claim_source_policies import page_ocr_profile

                table_policy = page_ocr_profile(args.claim_source_profile).table_policy_sha256

        config = ParserProfile(
            str(pilot.uuid4()),
            max_bytes=MAX_UPLOAD_BYTES,
            java_executable=pilot.parser_java_executable(),
            timeout_seconds=120,
            memory_bytes=pilot.parser_memory_limit(args.parser_memory_bytes),
            local_resource_policy=getattr(args, "parser_local_resource_policy", None),
            output_policy=getattr(args, "parser_output_policy", None),
            execution_policy=getattr(args, "parser_execution_policy", None),
            max_output_bytes=pilot.parser_output_limit(args.parser_max_output_bytes),
            table_source_policy_sha256=(
                table_policy()
                if args.verify_tables or args.verify_merged_tables or args.verify_selected_cells
                else None
            ),
            table_structure_repair="odl_header_v2" if args.repair_table_headers else None,
            vision_parse=args.vision_parse,
            parser_mode=args.parser,
            physical_pages=tuple(pages) if args.parser == "mixed-v1" else (),
            claim_physical_pages=tuple(claim_pages or ()) if args.parser == "mixed-v1" else (),
            mixed_ocr_max_pages=args.mixed_ocr_max_pages,
            failure_policy=(
                getattr(args, "parser_failure_policy", None) or "partial-v1"
                if args.pipeline_profile
                in (
                    "finals-unattended-v1",
                    "finals-unattended-v2",
                    "finals-unattended-j3-v1",
                    "finals-unattended-j7-v1",
                    "finals-unattended-j8-v1",
                )
                else None
            ),
            upstage_glyph_boxes=args.parser in ("upstage", "mixed-v1"),
            upstage_region_words=args.parser in ("upstage", "mixed-v1"),
            source_recovery=args.parser_source_recovery,
            table_claims_profile=("pb1-w9-v1" if args.extraction_w9 else "pb1-v1")
            if args.extraction_pb1
            else None,
        )
        (state / "parser.json").write_text(json.dumps(config.config_snapshot()))
        settings, extraction_profile = build_extraction_settings(
            args,
            build_root=pilot.ROOT,
            claim_pages=claim_pages,
            extraction_budget=extraction_budget,
        )
        settings.update(raster)
        if pilot.finals_candidate_profile(args):
            settings["r108_profile"] = pilot.finals_candidate_profile(args)
        if args.verify_claim_spans:
            settings["claim_source_policy"] = pilot.claim_source_policy_for(args)
        if args.pipeline_profile:
            settings["pipeline_profile"] = args.pipeline_profile
        if args.analysis_policy_sha256:
            from proofops.application.analysis_profile import policy_for

            policy_for(args.pipeline_profile, pinned_hash=args.analysis_policy_sha256)
            settings["analysis_policy_sha256"] = args.analysis_policy_sha256
        if args.live_tagging:
            from proofops.application.analysis_profile import policy_for

            analysis_policy = (
                policy_for(args.pipeline_profile, pinned_hash=args.analysis_policy_sha256)
                if args.pipeline_profile == "finals-unattended-v2"
                else {}
            )
            definition_profile = analysis_policy.get("element_definition_profile", "qi1-v1")
            if (
                definition_profile not in ("finals-i1-v1", "finals-i1-v2")
                and analysis_policy.get("semantic_definition_profile") == "w8-v1"
            ):
                definition_profile = "w8-v1"
            settings.update(
                pilot.live_tagging_settings(
                    args.tagging_max_calls,
                    prompt_profile=getattr(args, "tagging_prompt_profile", None),
                    element_definition_profile=definition_profile
                    if args.pipeline_profile
                    in (
                        "finals-unattended-v2",
                        "finals-unattended-j3-v1",
                        "finals-unattended-j7-v1",
                        "finals-unattended-j8-v1",
                    )
                    else None,
                    model_id=(
                        "gpt-6-luna" if args.llm_provider == "openai" else "openai/gpt-6-luna"
                    )
                    if args.llm_provider in ("openrouter", "openai")
                    else "solar-pro4",
                    relations=args.live_relations,
                    relation_profile=args.relation_profile,
                    preliminary_context=args.preliminary_context,
                    preliminary_table_context=args.preliminary_table_context,
                    preliminary_table_role=args.preliminary_table_role,
                    preliminary_goal_role=args.preliminary_goal_role,
                    preliminary_actor_role=args.preliminary_actor_role,
                    preliminary_pb1=args.extraction_pb1,
                    preliminary_sentence_context=args.preliminary_sentence_context,
                    preliminary_sentence_fallback=args.preliminary_sentence_fallback,
                    preliminary_p2=args.preliminary_p2,
                    preliminary_profile=args.preliminary_profile,
                    compact_element_wire=args.compact_element_wire,
                    element_consistency=args.element_consistency,
                    position_context_order=args.position_context_order,
                    capacity_refresh=getattr(args, "capacity_refresh", False),
                )
            )
            from proofops.application.tagging.service import output_reservation_tokens

            bound = settings["input_reservation_policy"]["reservation_input_tokens"]
            output_bound = output_reservation_tokens(
                model_id=settings["tagging_settings"]["model_id"],
                max_tokens=4096,
                synthetic=False,
            )
            settings["budget_limits"]["input_tokens"] += bound * args.tagging_max_calls
            settings["budget_limits"]["output_tokens"] += output_bound * args.tagging_max_calls
            settings["budget_limits"]["roles"].append(
                dict(
                    role="tagger",
                    max_calls=args.tagging_max_calls,
                    max_input_tokens=bound,
                    max_output_tokens=output_bound,
                    max_context_tokens=bound + output_bound,
                )
            )
            if "decision_settings" in settings:
                calls = args.tagging_max_calls * 2
                settings["budget_limits"]["input_tokens"] += 66560 * calls
                settings["budget_limits"]["output_tokens"] += 4096 * calls
                settings["budget_limits"]["roles"].append(
                    dict(
                        role="decision",
                        max_calls=calls,
                        max_input_tokens=66560,
                        max_output_tokens=4096,
                        max_context_tokens=70656,
                    )
                )
        (state / "settings.json").write_text(json.dumps(settings))
        return settings, extraction_profile
    return None, None
