"""One explicitly selected profile; old configurations remain byte-identical."""

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


def apply_pilot_profile(args):
    if (
        getattr(args, "analysis_profile", None) != PROFILE
        and getattr(args, "pipeline_profile", None) != PROFILE
    ):
        return
    if getattr(args, "resume", False):
        return  # persisted pins restored and checked by the pilot
    args.llm_provider = "openai"
    args.model = None
    args.parser = "mixed-v1"
    args.pipeline_profile = PROFILE
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
