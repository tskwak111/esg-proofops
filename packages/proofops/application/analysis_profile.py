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
V2_POLICY = V2_INITIAL_POLICY | dict(element_wire="track-rulecards-v1")


def policy_for(profile, *, pinned_hash=None):
    if profile == PROFILE:
        choices = (POLICY,)
    elif profile == V2_PROFILE:
        choices = (V2_POLICY, V2_INITIAL_POLICY)
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
