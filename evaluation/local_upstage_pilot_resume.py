"""Read-only restoration and comparison of a pilot's frozen source and policies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import ModuleType
from typing import Any


def apply_resume_metadata(
    pilot: ModuleType, args: argparse.Namespace, saved: dict[str, Any]
) -> None:
    """Reconstruct create-time inputs on ``args`` from a saved ``pilot.json``.

    This lets an operator re-serve a stored run with only ``--state`` by reading
    back the document path, page selection, and every policy flag that the
    pilot's strict resume guards compare against. It performs no model, network,
    or registration side effects; the recorded source path plus ``source_sha256``
    are still verified downstream, so a forged or substituted document is
    rejected exactly as before. Raises ``ValueError`` on a conflicting explicit
    override so callers can surface a clear CLI error.
    """
    stored_profile = saved.get("r108_profile")
    if stored_profile not in (None, pilot.FINALS_CANDIDATE, pilot.FINALS_CANDIDATE_V2):
        raise ValueError("unknown saved R108 profile")
    requested_profile = pilot.finals_candidate_profile(args)
    if requested_profile is not None and stored_profile != requested_profile:
        raise ValueError(f"--resume cannot add {requested_profile}; create a new run")
    args.r108_finals_candidate = stored_profile == pilot.FINALS_CANDIDATE
    args.r108_finals_candidate_v2 = stored_profile == pilot.FINALS_CANDIDATE_V2
    saved_memory = saved.get("parser_memory_bytes", 768 * 1024 * 1024)
    requested_memory = getattr(args, "parser_memory_bytes", None)
    if requested_memory is not None and requested_memory != saved_memory:
        raise ValueError("existing pilot parser memory limit changed; create a new run")
    args.parser_memory_bytes = pilot.parser_memory_limit(saved_memory)
    for field, default in (
        ("pipeline_profile", None),
        ("relation_profile", "source-quotes-v1"),
        ("preliminary_profile", None),
        ("claim_source_profile", None),
        ("display_text_profile", None),
        ("parser_source_recovery", None),
    ):
        requested = getattr(args, field, None)
        stored = saved.get(field, default)
        if requested is not None and requested != stored:
            raise ValueError(f"existing pilot {field} profile changed; create a new run")
        setattr(args, field, stored)
    if args.pdf is not None and Path(saved["source_path"]) != args.pdf.resolve():
        raise ValueError("--resume ignores conflicting explicit --pdf; omit it")
    if args.pdf is None:
        args.pdf = Path(saved["source_path"])
    if args.report_year is None:
        # The default only affects the unused create branch; resume never
        # re-registers a document version.
        args.report_year = saved.get("report_year", 0)
    if args.period_start is None:
        args.period_start = saved.get("period_start", "")
    if args.period_end is None:
        args.period_end = saved.get("period_end", "")
    if args.pages == "1" and saved.get("selected_pages"):
        args.pages = ",".join(str(page) for page in saved["selected_pages"])
    # Restore the frozen claim-page subset; a resume must not override the saved
    # scope. Reject a conflicting explicit --claim-pages instead of silently
    # re-narrowing a stored run.
    saved_claim_pages = saved.get("claim_pages")
    requested_claim_pages = getattr(args, "claim_pages", None)
    if requested_claim_pages is not None:
        requested = sorted(set(int(p) for p in requested_claim_pages.split(",")))
        if requested != (saved_claim_pages or []):
            raise ValueError("--resume ignores conflicting explicit --claim-pages; omit it")
    if saved_claim_pages:
        args.claim_pages = ",".join(str(page) for page in saved_claim_pages)
    # Restore each policy flag so the operator does not trip a false
    # "policy changed" rejection by omitting a flag the run was created with.
    saved_output_limit = saved.get("parser_max_output_bytes", 20_000_000)
    requested_output_limit = getattr(args, "parser_max_output_bytes", None)
    if requested_output_limit is not None and requested_output_limit != saved_output_limit:
        raise ValueError("--resume cannot change parser-max-output-bytes; create a new run")
    args.parser_max_output_bytes = pilot.parser_output_limit(saved_output_limit)
    args.vision_parse = saved.get("vision_parse", "off")
    args.parser = saved.get("parser_mode", "local")
    requested_ocr = getattr(args, "mixed_ocr_max_pages", 0)
    if requested_ocr and requested_ocr != saved.get("mixed_ocr_max_pages", 0):
        raise ValueError("--resume cannot change mixed OCR allowance; create a new run")
    args.mixed_ocr_max_pages = saved.get("mixed_ocr_max_pages", 0)
    args.model = saved.get("model", args.model)
    args.llm_provider = (
        "openai"
        if args.model == "gpt-6-luna"
        else ("openrouter" if args.model == "openai/gpt-6-luna" else "upstage")
    )
    args.verify_paragraphs = bool(saved.get("verify_paragraphs", False))
    args.verify_tables = bool(saved.get("verify_tables", False))
    args.verify_merged_tables = bool(saved.get("verify_merged_tables", False))
    args.verify_selected_cells = bool(saved.get("verify_selected_cells", False))
    args.native_quote_typography = bool(saved.get("native_quote_typography", False))
    args.repair_table_headers = bool(saved.get("repair_table_headers", False))
    args.verify_claim_spans = bool(saved.get("verify_claim_spans", False))
    args.claim_span_render_resolution = bool(saved.get("claim_span_render_resolution", False))
    args.claim_span_bullet_spacing = bool(saved.get("claim_span_bullet_spacing", False))
    args.claim_span_typography = bool(saved.get("claim_span_typography", False))
    args.raster_ocr = bool(saved.get("raster_ocr", False))
    args.live_tagging = bool(saved.get("live_tagging", False))
    args.live_relations = bool(saved.get("live_relations", False))
    args.preliminary_context = bool(saved.get("preliminary_context", False))
    args.preliminary_table_context = bool(saved.get("preliminary_table_context", False))
    args.preliminary_table_role = bool(saved.get("preliminary_table_role", False))
    args.preliminary_goal_role = bool(saved.get("preliminary_goal_role", False))
    args.preliminary_actor_role = bool(saved.get("preliminary_actor_role", False))
    args.preliminary_sentence_context = bool(saved.get("preliminary_sentence_context", False))
    args.preliminary_sentence_fallback = bool(saved.get("preliminary_sentence_fallback", False))
    args.preliminary_p2 = bool(saved.get("preliminary_p2", False))
    args.compact_element_wire = bool(saved.get("compact_element_wire", False))
    args.element_consistency = bool(saved.get("element_consistency", False))
    args.position_context_order = bool(saved.get("position_context_order", False))
    args.capacity_refresh = bool(saved.get("capacity_refresh", False))
    args.extraction_year_notation = bool(saved.get("extraction_year_notation", False))
    args.extraction_context = bool(saved.get("extraction_context", False))
    args.extraction_table_context = bool(saved.get("extraction_table_context", False))
    args.extraction_table_rows = bool(saved.get("extraction_table_rows", False))
    args.extraction_recall_prompt = bool(saved.get("extraction_recall_prompt", False))
    args.extraction_atomic = bool(saved.get("extraction_atomic", False))
    args.extraction_atomic_v3 = bool(saved.get("extraction_atomic_v3", False))
    args.extraction_failure_diagnostics = bool(saved.get("extraction_failure_diagnostics", False))
    args.extraction_linewrap_join = bool(saved.get("extraction_linewrap_join", False))
    args.extraction_fragment_guard = bool(saved.get("extraction_fragment_guard", False))
    args.extraction_sentence_prefix = bool(saved.get("extraction_sentence_prefix", False))
    args.extraction_k1 = bool(saved.get("extraction_k1", False))
    args.extraction_pb1 = bool(saved.get("extraction_pb1", False))
    args.extraction_w9 = bool(saved.get("extraction_w9", False))
    args.extraction_j3 = bool(saved.get("extraction_j3", False))
    args.extraction_k3 = bool(saved.get("extraction_k3", False))
    args.extraction_j7 = bool(saved.get("extraction_j7", False))
    args.extraction_j8 = bool(saved.get("extraction_j8", False))
    args.extraction_i3_wire = bool(saved.get("extraction_i3_wire", False))
    args.extraction_i4_identity = bool(saved.get("extraction_i4_identity", False))
    args.extraction_qc_native_figures = bool(saved.get("extraction_qc_native_figures", False))
    args.extraction_fxg_split = bool(saved.get("extraction_fxg_split", False))
    args.extraction_qt1_goal_split = bool(saved.get("extraction_qt1_goal_split", False))
    args.extraction_h1 = bool(saved.get("extraction_h1", False))
    args.extraction_i5_tables = bool(saved.get("extraction_i5_tables", False))
    args.extraction_k6 = bool(saved.get("extraction_k6", False))
    args.extraction_q1 = bool(saved.get("extraction_q1", False))
    args.extraction_qt1 = bool(saved.get("extraction_qt1", False))
    args.extraction_pb1_context_guard = bool(saved.get("extraction_pb1_context_guard", False))
    args.extraction_table_footnotes = bool(saved.get("extraction_table_footnotes", False))
    args.extraction_located_table_context = bool(
        saved.get("extraction_located_table_context", False)
    )
    args.extraction_source_ids = bool(saved.get("extraction_source_ids", False))
    args.extraction_assertion_prompt = bool(saved.get("extraction_assertion_prompt", False))
    args.extraction_complete_selection = bool(saved.get("extraction_complete_selection", False))
    args.extraction_content_bounds = bool(saved.get("extraction_content_bounds", False))
    pilot.apply_finals_candidate(args, restoring=True)
    if saved.get("tagging_max_calls"):
        args.tagging_max_calls = saved["tagging_max_calls"]
    saved_total = saved.get("extraction_total_calls")
    requested_total = getattr(args, "extraction_total_calls", None)
    if requested_total is not None and requested_total != saved_total:
        raise ValueError("--resume cannot change extraction total; create a new run")
    args.extraction_total_calls = saved_total
    if "extraction_batch_calls" in saved:
        args.max_calls = saved["extraction_batch_calls"]
    if args.raster_ocr and saved.get("raster_policy"):
        # Reuse the exact stored raster limits so the regenerated raster policy
        # dict matches the manifest's stored policy under the resume guard.
        args.raster_max_pages = saved["raster_policy"].get("max_pages", args.raster_max_pages)
        args.raster_max_calls = saved["raster_policy"].get("max_calls", args.raster_max_calls)


def _restore_resume_args(
    pilot: ModuleType,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    resume_state: Path,
    resume_manifest: Path,
) -> None:
    """Restore saved inputs and reject new capabilities on a read-only resume."""
    if args.invoke:
        parser.error("--resume is read-only for model calls; omit --invoke")
    if args.ai_project_review:
        parser.error("--ai-project-review only applies to a NEW run; omit it with --resume")
    if not resume_manifest.exists():
        parser.error(f"--resume requires an existing pilot.json under {resume_state}")
    requested_year_notation = args.extraction_year_notation
    requested_context = args.extraction_context
    requested_table_context = args.extraction_table_context
    requested_rows = args.extraction_table_rows
    requested_recall = args.extraction_recall_prompt
    requested_atomic = args.extraction_atomic
    requested_atomic_v3 = args.extraction_atomic_v3
    requested_failure_diagnostics = args.extraction_failure_diagnostics
    requested_sentence_prefix = args.extraction_sentence_prefix
    requested_k1 = args.extraction_k1
    requested_j7 = args.extraction_j7
    requested_linewrap_join = args.extraction_linewrap_join
    requested_source_ids = args.extraction_source_ids
    requested_assertion_prompt = args.extraction_assertion_prompt
    requested_complete_selection = args.extraction_complete_selection
    requested_content_bounds = args.extraction_content_bounds
    requested_preliminary_table = args.preliminary_table_context
    requested_preliminary_role = args.preliminary_table_role
    requested_preliminary_goal_role = args.preliminary_goal_role
    requested_preliminary_sentence_fallback = args.preliminary_sentence_fallback
    requested_preliminary_sentence_context = args.preliminary_sentence_context
    requested_preliminary_actor_role = args.preliminary_actor_role
    requested_preliminary_p2 = args.preliminary_p2
    requested_compact_element_wire = args.compact_element_wire
    requested_element_consistency = args.element_consistency
    requested_position_order = args.position_context_order
    requested_capacity_refresh = getattr(args, "capacity_refresh", False)
    requested_render_resolution = args.claim_span_render_resolution
    requested_bullet_spacing = args.claim_span_bullet_spacing
    requested_typography = args.claim_span_typography
    try:
        pilot.apply_resume_metadata(args, json.loads(resume_manifest.read_text()))
    except ValueError as exc:
        parser.error(str(exc))
    if requested_year_notation and not args.extraction_year_notation:
        parser.error("--resume cannot add extraction year-notation; create a new run")
    if requested_context and not args.extraction_context:
        parser.error("--resume cannot add extraction context; create a new run")
    if requested_table_context and not args.extraction_table_context:
        parser.error("--resume cannot add extraction table context; create a new run")
    if requested_rows and not args.extraction_table_rows:
        parser.error("--resume cannot add extraction table rows; create a new run")
    if requested_recall and not args.extraction_recall_prompt:
        parser.error("--resume cannot add extraction recall prompt; create a new run")
    if requested_atomic and not args.extraction_atomic:
        parser.error("--resume cannot add extraction atomic; create a new run")
    if requested_atomic_v3 and not args.extraction_atomic_v3:
        parser.error("--resume cannot add extraction atomic v3; create a new run")
    if requested_failure_diagnostics and not args.extraction_failure_diagnostics:
        parser.error("--resume cannot add extraction failure diagnostics; create a new run")
    if requested_sentence_prefix and not args.extraction_sentence_prefix:
        parser.error("--resume cannot add extraction sentence prefix; create a new run")
    if requested_k1 and not args.extraction_k1:
        parser.error("--resume cannot add K1 boundaries; create a new run")
    if requested_j7 and not args.extraction_j7:
        parser.error("--resume cannot add extraction J7; create a new run")
    if requested_linewrap_join and not args.extraction_linewrap_join:
        parser.error("--resume cannot add extraction linewrap join; create a new run")
    if requested_source_ids and not args.extraction_source_ids:
        parser.error("--resume cannot add extraction source-id selection; create a new run")
    if requested_assertion_prompt and not args.extraction_assertion_prompt:
        parser.error("--resume cannot add extraction assertion prompt; create a new run")
    if requested_complete_selection and not args.extraction_complete_selection:
        parser.error("--resume cannot add extraction complete selection; create a new run")
    if requested_content_bounds and not args.extraction_content_bounds:
        parser.error("--resume cannot add extraction content bounds; create a new run")
    if requested_preliminary_table and not args.preliminary_table_context:
        parser.error("--resume cannot add preliminary table context; create a new run")
    if requested_preliminary_role and not args.preliminary_table_role:
        parser.error("--resume cannot add preliminary table role resolution; create a new run")
    if requested_preliminary_goal_role and not args.preliminary_goal_role:
        parser.error("--resume cannot add preliminary goal role; create a new run")
    if requested_preliminary_sentence_fallback and not args.preliminary_sentence_fallback:
        parser.error("--resume cannot add sentence fallback; create a new run")
    if requested_preliminary_sentence_context and not args.preliminary_sentence_context:
        parser.error("--resume cannot add sentence context; create a new run")
    if requested_preliminary_actor_role and not args.preliminary_actor_role:
        parser.error("--resume cannot add preliminary actor role; create a new run")
    if requested_preliminary_p2 and not args.preliminary_p2:
        parser.error("--resume cannot add preliminary P2; create a new run")
    if requested_element_consistency and not args.element_consistency:
        parser.error("--resume cannot add element consistency; create a new run")
    if requested_compact_element_wire and not args.compact_element_wire:
        parser.error("--resume cannot add compact element wire; create a new run")
    if requested_position_order and not args.position_context_order:
        parser.error("--resume cannot add position context order; create a new run")
    if requested_capacity_refresh and not args.capacity_refresh:
        parser.error("--resume cannot add capacity refresh; create a new run")
    if requested_render_resolution and not args.claim_span_render_resolution:
        parser.error("--resume cannot add claim-span render resolution; create a new run")
    if requested_bullet_spacing and not args.claim_span_bullet_spacing:
        parser.error("--resume cannot add claim-span bullet spacing; create a new run")
    if requested_typography and not args.claim_span_typography:
        parser.error("--resume cannot add claim-span typography; create a new run")


def _validate_existing_pilot(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    manifest: dict[str, Any],
    *,
    raster: dict[str, Any],
    digest: str,
    claim_pages: list[int] | None,
) -> None:
    """Reject changes to the saved source, scope, and policy before execution."""
    if manifest.get("vision_parse", "off") != args.vision_parse:
        raise ValueError("pilot vision parse policy changed; create a new state directory")
    if manifest.get("mixed_ocr_max_pages", 0) != args.mixed_ocr_max_pages:
        raise ValueError("existing pilot mixed OCR allowance changed; create a new run")
    if manifest.get("parser_mode", "local") != args.parser:
        raise ValueError("pilot parser mode changed; create a new state directory")
    if manifest.get("capacity_refresh", False) != getattr(args, "capacity_refresh", False):
        raise ValueError("pilot capacity refresh policy changed; create a new state directory")
    if args.extraction_total_calls is not None and (
        manifest.get("extraction_total_calls") != args.extraction_total_calls
    ):
        raise ValueError("pilot extraction total changed; create a new state directory")
    if manifest.get("raster_ocr", False) != args.raster_ocr or (
        args.raster_ocr and manifest.get("raster_policy") != raster["raster_policy"]
    ):
        raise ValueError("pilot raster policy changed; create a new state directory")
    if manifest.get("preliminary_profile") != args.preliminary_profile:
        raise ValueError("existing pilot preliminary profile changed; create a new run")
    if manifest.get("relation_profile", "source-quotes-v1") != args.relation_profile:
        raise ValueError("pilot relation profile changed; create a new state directory")
    if manifest.get("display_text_profile") != args.display_text_profile:
        raise ValueError("pilot display text profile changed; create a new state directory")
    if manifest.get("claim_source_profile") != args.claim_source_profile:
        raise ValueError("pilot claim source profile changed; create a new state directory")
    if manifest.get("live_relations", False) != args.live_relations:
        raise ValueError("pilot relation policy changed; create a new state directory")
    if manifest.get("preliminary_context", False) != args.preliminary_context:
        raise ValueError("pilot preliminary context policy changed; create a new state directory")
    if manifest.get("preliminary_table_context", False) != args.preliminary_table_context:
        raise ValueError("pilot preliminary table policy changed; create a new state directory")
    if manifest.get("preliminary_table_role", False) != args.preliminary_table_role:
        raise ValueError("pilot preliminary table role policy changed; create a new state dir")
    if manifest.get("preliminary_goal_role", False) != args.preliminary_goal_role:
        raise ValueError("pilot preliminary goal role policy changed; create a new state dir")
    if manifest.get("preliminary_sentence_fallback", False) != args.preliminary_sentence_fallback:
        raise ValueError("pilot sentence fallback policy changed; create a new state dir")
    if manifest.get("preliminary_sentence_context", False) != args.preliminary_sentence_context:
        raise ValueError("pilot sentence context policy changed; create a new state dir")
    if manifest.get("preliminary_p2", False) != args.preliminary_p2:
        raise ValueError("pilot preliminary P2 policy changed; create a new state dir")
    if manifest.get("element_consistency", False) != args.element_consistency:
        raise ValueError("pilot element consistency changed; create a new state dir")
    if manifest.get("compact_element_wire", False) != args.compact_element_wire:
        raise ValueError("pilot element wire policy changed; create a new state dir")
    if args.position_context_order:
        from proofops.application.tagging.preliminary import CONTEXT_POSITION_ORDER

        if manifest.get("position_context_order") != CONTEXT_POSITION_ORDER:
            raise ValueError("pilot context order policy changed; create a new state dir")
    elif manifest.get("position_context_order") is not None:
        raise ValueError("pilot context order policy changed; create a new state dir")
    if manifest.get("live_tagging", False) != args.live_tagging or (
        args.live_tagging and manifest.get("tagging_max_calls") != args.tagging_max_calls
    ):
        raise ValueError("pilot tagging policy changed; create a new state directory")
    if manifest.get("repair_table_headers", False) != args.repair_table_headers:
        raise ValueError("pilot table repair changed; create a new state directory")
    if manifest.get("verify_merged_tables", False) != args.verify_merged_tables:
        raise ValueError("pilot merged table verification changed; create a new state directory")
    if manifest.get("verify_tables", False) != args.verify_tables:
        raise ValueError("pilot table verification changed; create a new state directory")
    if manifest.get("verify_selected_cells", False) != args.verify_selected_cells:
        raise ValueError("pilot selected cell policy changed; create a new state directory")
    if manifest.get("native_quote_typography", False) != args.native_quote_typography:
        raise ValueError("pilot quote typography policy changed; create a new state directory")
    if manifest.get("extraction_year_notation", False) != args.extraction_year_notation:
        raise ValueError(
            "pilot extraction year-notation policy changed; create a new state directory"
        )
    if manifest.get("extraction_context", False) != args.extraction_context:
        raise ValueError("pilot extraction context policy changed; create a new state directory")
    if manifest.get("extraction_table_context", False) != args.extraction_table_context:
        raise ValueError(
            "pilot extraction table context policy changed; create a new state directory"
        )
    for name in (
        "extraction_sentence_prefix",
        "extraction_k1",
        "extraction_table_rows",
        "extraction_recall_prompt",
        "extraction_fragment_guard",
        "extraction_pb1",
        "extraction_w9",
        "extraction_j3",
        "extraction_k3",
        "extraction_j7",
        "extraction_j8",
        "extraction_i3_wire",
        "extraction_i4_identity",
        "extraction_qc_native_figures",
        "extraction_fxg_split",
        "extraction_qt1_goal_split",
        "extraction_h1",
        "extraction_i5_tables",
        "extraction_k6",
        "extraction_q1",
        "extraction_qt1",
        "extraction_pb1_context_guard",
        "extraction_table_footnotes",
        "extraction_located_table_context",
    ):
        if manifest.get(name, False) != getattr(args, name, False):
            raise ValueError(name + " policy changed; create a new state directory")
    if manifest.get("extraction_atomic", False) != args.extraction_atomic:
        raise ValueError("pilot extraction atomic policy changed; create a new state directory")
    if manifest.get("extraction_atomic_v3", False) != args.extraction_atomic_v3:
        raise ValueError("pilot extraction atomic v3 policy changed; create a new state directory")
    if manifest.get("extraction_failure_diagnostics", False) != args.extraction_failure_diagnostics:
        raise ValueError(
            "pilot extraction failure diagnostics changed; create a new state directory"
        )
    if manifest.get("extraction_linewrap_join", False) != args.extraction_linewrap_join:
        raise ValueError(
            "pilot extraction linewrap join policy changed; create a new state directory"
        )
    if manifest.get("extraction_source_ids", False) != args.extraction_source_ids:
        raise ValueError("pilot extraction source-id policy changed; create a new state directory")
    if manifest.get("extraction_content_bounds", False) != args.extraction_content_bounds:
        raise ValueError(
            "pilot extraction content-bounds policy changed; create a new state directory"
        )
    if manifest["source_sha256"] != digest:
        raise ValueError("pilot source changed")
    if manifest.get("claim_pages") != claim_pages:
        raise ValueError("pilot claim-page scope changed; create a new state directory")
    if manifest.get("verify_claim_spans", False) != args.verify_claim_spans:
        parser.error("Existing state has a different claim span policy")
    if manifest.get("claim_span_render_resolution", False) != args.claim_span_render_resolution:
        parser.error("Existing state has a different claim span render-resolution policy")
    if manifest.get("claim_span_bullet_spacing", False) != args.claim_span_bullet_spacing:
        parser.error("Existing state has a different claim span bullet-spacing policy")
    if manifest.get("claim_span_typography", False) != args.claim_span_typography:
        parser.error("Existing state has a different claim span typography policy")
    if manifest.get("verify_paragraphs", False) != args.verify_paragraphs:
        raise ValueError("pilot verification policy changed; create a new state directory")
    if manifest.get("model", "solar-pro3") != args.model:
        raise ValueError("pilot model changed; create a new state directory")
