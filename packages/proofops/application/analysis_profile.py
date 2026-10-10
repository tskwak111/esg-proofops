"""One explicitly selected profile; old configurations remain byte-identical."""

from proofops.application.tagging.quality import ELEMENT_DEFINITIONS_HASH
from proofops.domain.provenance import canonical_hash

PROFILE = "finals-unattended-v1"
POLICY = dict(
    profile=PROFILE,
    scope="bounded-v1",
    parser="mixed-v1",
    source="claim-source-v3",
    evidence_source="evidence-source-v1",
    parser_failure_policy="partial-v1",
    pipeline="unattended-v1",
    linewrap=True,
    display_workers=4,
    max_http_workers=16,
    replicas=3,
    run_usd="1.0",
    daily_usd="7",
    event_usd="7",
    pipeline_graph="full-parse-only-v1",
)
POLICY_HASH = canonical_hash(POLICY)

V2_PROFILE = "finals-unattended-v2"
V2_INITIAL_POLICY = POLICY | dict(
    profile=V2_PROFILE,
    pipeline_graph="source-attested-before-tagging-v2",
    stage_overlap=False,
    element_definition_profile="qi1-v1",
    element_definitions_sha256=ELEMENT_DEFINITIONS_HASH,
    extraction_fragment_guard="selected-linewrap-fragments-v1",
    grade_display="whole-range-hold-v1",
)
V2_PRE_HF1_POLICY = V2_INITIAL_POLICY | dict(element_wire="track-rulecards-v1")
V2_HF1_POLICY = V2_PRE_HF1_POLICY | dict(
    source="upstage-ocr-page-v6",
    hold_recovery="hf1-v1",
    citation_restore="citation-whitespace-partial-v1",
    grade_display="actual-gap-hold-v2",
)

V2_PB1_INITIAL_POLICY = V2_HF1_POLICY | dict(
    extraction_pb1="pb1-v1",
    table_claims="pb1-v1",
    source="upstage-ocr-page-v7",
    goal_candidate="gap002-pb1-v1",
    occurrence_grouping="quote-occurrences-pb1-v1",
)

V2_PB1_COMPACT_POLICY = V2_PB1_INITIAL_POLICY | dict(preliminary_wire="pb1-compact-v1")
V2_PB1_POLICY = V2_PB1_COMPACT_POLICY | dict(table_context="pb1-table-context-labels-v1")
V2_PB2_INITIAL_POLICY = V2_PB1_POLICY | dict(
    source="upstage-ocr-page-v8",
    citation_restore="citation-table-separators-pb2-v1",
    table_evidence="table-selected-evidence-pb2-v1",
)
V2_PB2_ALL_CLAIMS_POLICY = V2_PB2_INITIAL_POLICY | dict(
    preliminary_fact_fields="preliminary-fact-fields-pb2-v1"
)
V2_POLICY = V2_PB2_ALL_CLAIMS_POLICY | dict(
    preliminary_fact_fields_scope="table_claims",
    table_cell_relations="attested-p1-p2-cells-pb2-v1",
)


def policy_for(profile, *, pinned_hash=None):
    if profile == PROFILE:
        choices = (POLICY,)
    elif profile == V2_PROFILE:
        choices = (
            V2_POLICY,
            V2_PB2_ALL_CLAIMS_POLICY,
            V2_PB2_INITIAL_POLICY,
            V2_PB1_POLICY,
            V2_PB1_COMPACT_POLICY,
            V2_PB1_INITIAL_POLICY,
            V2_HF1_POLICY,
            V2_PRE_HF1_POLICY,
            V2_INITIAL_POLICY,
        )
    else:
        raise ValueError("ANALYSIS_PROFILE_UNKNOWN")
    for policy in choices:
        if pinned_hash is None or canonical_hash(policy) == pinned_hash:
            return policy
    raise ValueError("ANALYSIS_PROFILE_PIN_MISMATCH")


def apply_pilot_profile(args):
    profile = getattr(args, "analysis_profile", None) or getattr(args, "pipeline_profile", None)
    if profile not in (PROFILE, V2_PROFILE):
        return
    if getattr(args, "resume", False):
        return  # persisted pins restored and checked by the pilot
    args.llm_provider = "openai"
    args.model = None
    args.parser = "mixed-v1"
    args.pipeline_profile = profile
    if profile == V2_PROFILE:
        args.extraction_fragment_guard = True
        args.extraction_pb1 = True
        args.extraction_pb1_context_guard = True
        args.extraction_table_rows = True
        args.preliminary_actor_role = True
    # Hosted Linux uses its independently approved OCR reader. Keep that explicit
    # source policy pinned in the run; other callers retain the SV1 native policy.
    if profile == V2_PROFILE and getattr(args, "claim_source_profile", None) in (
        None,
        "claim-source-v3",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v7",
        "upstage-ocr-page-v8",
    ):
        args.claim_source_profile = "upstage-ocr-page-v8"
    if getattr(args, "claim_source_profile", None) not in {
        "upstage-ocr-page-v3",
        "upstage-ocr-page-v4",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v7",
        "upstage-ocr-page-v8",
    }:
        args.claim_source_profile = "claim-source-v3"
    args.verify_claim_spans = True
    args.extraction_linewrap_join = True
    args.vision_parse = "off"
    args.live_tagging = True
    args.live_relations = True
    args.verify_paragraphs = True
    args.verify_merged_tables = True
    args.repair_table_headers = True
    args.display_text_profile = "glyph-joined-display-v1"
    args.relation_profile = "occurrence-v3"
    for flag in (
        "capacity_refresh",
        "extraction_source_ids",
        "extraction_assertion_prompt",
        "extraction_context",
        "extraction_table_context",
        "preliminary_context",
        "preliminary_table_context",
        "preliminary_table_role",
        "compact_element_wire",
        "position_context_order",
    ):
        setattr(args, flag, True)
    if profile == V2_PROFILE:
        args.position_context_order = False
        args.preliminary_goal_role = True
