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
V2_PRE_PA1_POLICY = V2_HF1_POLICY
VERIFIED_READ_POLICY = dict(
    profile="exact-verified-read-v1",
    max_bytes=32 * 1024 * 1024,
    max_entries=4,
    cold_read="single-flight",
    failure_cache=False,
    persistent=False,
)
V2_PRE_PA2_POLICY = V2_HF1_POLICY | dict(verified_read_cache=VERIFIED_READ_POLICY)
VERIFIED_READ_V2_POLICY = VERIFIED_READ_POLICY | dict(
    profile="exact-verified-read-v2",
    fresh_attestation="whole-byte-identical-v6",
    page_preparation="source-order-pipeline-v1",
    provider_fence="atomic-heartbeat-v1",
)
V2_PA2_POLICY = V2_HF1_POLICY | dict(verified_read_cache=VERIFIED_READ_V2_POLICY)
V2_PRE_PA3_POLICY = V2_PA2_POLICY
VERIFIED_READ_V3_POLICY = VERIFIED_READ_V2_POLICY | dict(
    profile="exact-verified-read-v3",
    fresh_parse_attestation="whole-native-v6-and-evidence-ocr-v1",
    cold_evidence_replay="one-full-byte-matched-attestation-v1",
    tag_fence="atomic-heartbeat-v1",
)
# Deployed as ec1-arm64-b523dd2 / e7837e0: HF1 sources with PA3 exact-replay reuse.
V2_PA3_POLICY = V2_HF1_POLICY | dict(verified_read_cache=VERIFIED_READ_V3_POLICY)

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
V2_PB2_POLICY = V2_PB2_ALL_CLAIMS_POLICY | dict(
    preliminary_fact_fields_scope="table_claims",
    table_cell_relations="attested-p1-p2-cells-pb2-v1",
)
# Local PB2+PA2 integration (never deployed); kept for replay of measurement runs.
V2_PRE_PB4_POLICY = V2_PB2_POLICY | dict(verified_read_cache=VERIFIED_READ_V2_POLICY)
V2_PB4_POLICY = V2_PRE_PB4_POLICY | dict(
    source="upstage-ocr-page-v9", table_native_ownership="all-selected-cells-pb4-v1"
)
# Integration: PB4 table extraction/v9 sources with PA3 replay reuse.
V2_PRE_PA7_POLICY = V2_PB4_POLICY | dict(verified_read_cache=VERIFIED_READ_V3_POLICY)
VERIFIED_READ_V4_POLICY = VERIFIED_READ_V3_POLICY | dict(
    profile="exact-verified-read-v4",
    fresh_attestation="whole-byte-identical-v6-and-v9-pb4",
    v9_replay_sha256="ce72e343558611cb48b873dbee7626c9bd277f7b8353a31f0ef93c20e48ea1fd",
    table_ownership="unchanged-approved-row-and-cell-span-tail",
    raster_raw_reads=dict(
        profile="source-runtime-scope-v1",
        max_bytes=8 * 1024 * 1024,
        max_entries=256,
        failure_cache=False,
        persistent=False,
    ),
)
V2_PRE_PA8_POLICY = V2_PRE_PA7_POLICY | dict(verified_read_cache=VERIFIED_READ_V4_POLICY)
V2_PRE_PA4_POLICY = V2_PRE_PA1_POLICY | dict(verified_read_cache=VERIFIED_READ_V3_POLICY)
MODEL_RESPONSE_POLICY = dict(
    profile="exact-model-response-v1",
    temperature=0,
    top_p=1,
    reasoning_effort="none",
    seed="not-authorized-by-model-specific-docs",
    key="tenant-source-analysis-role-replica-wire-schema-v1",
    successful_only=True,
    uncertain_dispatch="retain-pending-no-expiry",
    provenance="original-provider-receipt-and-raw-bytes",
    retention="owning-document-payload",
)
V2_PA4_POLICY = V2_PRE_PA4_POLICY | dict(model_response_policy=MODEL_RESPONSE_POLICY)
V2_PRE_PA9_POLICY = V2_PRE_PA8_POLICY | dict(model_response_policy=MODEL_RESPONSE_POLICY)
V2_POLICY = V2_PRE_PA9_POLICY | dict(
    source="upstage-ocr-page-v10", table_native_ownership="native-grid-pa9-v1"
)


def policy_for(profile, *, pinned_hash=None):
    if profile == PROFILE:
        choices = (POLICY,)
    elif profile == V2_PROFILE:
        choices = (
            V2_POLICY,
            V2_PRE_PA9_POLICY,
            V2_PRE_PA8_POLICY,
            V2_PA4_POLICY,
            V2_PRE_PA4_POLICY,
            V2_PRE_PA7_POLICY,
            V2_PB4_POLICY,
            V2_PRE_PB4_POLICY,
            V2_PB2_POLICY,
            V2_PB2_ALL_CLAIMS_POLICY,
            V2_PB2_INITIAL_POLICY,
            V2_PB1_POLICY,
            V2_PB1_COMPACT_POLICY,
            V2_PB1_INITIAL_POLICY,
            V2_PA3_POLICY,
            V2_PA2_POLICY,
            V2_PRE_PA2_POLICY,
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
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
    ):
        args.claim_source_profile = "upstage-ocr-page-v10"
    if getattr(args, "claim_source_profile", None) not in {
        "upstage-ocr-page-v3",
        "upstage-ocr-page-v4",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v7",
        "upstage-ocr-page-v8",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
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
