"""Pilot CLI declaration and argument validation before any run is created."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES


def _build_parser(description: str | None) -> argparse.ArgumentParser:
    """Construct the existing CLI without parsing or applying profiles."""
    parser = argparse.ArgumentParser(description=description)
    # --pdf/--report-year/--period-* are only needed to *create* a new pilot.
    # On --resume they are read back from the saved pilot.json so an operator
    # can re-serve a stored run without re-typing document metadata. The source
    # sha256 integrity check against the recorded PDF path is still enforced.
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--tenant-id", type=UUID, help="Private hosted worker tenant scope")
    parser.add_argument("--pages", default="1")
    parser.add_argument("--vision-parse", choices=("auto", "all", "off"))
    parser.add_argument(
        "--mixed-ocr-max-pages",
        type=int,
        default=0,
        help="mixed-v1 only: maximum evidence-only OCR pages; shared ledger still gates dispatch.",
    )
    parser.add_argument("--parser", choices=("upstage", "local", "mixed-v1"), default="upstage")
    parser.add_argument(
        "--parser-source-recovery",
        choices=("ps1-v1", "native-continuation-k8-v1"),
        help="NEW run only: literal location recovery and paragraph continuation.",
    )
    parser.add_argument("--report-year", type=int)
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    parser.add_argument("--company-name", help="Explicit legal name for a NEW run")
    parser.add_argument("--company-registration", help="Verified identifier, e.g. DART:00266961")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse an existing pilot.json: reconstruct pdf/year/period and all "
        "policy flags from saved metadata (no model calls, no registration).",
    )
    parser.add_argument(
        "--parser-max-output-bytes",
        type=int,
        default=None,
        help="NEW run parser artifact cap (default 20000000; max 128 MiB).",
    )
    parser.add_argument("--extraction-sentence-prefix", action="store_true")
    parser.add_argument("--extraction-k1", action="store_true")
    parser.add_argument("--extraction-pb1", action="store_true")
    parser.add_argument("--extraction-w9", action="store_true")
    parser.add_argument("--extraction-j3", action="store_true")
    parser.add_argument("--extraction-k3", action="store_true")
    parser.add_argument("--extraction-j7", action="store_true")
    parser.add_argument("--extraction-pb1-context-guard", action="store_true")
    parser.add_argument("--extraction-table-footnotes", action="store_true")
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument(
        "--parser-memory-bytes",
        type=int,
        default=None,
        help="NEW run parser process-tree memory cap (default 768 MiB; max 4 GiB).",
    )
    parser.add_argument(
        "--extraction-total-calls",
        type=int,
        default=None,
        help="NEW run's total extraction allowance across batches (max 2000); "
        "defaults to --max-calls. The shared USD20 ceiling still applies.",
    )
    parser.add_argument(
        "--claim-pages",
        default=None,
        help="Optional comma-separated 1-based subset of --pages to extract claims "
        "from. Parse/evidence/retrieval still cover all --pages; omit to keep the "
        "legacy behaviour where claims are discovered across every selected page.",
    )
    parser.add_argument(
        "--llm-provider", choices=["upstage", "openrouter", "openai"], default="openrouter"
    )
    parser.add_argument("--model", choices=["solar-pro3", "solar-pro4"])
    parser.add_argument("--verify-paragraphs", action="store_true")
    parser.add_argument(
        "--display-text-profile",
        choices=["glyph-joined-display-v1"],
        help="New-run only: glyph-proven display text with pinned raw offset maps.",
    )
    parser.add_argument("--native-quote-typography", action="store_true")
    table_checks = parser.add_mutually_exclusive_group()
    table_checks.add_argument("--verify-tables", action="store_true")
    table_checks.add_argument("--verify-merged-tables", action="store_true")
    table_checks.add_argument("--verify-selected-cells", action="store_true")
    parser.add_argument("--repair-table-headers", action="store_true")
    parser.add_argument("--verify-claim-spans", action="store_true")
    parser.add_argument(
        "--claim-span-bullet-spacing",
        action="store_true",
        help="Opt-in (R19), NEW-run only (never applies on --resume or an "
        "existing state directory): additionally re-check a claim span the base "
        "verifier left unresolved as text_mismatch ONLY because its native "
        "word-token join inserted one space at a bullet line's first content "
        "token, confirmed by that boundary's unique smallest real ink gap and by "
        "the existing unchanged rendered-text check. Requires "
        "--claim-span-render-resolution, whose recovery it preserves and wraps. "
        "Pins its own policy and receipt schema; existing runs and receipts are "
        "unchanged.",
    )
    parser.add_argument(
        "--claim-span-typography",
        action="store_true",
        help="Opt-in (R24), NEW-run only (never applies on --resume or an "
        "existing state directory): additionally re-check a claim span the "
        "wrapped verifiers already READ successfully but left unresolved only "
        "because the rendered reader spells the document's own typography "
        "differently. The native gate stays the base verifier's UNFOLDED "
        "unique-quote check; a finite five-entry fold (the shipped curly-quote "
        "map plus U+00B7 -> U+2022) is applied to the rendered text and the "
        "quote only. No digit, space, case, dash, subscript or fuzzy "
        "normalization, and the token-boundary refusal is not relaxed. "
        "Requires --claim-span-bullet-spacing, whose recovery it preserves and "
        "wraps. Pins its own policy and receipt schema; existing runs and "
        "receipts are unchanged.",
    )
    parser.add_argument(
        "--claim-span-render-resolution",
        action="store_true",
        help="Opt-in (R13/R15), NEW-run only (never applies on --resume or an "
        "existing state directory): additionally re-check a claim span the base "
        "verifier left unresolved only on its rendered-OCR string, using the "
        "existing deterministic-scale crop reader. Requires --verify-claim-spans. "
        "Pins its own policy and receipt schema; existing runs and receipts are "
        "unchanged.",
    )
    parser.add_argument(
        "--extraction-year-notation",
        action="store_true",
        help="Opt-in, NEW-run only in effect (pinned on --resume): accept the finite "
        "explicit abbreviated-year punctuation (‘ + two ASCII digits, e.g. ‘24 년도) "
        "as source punctuation rather than an unterminated paired quotation. "
        "No year is inferred and no text is normalized; genuinely truncated "
        "quotations still fail closed.",
    )
    parser.add_argument(
        "--extraction-context",
        action="store_true",
        help="Opt-in, NEW-run only in effect (pinned on --resume): send bounded, "
        "source-linked heading/adjacent context blocks with each extraction call "
        "under a distinct context profile. The graph identity is verified per "
        "call and the actual wire content (blocks and omissions) is hash-bound "
        "into the receipt; quotes still resolve from the focal source only.",
    )
    parser.add_argument(
        "--position-context-order",
        action="store_true",
        help="New-run opt-in: page/top-left/content context order for extraction "
        "and table-role preliminary.",
    )
    parser.add_argument(
        "--ai-project-review",
        action="store_true",
        help="Opt-in, NEW-run only (never applies on --resume or an existing "
        "manifest): promote the pilot's draft rulepack to a validated, "
        "AI-delegated-reviewed pack via scripts.review_rulepack."
        "promote_and_review_pack, and use ITS returned rule_pack_id for this "
        "run instead of the unreviewed draft. This is not an independent "
        "expert gold or legal-standard approval; GAPs are preserved and "
        "recorded under the delegated source authority, not human sign-off.",
    )
    parser.add_argument("--raster-ocr", action="store_true")
    parser.add_argument("--raster-max-pages", type=int, default=4)
    parser.add_argument("--raster-max-calls", type=int, default=1)
    parser.add_argument("--invoke", action="store_true")
    parser.add_argument(
        "--pipeline-profile",
        choices=[
            "unattended-v1",
            "finals-unattended-v1",
            "finals-unattended-v2",
            "finals-unattended-j3-v1",
            "finals-unattended-j7-v1",
            "finals-unattended-j8-v1",
        ],
        help="New run only: read-only provisional results and claim-isolated completion.",
    )
    parser.add_argument("--live-tagging", action="store_true")
    parser.add_argument("--live-relations", action="store_true")
    parser.add_argument(
        "--preliminary-profile",
        choices=["decision-v1"],
        help="New run: OpenAI Decisions + JEV judgments with Luna literal quotes.",
    )
    parser.add_argument(
        "--relation-profile",
        choices=["source-quotes-v1", "occurrence-v2", "occurrence-v3", "decision-gate-v1"],
        help="Pin a relation contract for a NEW run; requires --live-relations.",
    )
    parser.add_argument(
        "--claim-source-profile",
        "--rendered-reader-profile",
        choices=[
            "glyph-alignment-v1",
            "table-claim-spans-v1",
            "claim-source-v3",
            *PAGE_OCR_PROFILES,
        ],
        help="Pin source reader for a NEW run; requires --verify-claim-spans.",
    )
    parser.add_argument(
        "--element-consistency",
        action="store_true",
        help="Opt in to deterministic per-element evidence routing (v6).",
    )
    parser.add_argument(
        "--compact-element-wire",
        action="store_true",
        help="Opt-in v5 element wire; pins a distinct model/cache identity for new runs.",
    )
    parser.add_argument(
        "--preliminary-context",
        action="store_true",
        help="Opt-in: preliminary classification receives bounded, source-bound "
        "interpretation-only context (parent paragraph/section heading/nearby "
        "same-page prose) alongside the atomic claim quote. Requires "
        "--live-tagging. Selects a distinct model_profile/prompt pair; a stored "
        "run's flag cannot be changed on --resume.",
    )
    parser.add_argument(
        "--preliminary-table-context",
        action="store_true",
        help="Opt-in (R12): additionally offer the claim value's OWN table row/column "
        "header cells as extra numbered sources, but only those that pass real source "
        "verification and an actual same-table row/column association; unverified axes "
        "travel as context only. Requires --preliminary-context. Selects a distinct "
        "model_profile/prompt pair and cannot be added on --resume.",
    )
    parser.add_argument(
        "--preliminary-table-role",
        action="store_true",
        help="Opt-in (R16): keep the exact --preliminary-table-context wire shape and "
        "validator, and send one additive prompt suffix that resolves the frozen "
        "atomic-source instructions against the table-axis permission, so a verified "
        "column header literally naming a measure or a reported interval can become "
        "metric/reporting_period instead of collapsing to null. Target/plan year "
        "columns stay excluded and track is never forced. Requires "
        "--preliminary-table-context; selects its own model_profile/prompt pair and "
        "cannot be added on --resume.",
    )
    parser.add_argument(
        "--preliminary-goal-role",
        action="store_true",
        help="Opt-in (R34): keep the exact --preliminary-table-role wire shape and "
        "validator, and send one additive prompt suffix that clarifies goal-track "
        "metric extraction when source 0 states a named company target or standard "
        "(e.g. RE100, carbon-neutrality). A regulatory designation or predicted future "
        "external inclusion is not itself a commitment; a stated future risk is not "
        "automatically goal. Adds no wire field, no new schema, and no new grade rule. "
        "Requires --preliminary-table-role; selects its own model_profile/prompt pair "
        "and cannot be added on --resume.",
    )
    parser.add_argument(
        "--preliminary-actor-role",
        action="store_true",
        help="Use R34 actor-role prompt",
    )
    parser.add_argument(
        "--preliminary-sentence-fallback",
        action="store_true",
        help="Opt-in context-free E2E3 fallback when verified sentence context is unavailable.",
    )
    parser.add_argument(
        "--preliminary-sentence-context",
        action="store_true",
        help="Opt-in verified same-block sentence context; requires --preliminary-actor-role.",
    )
    parser.add_argument(
        "--preliminary-p2",
        action="store_true",
        help="Opt-in P2 preliminary prompt; requires --preliminary-table-role.",
    )
    parser.add_argument(
        "--capacity-policy-refresh",
        dest="capacity_refresh",
        action="store_true",
        help="Opt-in: use refreshed 2026-09-25 capacity reservation policy revision "
        "(expires 2026-10-02).",
    )

    parser.add_argument(
        "--extraction-source-ids",
        action="store_true",
        help="Opt-in (R14), NEW-run only in effect (pinned on --resume): send each "
        "source already split into locally minted sentence ids and accept only those "
        "ids back, then restore the span from the original offsets. Citation matching "
        "is not relaxed: it removes the model's chance to retype the quote (observed "
        "real loss of `2023 년` rewritten to `2023년`). Pins its own extraction "
        "prompt/rule hash; a selected sentence is a whole source sentence, so "
        "atomicity stays unreviewed.",
    )
    parser.add_argument(
        "--extraction-table-context",
        action="store_true",
        help="Opt-in (R12): give claim extraction a table cell's own row/column header "
        "context instead of the nearest numeric neighbours. Requires "
        "--extraction-context; pins its own extraction rule/prompt hash.",
    )
    parser.add_argument(
        "--extraction-table-rows",
        action="store_true",
        help="Opt-in literal table/chart row candidates; requires source IDs.",
    )
    parser.add_argument(
        "--extraction-recall-prompt",
        action="store_true",
        help="Opt-in environmental targets, oversight and plan examples; requires source IDs.",
    )
    parser.add_argument(
        "--extraction-atomic",
        action="store_true",
        help="Opt-in extraction-atomic-v2; requires --extraction-source-ids. "
        "Pinned on resume; use a new state for the challenger.",
    )
    parser.add_argument(
        "--extraction-atomic-v3",
        action="store_true",
        help="Opt-in explicit recognition/award atom split; requires --extraction-atomic.",
    )
    parser.add_argument(
        "--extraction-failure-diagnostics",
        action="store_true",
        help="Retain bounded per-source model/schema failure codes; requires source IDs.",
    )
    parser.add_argument(
        "--extraction-linewrap-join",
        action="store_true",
        help="Opt-in selected-linewrap-join-v1: join selected prose continuations only. "
        "Requires --extraction-source-ids, incompatible with --extraction-atomic; new run only.",
    )
    parser.add_argument(
        "--extraction-assertion-prompt",
        action="store_true",
        help="Require the selected source sentence itself to assert a claim. "
        "Requires --extraction-source-ids; new-run opt-in, pinned on --resume.",
    )
    parser.add_argument(
        "--extraction-complete-selection",
        action="store_true",
        help="Review every source sentence for claims; requires --extraction-assertion-prompt. "
        "New-run opt-in, pinned on resume.",
    )
    parser.add_argument(
        "--extraction-content-bounds",
        action="store_true",
        help="Excludes a single terminal period for proven OCR mismatches; requires "
        "--extraction-source-ids.",
    )
    parser.add_argument("--tagging-max-calls", type=int, default=12)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--serve-worker",
        action="store_true",
        help="Explicit paid consent to drive NEW web-queued runs in the same process "
        "(parse/extract/tag via the shared USD20 ledger). Distinct from read-only "
        "--resume; requires --serve. Re-serving stored results alone never needs it.",
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--r108-finals-candidate",
        action="store_true",
        help="Opt-in Sprint5 attempt3 + linewrap join + element consistency v6 + "
        "sentence context + table rows + recall prompt. No atomic mode; "
        "does not authorize model calls.",
    )
    parser.add_argument(
        "--r108-finals-candidate-v2",
        action="store_true",
        help="Opt-in Sprint5 attempt3 + linewrap join + element consistency v6 + "
        "sentence context with E2E3 fallback; excludes table rows, recall, atomic and P1/P2. "
        "Does not authorize model calls.",
    )
    parser.add_argument(
        "--analysis-profile",
        choices=[
            "finals-unattended-v1",
            "finals-unattended-v2",
            "finals-unattended-j3-v1",
            "finals-unattended-j7-v1",
            "finals-unattended-j8-v1",
        ],
    )
    parser.add_argument("--analysis-policy-sha256", help="Explicit known execution policy pin")
    parser.add_argument("--extraction-fragment-guard", action="store_true")
    return parser


def validate_arguments(
    pilot: ModuleType, args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any]:
    """Apply create/resume profiles and reject incompatible explicit options."""
    from proofops.application.analysis_profile import apply_pilot_profile

    args.extraction_j8 = False
    args.extraction_i3_wire = False
    args.extraction_i4_identity = False
    args.extraction_qc_native_figures = False
    args.extraction_k6 = False
    args.extraction_q1 = False
    args.extraction_qt1 = False
    apply_pilot_profile(args)
    try:
        pilot.apply_finals_candidate(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.vision_parse is None:
        args.vision_parse = "auto" if args.parser in ("upstage", "mixed-v1") else "off"
    if args.parser in ("upstage", "mixed-v1") and args.vision_parse == "all":
        parser.error("--vision-parse all requires --parser local")
    if not args.resume:
        if args.llm_provider in ("openrouter", "openai"):
            if args.model is not None:
                parser.error("--model requires --llm-provider upstage")
            args.model = "gpt-6-luna" if args.llm_provider == "openai" else "openai/gpt-6-luna"
        else:
            args.model = args.model or "solar-pro3"
    if args.serve_worker and not args.serve:
        parser.error("--serve-worker requires --serve")
    if args.serve:
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", args.port))
            except OSError:
                parser.error("Port is in use; use the existing review URL or another --port")
    try:
        pilot.parser_output_limit(args.parser_max_output_bytes)
        pilot.parser_memory_limit(args.parser_memory_bytes)
    except ValueError as exc:
        parser.error(str(exc))
    resume_state = args.state.resolve()
    resume_manifest = resume_state / "pilot.json"
    if resume_manifest.exists():
        saved = json.loads(resume_manifest.read_text())
        requested_profile = pilot.finals_candidate_profile(args)
        if requested_profile is not None and saved.get("r108_profile") != requested_profile:
            parser.error(f"cannot add {requested_profile} to an existing run; create a new run")
        if args.parser_memory_bytes is not None and args.parser_memory_bytes != saved.get(
            "parser_memory_bytes", 768 * 1024 * 1024
        ):
            parser.error("existing pilot parser memory limit changed; create a new run")
        for field, default in (
            ("pipeline_profile", None),
            ("analysis_policy_sha256", None),
            ("relation_profile", "source-quotes-v1"),
            ("preliminary_profile", None),
            ("claim_source_profile", None),
            ("display_text_profile", None),
        ):
            requested = getattr(args, field)
            if requested is not None and requested != saved.get(field, default):
                parser.error(f"existing pilot {field} profile changed; create a new run")
    try:
        company_body = pilot.pilot_company_body(
            args.company_name,
            args.company_registration,
            existing=args.resume or resume_manifest.exists(),
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.resume:
        pilot._restore_resume_args(args, parser, resume_state, resume_manifest)
    elif (
        args.pdf is None
        or args.report_year is None
        or args.period_start is None
        or (args.period_end is None)
    ):
        parser.error("--pdf, --report-year, --period-start and --period-end are required")
    if (args.preliminary_profile or args.relation_profile == "decision-gate-v1") and (
        not args.live_tagging or args.llm_provider != "openrouter" or args.position_context_order
    ):
        parser.error(
            "decision profiles require --live-tagging --llm-provider openrouter "
            "and source context order"
        )
    if args.relation_profile is None:
        args.relation_profile = "source-quotes-v1"
    if args.relation_profile != "source-quotes-v1" and not args.live_relations:
        parser.error("--relation-profile requires --live-relations")
    if args.claim_source_profile is not None and not args.verify_claim_spans:
        parser.error("--claim-source-profile requires --verify-claim-spans")
    if args.key_file is None:
        args.key_file = pilot.ROOT / (f".env.{args.llm_provider}.local")
    if args.live_relations and not args.live_tagging:
        parser.error("--live-relations requires --live-tagging")
    if args.element_consistency and not args.live_tagging:
        parser.error("--element-consistency requires --live-tagging")
    if args.compact_element_wire and not args.live_tagging:
        parser.error("--compact-element-wire requires --live-tagging")
    if args.preliminary_sentence_fallback and not args.preliminary_sentence_context:
        parser.error("--preliminary-sentence-fallback requires --preliminary-sentence-context")
    if args.preliminary_sentence_context and (
        not args.preliminary_actor_role
        or args.preliminary_p2
        or args.preliminary_profile
        or args.position_context_order
    ):
        parser.error("--preliminary-sentence-context requires actor role and excludes alternatives")
    if args.preliminary_context and not args.live_tagging:
        parser.error("--preliminary-context requires --live-tagging")
    if args.preliminary_table_context and not args.preliminary_context:
        parser.error("--preliminary-table-context requires --preliminary-context")
    if args.preliminary_table_role and not args.preliminary_table_context:
        parser.error("--preliminary-table-role requires --preliminary-table-context")
    if args.preliminary_goal_role and not args.preliminary_table_role:
        parser.error("--preliminary-goal-role requires --preliminary-table-role")
    if args.preliminary_p2 and (
        not args.preliminary_table_role or args.preliminary_goal_role or args.preliminary_actor_role
    ):
        parser.error("--preliminary-p2 requires only --preliminary-table-role")
    if args.position_context_order and not args.extraction_context:
        parser.error("--position-context-order requires --extraction-context")
    if args.position_context_order and args.live_tagging and not args.preliminary_table_role:
        parser.error("--position-context-order with live tagging requires --preliminary-table-role")
    if args.position_context_order and (args.preliminary_goal_role or args.preliminary_actor_role):
        parser.error("--position-context-order requires only preliminary table role")
    if args.claim_span_render_resolution and not args.verify_claim_spans:
        parser.error("--claim-span-render-resolution requires --verify-claim-spans")
    if args.claim_span_bullet_spacing and not args.claim_span_render_resolution:
        # Refused rather than silently overriding one recovery with the other.
        parser.error("--claim-span-bullet-spacing requires --claim-span-render-resolution")
    if args.claim_span_typography and not args.claim_span_bullet_spacing:
        # Same reason: the typography wrapper wraps the bullet wrapper's own
        # rendered read, so it cannot replace it.
        parser.error("--claim-span-typography requires --claim-span-bullet-spacing")
    if args.extraction_table_context and not args.extraction_context:
        parser.error("--extraction-table-context requires --extraction-context")
    for name in ("table_rows", "recall_prompt"):
        if getattr(args, "extraction_" + name) and not args.extraction_source_ids:
            parser.error(
                "--extraction-" + name.replace("_", "-") + " requires --extraction-source-ids"
            )
    if args.extraction_atomic and (args.extraction_table_rows or args.extraction_recall_prompt):
        parser.error("row/recall profiles cannot mix with --extraction-atomic")
    if args.extraction_atomic and not args.extraction_source_ids:
        parser.error("--extraction-atomic requires --extraction-source-ids")
    if args.extraction_atomic_v3 and not (args.extraction_atomic or args.extraction_table_rows):
        parser.error("--extraction-atomic-v3 requires --extraction-atomic")
    if args.extraction_failure_diagnostics and not args.extraction_source_ids:
        parser.error("--extraction-failure-diagnostics requires --extraction-source-ids")
    if args.extraction_sentence_prefix and (
        not args.extraction_context or not args.extraction_linewrap_join or args.extraction_atomic
    ):
        parser.error(
            "--extraction-sentence-prefix requires --extraction-context and "
            "--extraction-linewrap-join without atomic"
        )
    if args.extraction_linewrap_join and (not args.extraction_source_ids or args.extraction_atomic):
        parser.error(
            "--extraction-linewrap-join requires --extraction-source-ids and no atomic mode"
        )
    if args.extraction_content_bounds and not args.extraction_source_ids:
        parser.error("--extraction-content-bounds requires --extraction-source-ids")
    if args.extraction_assertion_prompt and not args.extraction_source_ids:
        parser.error("--extraction-assertion-prompt requires --extraction-source-ids")
    if args.extraction_complete_selection and not args.extraction_assertion_prompt:
        parser.error("--extraction-complete-selection requires --extraction-assertion-prompt")
    if args.raster_ocr and not args.verify_paragraphs:
        parser.error("--raster-ocr requires --verify-paragraphs")
    if args.native_quote_typography and (not args.verify_paragraphs or args.raster_ocr):
        parser.error("--native-quote-typography requires --verify-paragraphs without --raster-ocr")
    return company_body
