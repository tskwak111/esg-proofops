"""Pure new-run extraction settings; CLI, files and resume remain caller-owned."""

from dataclasses import asdict

from proofops_agent.upstage_extraction import _profile_with_options


def build_extraction_settings(args, *, build_root, claim_pages, extraction_budget):
    """Preserve legacy opt-in rules and insertion order of the persisted settings."""
    if (
        args.extraction_year_notation
        or args.extraction_context
        or args.position_context_order
        or args.extraction_source_ids
        or args.extraction_content_bounds
    ):
        extraction_profile = asdict(
            _profile_with_options(
                args.model,
                year_notation=args.extraction_year_notation,
                extraction_context=args.extraction_context,
                extraction_table_context=args.extraction_table_context,
                source_ids=args.extraction_source_ids,
                extraction_atomic=args.extraction_atomic,
                extraction_atomic_v3=args.extraction_atomic_v3,
                extraction_failure_diagnostics=args.extraction_failure_diagnostics,
                extraction_linewrap_join=args.extraction_linewrap_join,
                extraction_fragment_guard=args.extraction_fragment_guard,
                extraction_sentence_prefix=args.extraction_sentence_prefix,
                extraction_k1=args.extraction_k1,
                extraction_pb1=args.extraction_pb1,
                extraction_w9=args.extraction_w9,
                extraction_j3=args.extraction_j3,
                extraction_k3=args.extraction_k3,
                extraction_j7=args.extraction_j7,
                extraction_j8=args.extraction_j8,
                extraction_i3_wire=args.extraction_i3_wire,
                extraction_i4_identity=args.extraction_i4_identity,
                extraction_qc_native_figures=args.extraction_qc_native_figures,
                extraction_fxg_split=getattr(args, "extraction_fxg_split", False),
                extraction_qt1_goal_split=getattr(args, "extraction_qt1_goal_split", False),
                extraction_h1=getattr(args, "extraction_h1", False),
                extraction_i5_tables=getattr(args, "extraction_i5_tables", False),
                extraction_k6=args.extraction_k6,
                extraction_q1=args.extraction_q1,
                extraction_qt1=args.extraction_qt1,
                extraction_pb1_context_guard=args.extraction_pb1_context_guard,
                extraction_table_footnotes=args.extraction_table_footnotes,
                extraction_located_table_context=getattr(
                    args, "extraction_located_table_context", False
                ),
                extraction_table_rows=args.extraction_table_rows,
                extraction_recall_prompt=args.extraction_recall_prompt,
                assertion_prompt=args.extraction_assertion_prompt,
                complete_selection=args.extraction_complete_selection,
                extraction_content_bounds=args.extraction_content_bounds,
                position_order=args.position_context_order,
                wire_policy_version=2 if args.model in ("openai/gpt-6-luna", "gpt-6-luna") else 1,
                display_text_profile=args.display_text_profile,
            )
        )
    else:
        extraction_profile = asdict(
            _profile_with_options(
                args.model,
                wire_policy_version=2 if args.model in ("openai/gpt-6-luna", "gpt-6-luna") else 1,
                display_text_profile=args.display_text_profile,
            )
        )
    settings = dict(
        build_root=str(build_root),
        extraction_profile=extraction_profile,
        extraction_limits=(
            dict(max_calls=args.max_calls, max_output_tokens=1024, claim_pages=claim_pages)
            if claim_pages is not None
            else dict(max_calls=args.max_calls, max_output_tokens=1024)
        ),
        budget_limits=extraction_budget,
    )
    if args.display_text_profile:
        from proofops.application.ingest.display_text import POLICY

        settings["display_text_policy"] = POLICY
    if args.extraction_year_notation:
        settings["extraction_year_notation"] = True
    if args.extraction_context:
        settings["extraction_context"] = True
    if args.position_context_order:
        from proofops.application.tagging.preliminary import CONTEXT_POSITION_ORDER

        settings["position_context_order"] = CONTEXT_POSITION_ORDER
    if args.extraction_table_context:
        settings["extraction_table_context"] = True
    if args.extraction_table_rows:
        settings["extraction_table_rows"] = True
    if args.extraction_recall_prompt:
        settings["extraction_recall_prompt"] = True
    if args.extraction_atomic:
        settings["extraction_atomic"] = True
    if args.extraction_atomic_v3:
        settings["extraction_atomic_v3"] = True
    if args.extraction_failure_diagnostics:
        settings["extraction_failure_diagnostics"] = True
    if args.extraction_linewrap_join:
        settings["extraction_linewrap_join"] = True
    if args.extraction_sentence_prefix:
        settings["extraction_sentence_prefix"] = True
    if args.extraction_k1:
        settings["extraction_k1"] = True
    if args.extraction_pb1_context_guard:
        settings["extraction_pb1_context_guard"] = True
    if args.extraction_w9:
        settings["extraction_w9"] = True
    if args.extraction_k3:
        settings["extraction_k3"] = True
    if args.extraction_table_footnotes:
        settings["extraction_table_footnotes"] = True
    if getattr(args, "extraction_located_table_context", False):
        settings["extraction_located_table_context"] = True
    if args.extraction_j8:
        settings["extraction_j8"] = True
    if args.extraction_k6:
        settings["extraction_k6"] = True
    if args.extraction_q1:
        settings["extraction_q1"] = True
    if args.extraction_qt1:
        settings["extraction_qt1"] = True
    if args.extraction_i4_identity:
        settings["extraction_i4_identity"] = True
    if getattr(args, "extraction_fxg_split", False):
        settings["extraction_fxg_split"] = True
    if getattr(args, "extraction_qt1_goal_split", False):
        settings["extraction_qt1_goal_split"] = True
    if args.extraction_qc_native_figures:
        settings["extraction_qc_native_figures"] = True
    if args.extraction_i3_wire:
        settings["extraction_i3_wire"] = True
    if getattr(args, "extraction_h1", False):
        settings["extraction_h1"] = True
    if getattr(args, "extraction_i5_tables", False):
        settings["extraction_i5_tables"] = True
    if args.extraction_j3:
        settings["extraction_j3"] = True
    if args.extraction_j7:
        settings["extraction_j7"] = True
    if args.extraction_pb1:
        settings["extraction_pb1"] = True
    if args.extraction_fragment_guard:
        settings["extraction_fragment_guard"] = True
    if args.extraction_source_ids:
        settings["extraction_source_ids"] = True
    if args.extraction_assertion_prompt:
        settings["extraction_assertion_prompt"] = True
    if args.extraction_complete_selection:
        settings["extraction_complete_selection"] = True
    if args.extraction_content_bounds:
        settings["extraction_content_bounds"] = True
    return settings, extraction_profile
