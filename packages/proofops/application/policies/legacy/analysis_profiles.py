"""One explicitly selected profile; old configurations remain byte-identical."""

from proofops.adapters.local.claim_source_policies import PAGE_OCR_PROFILES
from proofops.application.fxh_policy import POLICY as FXH_RUNTIME_POLICY
from proofops.application.i27_inventory import POLICY as I27_INVENTORY_POLICY
from proofops.application.ingest.fxg_wire import POLICY as FXG_WIRE_POLICY
from proofops.application.ingest.h1_boundaries import POLICY as H1_BOUNDARY_POLICY
from proofops.application.ingest.i3_wire import POLICY as I3_WIRE_POLICY
from proofops.application.ingest.j7_split import CONTEXT_POLICY
from proofops.application.ingest.j8_cells import POLICY as J8_CELLS_POLICY
from proofops.application.ingest.k1_boundaries import POLICY_HASH as K1_BOUNDARY_HASH
from proofops.application.ingest.k3_table_routing import POLICY as K3_ROUTING_POLICY
from proofops.application.ingest.k5_context import POLICY as K5_CONTEXT_POLICY
from proofops.application.ingest.k6_coverage import FIGURE_POLICY as QC2_FIGURE_POLICY
from proofops.application.ingest.k6_coverage import POLICY as K6_COVERAGE_POLICY
from proofops.application.ingest.page_recovery_policy import CLAIM_LAYOUT_POLICY
from proofops.application.ingest.page_recovery_policy import POLICY as HX6_RECOVERY_POLICY
from proofops.application.ingest.q1_tables import POLICY as Q1_TABLE_POLICY
from proofops.application.ingest.qt1_goal_split import POLICY as QT1_GOAL_SPLIT_POLICY
from proofops.application.ingest.qt1_tables import POLICY as QT1_TABLE_POLICY
from proofops.application.ingest.sentence_prefix import POLICY as PREFIX_POLICY
from proofops.application.input_failures import POLICY as HX5_INPUT_POLICY
from proofops.application.openai_retry import POLICY as T1_RETRY_POLICY
from proofops.application.openai_transport import POLICY as K10_TRANSPORT_POLICY
from proofops.application.provider_resilience import (
    HTTP_DIAGNOSTIC_POLICY,
    RESPONSE_ERROR_DIAGNOSTIC_POLICY,
    SCHEDULER_C24_POLICY,
    SCHEDULER_POLICY,
)
from proofops.application.provider_resilience import POLICY as F1_RESILIENCE_POLICY
from proofops.application.rb1_input_isolation import POLICY as RB1_INPUT_POLICY
from proofops.application.rb3_deadline import POLICY as RB3_DEADLINE_POLICY
from proofops.application.rb3_deadline import POLICY_V2 as RB3_DEADLINE_V2_POLICY
from proofops.application.rb4_memory import POLICY as RB4_MEMORY_POLICY
from proofops.application.rb4_memory import PUBLICATION_POLICY as RB4_PUBLICATION_POLICY
from proofops.application.spg_publication import POLICY as SPG_PUBLICATION_POLICY
from proofops.application.tagging.analysis_scope import confirmation_policy as sc1_policy
from proofops.application.tagging.c3_request_binding import CF2_POLICY as CF2_C3_BINDING
from proofops.application.tagging.c3_request_binding import S5_POLICY as S5_C3_BINDING
from proofops.application.tagging.cf1_inventory import MAJORITY_POLICY as CF1_MAJORITY_POLICY
from proofops.application.tagging.cf1_inventory import POLICY as CF1_INVENTORY_POLICY
from proofops.application.tagging.cf5_context import POLICY as CF5_CONTEXT_POLICY
from proofops.application.tagging.cf5_context import PROFILE as CF5_PROMPT_PROFILE
from proofops.application.tagging.cf6_confirmation import POLICY as CF6_V2_CONFIRMATION_POLICY
from proofops.application.tagging.cf6_confirmation import POLICY_V1 as CF6_CONFIRMATION_POLICY
from proofops.application.tagging.dec24 import (
    DEFINITIONS_HASH,
    INTEGRATED_DEFINITIONS_HASH,
    INTEGRATED_V2_DEFINITIONS_HASH,
    LOCATED_TABLE_CONTEXT_POLICY,
)
from proofops.application.tagging.fact_assembly_c3 import POLICY as C3_POLICY
from proofops.application.tagging.fact_assembly_c3 import REVIEWED_IDENTITY as C3_IDENTITY
from proofops.application.tagging.fact_assembly_c3_v2 import POLICY as C3_V2_POLICY
from proofops.application.tagging.fact_assembly_c3_v2_legacy import POLICY as C3_V2_LEGACY_POLICY
from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE
from proofops.application.tagging.finals_i4 import POLICY as I4_PROMPT_POLICY
from proofops.application.tagging.grade_required_agreement_policy import (
    DEFAULT_POLICY as R18_POLICY,
)
from proofops.application.tagging.i24_inventory import POLICY as I24_INVENTORY_POLICY
from proofops.application.tagging.k1_semantics import DEFINITIONS as K1_DEFINITIONS
from proofops.application.tagging.k1_semantics import POLICY as K1_SEMANTIC_POLICY
from proofops.application.tagging.k2_recovery import POLICY as K2_RECOVERY_POLICY
from proofops.application.tagging.k4_contract import (
    FACILITY_POLICY,
    RESPONSE_POLICY,
    SEMANTIC_POLICY,
    VALUE_POLICY,
)
from proofops.application.tagging.k6_citations import POLICY as K6_CITATION_POLICY
from proofops.application.tagging.k6_citations import RISK_POLICY as K6_RISK_POLICY
from proofops.application.tagging.k7_wire import POLICY as K7_WIRE_POLICY
from proofops.application.tagging.k7_wire import POLICY_K8 as K8_WIRE_POLICY
from proofops.application.tagging.k7_wire import POLICY_K8_V2 as K8_WIRE_V2_POLICY
from proofops.application.tagging.k7_wire import POLICY_K8_V3 as K8_WIRE_V3_POLICY
from proofops.application.tagging.k7_wire import POLICY_K10 as K10_WIRE_POLICY
from proofops.application.tagging.k7_wire import POLICY_V1 as K7_WIRE_V1_POLICY
from proofops.application.tagging.k9_contract import BINDING_POLICY as K9_BINDING_POLICY
from proofops.application.tagging.k9_contract import BINDING_V1_POLICY as K9_BINDING_V1_POLICY
from proofops.application.tagging.k9_contract import BINDING_V2_POLICY as K9_BINDING_V2_POLICY
from proofops.application.tagging.k9_contract import BINDING_V3_POLICY as K9_BINDING_V3_POLICY
from proofops.application.tagging.k9_contract import BINDING_V4_POLICY as K9_BINDING_V4_POLICY
from proofops.application.tagging.k9_contract import PROFILE as K9_PROMPT_PROFILE
from proofops.application.tagging.k9_contract import PROMPT_POLICY as K9_PROMPT_POLICY
from proofops.application.tagging.k10_contract import SEMANTIC_POLICY as K10_SEMANTIC_POLICY
from proofops.application.tagging.k10_contract import SEMANTIC_V2_POLICY as K10_SEMANTIC_V2_POLICY
from proofops.application.tagging.k11_contract import WIRE_POLICY as K11_WIRE_POLICY
from proofops.application.tagging.k11_contract import WIRE_V1_POLICY as K11_WIRE_V1_POLICY
from proofops.application.tagging.q1_contract import PROMPT_POLICY as Q1_PROMPT_POLICY
from proofops.application.tagging.q1_contract import QA2_POLICY
from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_SEMANTIC_POLICY
from proofops.application.tagging.qt1_baseline import POLICY as QT1_BASELINE_POLICY
from proofops.application.tagging.qt1_tuples import POLICY as QT1_TUPLE_POLICY
from proofops.application.tagging.qt2_context import POLICY as QT2_CONTEXT_POLICY
from proofops.application.tagging.quality import ELEMENT_DEFINITIONS_HASH
from proofops.application.tagging.semantic_admission import POLICY as W8_POLICY
from proofops.application.tagging.semantic_admission import POLICY_HASH as W8_POLICY_HASH
from proofops.application.tagging.spt_pipeline import POLICY as SPT_PIPELINE_POLICY
from proofops.application.tagging.tb1_table_bundles import POLICY as TB1_TABLE_POLICY
from proofops.application.tagging.v1_activity_links import POLICY as V1_ACTIVITY_LINK_POLICY
from proofops.application.tagging.v3_dec92 import POLICY as V3_DEC92_POLICY
from proofops.application.tagging.v3_dec92 import PROMPT_POLICY as V3_PROMPT_POLICY
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
# Preserve both the standalone PB6 policy and the deployed dd61b3e policy.
V2_PRE_PB6_POLICY = V2_PRE_PA8_POLICY
V2_PB6_POLICY = V2_PRE_PB6_POLICY | dict(citation_restore="citation-selected-value-pb6-v1")
V2_PRE_PB7_POLICY = V2_PRE_PA8_POLICY | dict(model_response_policy=MODEL_RESPONSE_POLICY)
V2_PB7_POLICY = V2_PRE_PB7_POLICY | dict(citation_restore="citation-selected-value-pb6-v1")
V2_PRE_PA9_POLICY = V2_PRE_PB7_POLICY
V2_PA9_POLICY = V2_PRE_PA9_POLICY | dict(
    source="upstage-ocr-page-v10", table_native_ownership="native-grid-pa9-v1"
)
V2_PRE_W8_POLICY = V2_PB7_POLICY | dict(
    source="upstage-ocr-page-v10", table_native_ownership="native-grid-pa9-v1"
)
V2_W8_POLICY = V2_PRE_W8_POLICY | dict(
    semantic_definition_profile="w8-v1",
    semantic_admission=W8_POLICY,
    semantic_admission_sha256=W8_POLICY_HASH,
)
V2_PRE_D24_POLICY = V2_PRE_W8_POLICY
V2_PRE_W9_POLICY = V2_PRE_W8_POLICY
V2_W9_POLICY = V2_PRE_W9_POLICY | dict(
    table_claims="pb1-w9-v1",
    table_cells="pb1-w9-v1",
    table_figures="independent-reader-only-w9-v1",
)

# W3 is opt-in by its hash. Never reinterpret or change the default v2 pin.
VERIFIED_READ_V5_POLICY = VERIFIED_READ_V4_POLICY | dict(
    profile="exact-verified-read-v5",
    fresh_attestation="whole-byte-identical-v6-v9-v10",
    v10_replay_sha256="d25b4acb5fea06b56278d0de7d5383478d57bb9e4f5a25e888baedb6b8b1a3a1",
    raw_ocr_profiles=["upstage-ocr-page-v6", "upstage-ocr-page-v9", "upstage-ocr-page-v10"],
    raw_ocr_workers=2,
    raw_ocr_omp_threads=1,
)
W3_POLICY = V2_PRE_W8_POLICY | dict(
    execution_profile="w3-speed-v1",
    verified_read_cache=VERIFIED_READ_V5_POLICY,
    max_http_workers=16,
    parse_download_workers=4,
    overlap_gate="full-frozen-graph-required",
    http_admission="per-run-16-half-on-429-no-retry-v1",
    http_max_cooldown_seconds=30,
    http_retry_after="minimum-or-defer-v1",
)


V2_D24_POLICY = V2_PRE_D24_POLICY | dict(
    element_definition_profile="dec24-v1",
    element_definitions_sha256=DEFINITIONS_HASH,
    table_footnotes="table-footnotes-dec24-v1",
    hold_display="estimate-reason-dec24-v1",
    context_binding="conservative-atomic-source-v1",
)

FINALS_I1_INITIAL_POLICY = (
    V2_D24_POLICY
    | {k: v for k, v in V2_W9_POLICY.items() if v != V2_PRE_W9_POLICY.get(k)}
    | {k: v for k, v in V2_W8_POLICY.items() if v != V2_PRE_W8_POLICY.get(k)}
    | {k: v for k, v in W3_POLICY.items() if v != V2_PRE_W8_POLICY.get(k)}
    | dict(
        integration_profile="finals-20261011-v1",
        scope="bounded-v2",
        scope_ranking="W4-v2",
        scope_policy_sha256="542b59b0512b48f5e88b8ef508a64072a3112e2b6ec97bbbcbbadc2ce038f986",
        extraction_sentence_prefix="same-paragraph-sentence-prefix-w7-v1",
        sentence_prefix_policy_sha256=canonical_hash(PREFIX_POLICY),
        element_definition_profile="finals-i1-v1",
        element_definitions_sha256=INTEGRATED_DEFINITIONS_HASH,
    )
)
FINALS_I1_POLICY = FINALS_I1_INITIAL_POLICY | dict(
    element_definition_profile="finals-i1-v2",
    element_definitions_sha256=INTEGRATED_V2_DEFINITIONS_HASH,
)
FINALS_I2_J3_POLICY = FINALS_I1_POLICY | dict(
    integration_profile="finals-20261011-v2",
    selected_span_refinement="j3-explicit-boundaries-v1",
)
# The same-input I2 replay measured 70/75 strict precision (<95%). Keep this
# candidate readable, but exclude J3 from new default/publication runs.
FINALS_I2_POLICY = FINALS_I1_POLICY | dict(integration_profile="finals-20261011-v2")
V2_POLICY = FINALS_I2_POLICY


J3_PROFILE = "finals-unattended-j3-v1"
J3_POLICY = V2_W9_POLICY | dict(
    profile=J3_PROFILE,
    selected_span_refinement="j3-explicit-boundaries-v1",
)

# K1 is explicitly hash-selected until the integration owner adopts it.
K1_POLICY = FINALS_I1_POLICY | dict(
    semantic_definition_profile="k1-v1",
    semantic_admission=K1_SEMANTIC_POLICY,
    semantic_admission_sha256=canonical_hash(K1_SEMANTIC_POLICY),
    element_definition_profile="k1-v1",
    element_definitions_sha256=canonical_hash(K1_DEFINITIONS),
    extraction_k1="table-trailing-label-k1-v1",
    extraction_k1_sha256=K1_BOUNDARY_HASH,
)

# Explicit pin only: historical defaults and stored I1 hashes remain unchanged.
FINALS_K2_POLICY = FINALS_I1_POLICY | dict(
    hold_recovery_policy=K2_RECOVERY_POLICY,
    hold_recovery_policy_sha256=canonical_hash(K2_RECOVERY_POLICY),
    hold_display="cause-specific-k2-v1",
)
# Keep I1 immutable/readable. K3 changes only future table source/routing policy.

K3_POLICY = FINALS_I1_POLICY | dict(
    source="upstage-ocr-page-v11",
    table_native_ownership="native-column-k3-v1",
    table_worker_routing=K3_ROUTING_POLICY,
)


J7_PROFILE = "finals-unattended-j7-v1"
J7_POLICY = J3_POLICY | dict(
    profile=J7_PROFILE,
    selected_span_refinement="j7-independent-clauses-v1",
)


J8_PROFILE = "finals-unattended-j8-v1"

J8_POLICY = J3_POLICY | dict(
    profile=J8_PROFILE,
    table_cells=J8_CELLS_POLICY["profile"],
    cell_candidate_policy_sha256=canonical_hash(J8_CELLS_POLICY),
)

FINALS_I3_POLICY = (
    FINALS_I2_POLICY
    | {k: v for k, v in K1_POLICY.items() if v != FINALS_I1_POLICY.get(k)}
    | {k: v for k, v in FINALS_K2_POLICY.items() if v != FINALS_I1_POLICY.get(k)}
    | {k: v for k, v in K3_POLICY.items() if v != FINALS_I1_POLICY.get(k)}
    | dict(
        integration_profile="finals-20261011-v3",
        extraction_wire="owned-cell-compact-i3-v1",
        extraction_wire_policy_sha256=canonical_hash(I3_WIRE_POLICY),
        selected_span_refinement="j7-independent-clauses-v1",
        table_cells=J8_CELLS_POLICY["profile"],
        cell_candidate_policy_sha256=canonical_hash(J8_CELLS_POLICY),
    )
)
FINALS_H1_POLICY = FINALS_I3_POLICY | dict(
    source="upstage-ocr-page-v12",
    local_resource_policy="selected-pdf-h1-v1",
    table_context_origins="h1-origin-context-v1",
    selected_boundary_recovery="h1-selected-boundaries-v1",
    boundary_recovery_policy_sha256=canonical_hash(H1_BOUNDARY_POLICY),
)
V2_POLICY = FINALS_I3_POLICY

S1_POLICY = FINALS_I3_POLICY | dict(
    parse_replay_cache=dict(
        profile="whole-fresh-table-s1-v1",
        implementation_sha256="b2531a86a7a77efd01418dd357b3e13eb68c01859382e1f08679a1054989b017",
        max_bytes=32 * 1024 * 1024,
        scope="tenant-run-source-graph-runtime-whole-receipt-single-delivery",
        projection="byte-pinned-selected-cell-replay-tail",
        transient_cache=False,
        persistent=False,
    ),
)


FINALS_K4_POLICY = FINALS_I3_POLICY | dict(
    integration_profile="finals-r2-k4-v1",
    sentence_context_policy=CONTEXT_POLICY,
    sentence_context_policy_sha256=canonical_hash(CONTEXT_POLICY),
    tagging_response_policy=RESPONSE_POLICY,
    preliminary_response_policy=RESPONSE_POLICY,
    selected_quantity_policy=VALUE_POLICY,
    table_evidence="table-selected-evidence-k4-v1",
    semantic_admission=SEMANTIC_POLICY,
    semantic_admission_sha256=canonical_hash(SEMANTIC_POLICY),
    facility_dimensions=FACILITY_POLICY["profile"],
    facility_dimensions_policy=FACILITY_POLICY,
    facility_dimensions_policy_sha256=canonical_hash(FACILITY_POLICY),
)

FINALS_I4_POLICY = FINALS_K4_POLICY | dict(
    integration_profile="finals-20261012-v4",
    parse_replay_cache=S1_POLICY["parse_replay_cache"],
    extraction_selection_ids="dispatch-local-selection-i4-v1",
    tagging_prompt_profile=I4_PROMPT_POLICY["profile"],
    tagging_prompt_policy=I4_PROMPT_POLICY,
    tagging_prompt_policy_sha256=canonical_hash(I4_PROMPT_POLICY),
)
V2_POLICY = FINALS_I4_POLICY

# S2 is explicitly pinned. I3 and the coordinator's future I4 default stay intact.
VERIFIED_READ_V6_POLICY = VERIFIED_READ_V5_POLICY | dict(
    profile="exact-verified-read-v6",
    fresh_attestation="whole-byte-identical-v6-v9-v10-v11",
    v11_replay_sha256="481cdc96d6d83af08963c5f91f8142b9ea3db31d658c7b876499284802369128",
    raw_ocr_profiles=[
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
    ],
    cold_claim_replay="offline-v11-two-cpu-raw-read-v1",
)
S2_POLICY = FINALS_I3_POLICY | dict(
    execution_profile="s2-server-v1",
    verified_read_cache=VERIFIED_READ_V6_POLICY,
    tagging_budget=dict(
        profile="claim-count-reservation-s2-v1",
        max_calls=2000,
        calls_per_claim=27,
        priority="verified-quantitative-target-first-v1",
        money_authority="existing-per-call-usd-reservation",
        run_usd="1.0",
    ),
)

# Additive execution policy: v6/v11 receipts and all earlier pins stay immutable.
VERIFIED_READ_V7_POLICY = VERIFIED_READ_V6_POLICY | dict(
    profile="exact-verified-read-v7",
    fresh_attestation="whole-byte-identical-v6-v9-v10-v11-v12",
    v12_replay_sha256="94f0b5376644143739448d75be16a235b56298a01ee98a0807ae0bfd625b462a",
    raw_ocr_profiles=[
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
        "upstage-ocr-page-v12",
    ],
    cold_claim_replay="offline-v12-two-cpu-raw-read-i5-v1",
)
FINALS_I5_INITIAL_POLICY = (
    FINALS_I4_POLICY
    | {k: v for k, v in FINALS_H1_POLICY.items() if v != FINALS_I3_POLICY.get(k)}
    | {k: v for k, v in S2_POLICY.items() if v != FINALS_I3_POLICY.get(k)}
    | dict(integration_profile="finals-20261012-v5", verified_read_cache=VERIFIED_READ_V7_POLICY)
)
FINALS_I5_POLICY = FINALS_I5_INITIAL_POLICY | dict(
    table_failure_profile="i5-grid-unreadable-v1",
)
V2_POLICY = FINALS_I5_POLICY

# Explicit adoption only. Historical I4 runs and the default remain immutable.
FINALS_K5_POLICY = FINALS_I4_POLICY | dict(
    integration_profile="finals-context-k5-v1",
    sentence_context_policy=K5_CONTEXT_POLICY,
    sentence_context_policy_sha256=canonical_hash(K5_CONTEXT_POLICY),
)


FINALS_K6_POLICY = FINALS_I4_POLICY | dict(
    integration_profile="finals-coverage-k6-v1",
    coverage_policy=K6_COVERAGE_POLICY,
    coverage_policy_sha256=canonical_hash(K6_COVERAGE_POLICY),
    citation_restore=K6_CITATION_POLICY["profile"],
    risk_classification_policy=K6_RISK_POLICY,
    risk_classification_policy_sha256=canonical_hash(K6_RISK_POLICY),
    facility_tagging_candidates="native-proof-boundary-candidates-k6-v1",
)

FINALS_I6_POLICY = (
    FINALS_I5_POLICY
    | {k: v for k, v in FINALS_K5_POLICY.items() if v != FINALS_I4_POLICY.get(k)}
    | {k: v for k, v in FINALS_K6_POLICY.items() if v != FINALS_I4_POLICY.get(k)}
    | dict(integration_profile="finals-20261012-v6")
)
V2_POLICY = FINALS_I6_POLICY

# K7 is explicit until its live gate is accepted; every v6 pin remains readable.

FINALS_K7_POLICY = FINALS_I6_POLICY | dict(
    integration_profile="finals-20261012-v6fix-k7",
    tagging_wire_policy=K7_WIRE_POLICY,
    source="upstage-ocr-page-v13",
    table_evidence="table-selected-evidence-k7-v1",
)
FINALS_K7_V1_POLICY = FINALS_K7_POLICY | dict(tagging_wire_policy=K7_WIRE_V1_POLICY)


FINALS_K8_POLICY = FINALS_K7_POLICY | dict(
    integration_profile="finals-20261012-r4-k8",
    tagging_wire_policy=K8_WIRE_POLICY,
    parser_source_recovery="native-continuation-k8-v1",
)


FINALS_K8_V2_POLICY = FINALS_K8_POLICY | dict(
    integration_profile="finals-20261012-r4-k8-v2",
    tagging_wire_policy=K8_WIRE_V2_POLICY,
)


FINALS_K8_V3_POLICY = FINALS_K8_V2_POLICY | dict(
    integration_profile="finals-20261012-r4-k8-v3",
    tagging_wire_policy=K8_WIRE_V3_POLICY,
)

# Explicit pin only. The deployed v5/default and all replay hashes stay intact.
FINALS_T1_POLICY = FINALS_I5_POLICY | dict(
    integration_profile="finals-20261012-t1-403-v1",
    openai_retry_policy=T1_RETRY_POLICY,
    http_admission="per-run-8-structured-overload-403-once-t1-v1",
    max_http_workers=8,
)
FINALS_F1_INITIAL_POLICY = FINALS_T1_POLICY | dict(
    integration_profile="finals-20261012-f1-resilience-v1",
    provider_resilience=F1_RESILIENCE_POLICY,
    http_admission="per-run-8-paced4-denial3-f1-v1",
)
FINALS_F1_TRANSPORT_POLICY = FINALS_F1_INITIAL_POLICY | dict(
    integration_profile="finals-20261012-f1-resilience-v2",
    http_dispatch_guard="physical-attempt-paced4-denial3-f1-v2",
)
FINALS_F1_POLICY = FINALS_F1_TRANSPORT_POLICY | dict(
    integration_profile="finals-20261012-f1-resilience-v3",
    response_uncertainty_policy=RESPONSE_ERROR_DIAGNOSTIC_POLICY,
)

# Adopt the complete K8 source/wire and F1 transport contracts only for new runs.
FINALS_I7_POLICY = (
    FINALS_K8_V3_POLICY
    | {k: v for k, v in FINALS_F1_POLICY.items() if v != FINALS_I5_POLICY.get(k)}
    | dict(
        integration_profile="finals-20261012-v7",
        extract_batch_calls=100,
        max_active_runs=1,
    )
)
V2_POLICY = FINALS_I7_POLICY

# Historical K9 candidate pins remain readable after default adoption.
FINALS_K9_INITIAL_POLICY = FINALS_I7_POLICY | dict(
    integration_profile="finals-20261012-v7fix-k9",
    tagging_prompt_profile=K9_PROMPT_PROFILE,
    tagging_prompt_policy=K9_PROMPT_POLICY,
    tagging_prompt_policy_sha256=canonical_hash(K9_PROMPT_POLICY),
    local_implementation_binding_policy=K9_BINDING_V1_POLICY,
    local_implementation_binding_policy_sha256=canonical_hash(K9_BINDING_V1_POLICY),
)

FINALS_K9_V2_POLICY = FINALS_K9_INITIAL_POLICY | dict(
    integration_profile="finals-20261012-v7fix-k9-v2",
    local_implementation_binding_policy=K9_BINDING_V2_POLICY,
    local_implementation_binding_policy_sha256=canonical_hash(K9_BINDING_V2_POLICY),
)

FINALS_K9_V3_POLICY = FINALS_K9_V2_POLICY | dict(
    integration_profile="finals-20261012-v7fix-k9-v3",
    local_implementation_binding_policy=K9_BINDING_V3_POLICY,
    local_implementation_binding_policy_sha256=canonical_hash(K9_BINDING_V3_POLICY),
)

FINALS_K9_V4_POLICY = FINALS_K9_V3_POLICY | dict(
    integration_profile="finals-20261012-v7fix-k9-v4",
    local_implementation_binding_policy=K9_BINDING_V4_POLICY,
    local_implementation_binding_policy_sha256=canonical_hash(K9_BINDING_V4_POLICY),
)

FINALS_K9_POLICY = FINALS_K9_V4_POLICY | dict(
    integration_profile="finals-20261012-v7fix-k9-v5",
    local_implementation_binding_policy=K9_BINDING_POLICY,
    local_implementation_binding_policy_sha256=canonical_hash(K9_BINDING_POLICY),
)

# Adopt final K9 semantics for new runs; preserve every earlier pin verbatim.
FINALS_I8_POLICY = FINALS_K9_POLICY | dict(integration_profile="finals-20261012-v8")


# S4 is opt-in; the deployed v7 policy and all historical reader bytes stay pinned.
VERIFIED_READ_V8_POLICY = VERIFIED_READ_V7_POLICY | dict(
    profile="exact-verified-read-v8",
    fresh_attestation="whole-byte-identical-v6-v9-v10-v11-v12-v13",
    v13_replay_sha256="4ef2bc4795b8a755bd9e8180dfaf0fe848e355ef2db67d554775ecadc3b1a4d4",
    raw_ocr_profiles=[
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
        "upstage-ocr-page-v12",
        "upstage-ocr-page-v13",
    ],
    cold_claim_replay="offline-v13-two-cpu-raw-read-s4-v1",
)
S4_PUBLICATION_POLICY = dict(
    profile="private-child-byte-pinned-publication-s4-v1",
    transport="inherited-anonymous-fd-no-persistent-cache",
    admission="exact-workspace-tenant-run-fence-pages-reader-runtime-bytes",
    fallback="original-source-replay",
    max_bytes=32 * 1024 * 1024,
)
S4_POLICY = FINALS_I7_POLICY | dict(
    integration_profile="finals-s4-v13cache-v1",
    verified_read_cache=VERIFIED_READ_V8_POLICY,
    publication_handoff=S4_PUBLICATION_POLICY,
)

# Explicit opt-in until real LG + Kakao promotion gates pass. The default and
# every existing source/model/rule policy remain available for historical replay.
FINALS_S5_POLICY = FINALS_I7_POLICY | dict(
    integration_profile="finals-20261012-s5-pacing-v1",
    provider_scheduler=SCHEDULER_POLICY,
    http_dispatch_guard=SCHEDULER_POLICY["profile"],
    http_admission="shared-physical-role-fair-s5-v1",
    max_http_workers=16,
    worker_resources="worker-resources-s5-v1",
)

# Execution-only integration; the v8 source, tagging and domain policies remain fixed.
FINALS_I9_POLICY = (
    FINALS_I8_POLICY
    | {key: S4_POLICY[key] for key in ("verified_read_cache", "publication_handoff")}
    | {
        key: FINALS_S5_POLICY[key]
        for key in (
            "provider_scheduler",
            "http_dispatch_guard",
            "http_admission",
            "max_http_workers",
            "worker_resources",
        )
    }
    | dict(integration_profile="finals-20261012-v9")
)
FINALS_C24_POLICY = FINALS_I9_POLICY | dict(
    integration_profile="finals-20261012-v10",
    max_http_workers=24,
    provider_scheduler=SCHEDULER_C24_POLICY,
    http_dispatch_guard=SCHEDULER_C24_POLICY["profile"],
)

FINALS_Q1_POLICY = FINALS_I9_POLICY | dict(
    integration_profile="finals-q1-structural-v1",
    semantic_admission=Q1_SEMANTIC_POLICY,
    semantic_admission_sha256=canonical_hash(Q1_SEMANTIC_POLICY),
    structural_quality_policy=Q1_SEMANTIC_POLICY,
    structural_quality_policy_sha256=canonical_hash(Q1_SEMANTIC_POLICY),
    activity_table_policy=Q1_TABLE_POLICY,
    activity_table_policy_sha256=canonical_hash(Q1_TABLE_POLICY),
    tagging_prompt_profile=Q1_PROMPT_POLICY["profile"],
    tagging_prompt_policy=Q1_PROMPT_POLICY,
    tagging_prompt_policy_sha256=canonical_hash(Q1_PROMPT_POLICY),
)
FINALS_E05_POLICY = FINALS_I9_POLICY | dict(
    integration_profile="finals-20261013-e05-diagnostics-v1",
    http_diagnostic_policy=HTTP_DIAGNOSTIC_POLICY,
)
FINALS_I10_POLICY = (
    FINALS_C24_POLICY
    | {key: value for key, value in FINALS_Q1_POLICY.items() if value != FINALS_I9_POLICY.get(key)}
    | dict(
        integration_profile="finals-20261013-v11",
        http_diagnostic_policy=HTTP_DIAGNOSTIC_POLICY,
        scope_ranking="E06-scope-v1",
        scope_policy_sha256="e9e826265f104448226f18924eb152f373cc43622f0fbda29ceaa9dda92216d0",
        scope_profile="E06",
        scope_discovery="scope-ocr-fallback-v1",
    )
)

FINALS_K10_POLICY = FINALS_I10_POLICY | dict(
    integration_profile="finals-20261013-k10-v1",
    semantic_admission=K10_SEMANTIC_POLICY,
    semantic_admission_sha256=canonical_hash(K10_SEMANTIC_POLICY),
    tagging_wire_policy=K10_WIRE_POLICY,
    tagging_wire_policy_sha256=canonical_hash(K10_WIRE_POLICY),
    openai_transport_policy=K10_TRANSPORT_POLICY,
    openai_transport_policy_sha256=canonical_hash(K10_TRANSPORT_POLICY),
)
FINALS_K10_V2_POLICY = FINALS_K10_POLICY | dict(
    integration_profile="finals-20261013-k10-v2",
    semantic_admission=K10_SEMANTIC_V2_POLICY,
    semantic_admission_sha256=canonical_hash(K10_SEMANTIC_V2_POLICY),
)
# R9: retain only R8-approved C3 identity; C4 general discovery is disabled by default.
FINALS_I11_POLICY = FINALS_K10_V2_POLICY | dict(
    integration_profile="finals-20261013-v12",
    direct_certification_policy=C3_POLICY,
    direct_certification_policy_sha256=canonical_hash(C3_POLICY),
    general_certification=dict(profile=C4_PROFILE, enabled=False, reason="R9-context-exclusions"),
    residual_review="LG-p24-G3-baseline-year-value-reextraction; keep-unresolved",
)
# Opt-in re-extraction only. Historical defaults/readers and raw votes are immutable.
FINALS_K11_V1_POLICY = FINALS_I11_POLICY | dict(
    integration_profile="finals-20261013-k11-v1",
    tagging_wire_policy=K11_WIRE_V1_POLICY,
    tagging_wire_policy_sha256=canonical_hash(K11_WIRE_V1_POLICY),
    residual_review="G3-requires-fresh-validated-year-and-value; G4-and-grades-remain-independent",
)
FINALS_K11_POLICY = FINALS_K11_V1_POLICY | dict(
    integration_profile="finals-20261013-k11-v2",
    tagging_wire_policy=K11_WIRE_POLICY,
    tagging_wire_policy_sha256=canonical_hash(K11_WIRE_POLICY),
)


FINALS_H4_POLICY = FINALS_I11_POLICY | dict(
    integration_profile="finals-20261013-h4-robustness-v1",
    parser_failure_policy="partial-v2",
    candidate_failure_policy="invalid-table-unknown-v1",
)

FINALS_H5_POLICY = FINALS_H4_POLICY | dict(
    integration_profile="finals-20261013-h5-risk-v1",
    failure_diagnostics="h5-render-limit-and-native-text-eof-v1",
)


FINALS_H6_POLICY = FINALS_K11_POLICY | dict(
    integration_profile="finals-20261013-h6-robustness-v1",
    parser_failure_policy="partial-v3",
    local_resource_policy="selected-pdf-h6-v1",
    source="upstage-ocr-page-v14",
    candidate_failure_policy="invalid-table-unknown-v1",
    failure_diagnostics="h5-render-limit-and-native-text-eof-v1",
)


# I12: promote the retained K11 v2/H6 contract without mutating historical pins.
FINALS_I12_POLICY = FINALS_H6_POLICY | dict(
    integration_profile="finals-20261013-v13",
)


FINALS_H7_POLICY = FINALS_H6_POLICY | dict(
    integration_profile="finals-20261013-h7-original-source-v1",
    source="upstage-ocr-page-v15",
)


# I13: enable H7 for new runs; historical policies remain explicitly selectable.
FINALS_I13_POLICY = FINALS_H7_POLICY | dict(
    integration_profile="finals-20261013-v14",
)
# I15: activate QA2 admission and QC2 candidate discovery only for new runs.
FINALS_I15_POLICY = FINALS_I13_POLICY | dict(
    integration_profile="finals-20261014-v15",
    structural_quality_policy=QA2_POLICY,
    structural_quality_policy_sha256=canonical_hash(QA2_POLICY),
    native_figure_policy=QC2_FIGURE_POLICY,
    native_figure_policy_sha256=canonical_hash(QC2_FIGURE_POLICY),
)
FINALS_HX3_POLICY = FINALS_I13_POLICY | dict(
    integration_profile="finals-20261014-hx3",
    source="upstage-ocr-page-v16",
    result_outcome_projection="admitted-extraction-checkpoint-hx3-v1",
    failure_diagnostics="source-item-holds-and-code-locations-hx3-v1",
)
# I16: keep both historical branches intact and add HX3 to the v15 chain.
FINALS_I16_POLICY = FINALS_I15_POLICY | dict(
    integration_profile="finals-20261014-v16",
    source=FINALS_HX3_POLICY["source"],
    result_outcome_projection=FINALS_HX3_POLICY["result_outcome_projection"],
    failure_diagnostics=FINALS_HX3_POLICY["failure_diagnostics"],
)
V2_POLICY = FINALS_I16_POLICY

VERIFIED_READ_V9_POLICY = VERIFIED_READ_V8_POLICY | dict(
    profile="exact-verified-read-v9",
    fresh_attestation="whole-byte-identical-v17-rg1",
    v17_replay_sha256="5b32b114258b27b36461f130ff42b9aabd15dd0c7335a7829cdca63de4ba9d3d",
    raw_ocr_profiles=[
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
        "upstage-ocr-page-v12",
        "upstage-ocr-page-v13",
        "upstage-ocr-page-v17",
    ],
)
RG1_PUBLICATION_POLICY = S4_PUBLICATION_POLICY | dict(
    profile="private-child-byte-pinned-publication-rg1-v1",
)
FINALS_RG1_POLICY = FINALS_I16_POLICY | dict(
    integration_profile="finals-20261014-rg1",
    source="upstage-ocr-page-v17",
    local_resource_policy="selected-pdf-h6-v2",
    verified_read_cache=VERIFIED_READ_V9_POLICY,
    publication_handoff=RG1_PUBLICATION_POLICY,
)

# Explicit hotfix pin: integration can adopt it without rewriting any v15 run.
FINALS_HX4_POLICY = FINALS_I15_POLICY | dict(
    integration_profile="finals-20261014-hx4-parse-v1",
    parser_failure_policy="partial-v4",
    source="upstage-ocr-page-v16",
    parser_block_failure="page-qualified-occurrence-ids; invalid-subtree-unlocated-unknown",
)

FINALS_HX4_COMPLETE_POLICY = FINALS_HX4_POLICY | dict(
    integration_profile="finals-20261014-hx4-parse-v2",
    source="upstage-ocr-page-v17",
)


FINALS_HX6_POLICY = FINALS_HX4_COMPLETE_POLICY | dict(
    integration_profile="finals-20261014-hx6-upstage-v1",
    parser_failure_policy="partial-v5",
    page_recovery_policy=HX6_RECOVERY_POLICY,
    page_recovery_policy_sha256=canonical_hash(HX6_RECOVERY_POLICY),
)
FINALS_HX6_COMPLETE_POLICY = FINALS_HX6_POLICY | dict(
    integration_profile="finals-20261014-hx6-upstage-v2",
    display_failure_policy=(
        "pdfminer-eof-no-display-deletions; raw-quotes-and-source-gates-retained"
    ),
)
FINALS_HX6_RESILIENT_POLICY = FINALS_HX6_COMPLETE_POLICY | dict(
    integration_profile="finals-20261014-hx6-upstage-v3",
    auxiliary_native_failure="unreadable-no-supplemental-credit-hx6-v1",
)
FINALS_HX5_V1_POLICY = FINALS_I15_POLICY | dict(
    input_failure_policy=HX5_INPUT_POLICY,
    input_failure_policy_sha256=canonical_hash(HX5_INPUT_POLICY),
)
FINALS_HX5_POLICY = FINALS_HX5_V1_POLICY | dict(source="upstage-ocr-page-v16")


# Additive integration: historical names and policy dictionaries stay unchanged.
FINALS_I17_POLICY = (
    FINALS_I16_POLICY
    | {k: v for k, v in FINALS_HX6_RESILIENT_POLICY.items() if v != FINALS_I15_POLICY.get(k)}
    | dict(
        integration_profile="finals-20261014-v17",
        source="upstage-ocr-page-v18",
        input_failure_policy=HX5_INPUT_POLICY,
        input_failure_policy_sha256=canonical_hash(HX5_INPUT_POLICY),
    )
)
VERIFIED_READ_V10_POLICY = VERIFIED_READ_V9_POLICY | dict(
    profile="exact-verified-read-v10",
    fresh_attestation="registered-whole-receipt-and-policy-v1",
)
I18_PUBLICATION_POLICY = S4_PUBLICATION_POLICY | dict(
    profile="private-child-registered-policy-publication-v1",
)
FINALS_I18_POLICY = FINALS_I17_POLICY | dict(
    integration_profile="finals-20261014-v18",
    source="upstage-ocr-page-v19",
    local_resource_policy="selected-pdf-h6-v2",
    verified_read_cache=VERIFIED_READ_V10_POLICY,
    publication_handoff=I18_PUBLICATION_POLICY,
)
FINALS_P3_POLICY = FINALS_I18_POLICY | dict(
    integration_profile="finals-20261014-p3-table-replay-v1",
    source="upstage-ocr-page-v20",
)
FINALS_P2_POLICY = FINALS_I18_POLICY | dict(
    integration_profile="finals-20261014-p2-v1",
    located_table_context=LOCATED_TABLE_CONTEXT_POLICY,
    parser_failure_policy="partial-v6",
    page_recovery_policy=CLAIM_LAYOUT_POLICY,
    page_recovery_policy_sha256=canonical_hash(CLAIM_LAYOUT_POLICY),
)
FINALS_I19_POLICY = FINALS_P2_POLICY | dict(
    integration_profile="finals-20261015-v19",
    source="upstage-ocr-page-v20",
)
FINALS_I20_POLICY = FINALS_I19_POLICY | dict(
    integration_profile="finals-20261015-v20",
    source="upstage-ocr-page-v21",
    scope_ranking="W5-v1",
    scope_policy_sha256="61610ca926232d8cfa00c5a0634a8b042a855df58bb5dbdce894a9b4a1704adf",
    scope_ranking_policy_sha256="2d4e44da6505e873151bc172ae999a2307a1ec6b552c9c5912be049155c4e264",
    extraction_candidate_profile="extraction-atomic-v3",
    extraction_failure_diagnostics=True,
    fact_assembly_profile="grade-relevant-unanimity-v1",
    direct_certification_policy=C3_V2_LEGACY_POLICY,
    direct_certification_policy_sha256=canonical_hash(C3_V2_LEGACY_POLICY),
)
# Retain the first local v20 pin emitted before E06/W5 composition was corrected.
FINALS_I20_INITIAL_POLICY = FINALS_I20_POLICY | dict(
    scope_policy_sha256=FINALS_I19_POLICY["scope_policy_sha256"]
)
FINALS_I20_PRE_FXB_POLICY = FINALS_I20_POLICY
# Preserve FXB standalone receipts without reinterpreting historical v20/v21.
FINALS_FXB_POLICY = FINALS_I20_POLICY | dict(
    fact_assembly_profile="grade-relevant-unanimity-v2",
    direct_certification_policy=C3_V2_POLICY,
    direct_certification_policy_sha256=canonical_hash(C3_V2_POLICY),
)
FINALS_I20_PRE_FXC_POLICY = FINALS_FXB_POLICY
FINALS_FXC_POLICY = FINALS_FXB_POLICY | dict(
    fact_assembly_profile="grade-relevant-unanimity-v3",
)
V2_POLICY = FINALS_I20_POLICY

VERIFIED_READ_V11_POLICY = VERIFIED_READ_V10_POLICY | dict(
    profile="exact-verified-read-v11",
    cold_parse_replay="one-whole-registered-v19-i17-recomputation-s2-v1",
    terminal_batch_replay="stop-after-committed-empty-pending-v1",
    max_entries=8,
    table_replay_sha256="b7c45f03899c893c1e560fd69929de8284ffd6407a524fa7994f4e298eb205d3",
    policy_snapshot_sha256="988b4ea0537bf53665b2ed7c94ab67f5d0ee225e19e86dc259b7f594859054fb",
)
FINALS_S2_SPEED_POLICY = FINALS_P2_POLICY | dict(
    integration_profile="finals-20261015-s2-speed-v1",
    verified_read_cache=VERIFIED_READ_V11_POLICY,
)


VERIFIED_READ_V12_POLICY = VERIFIED_READ_V11_POLICY | dict(
    profile="exact-verified-read-v12",
    cold_parse_replay="one-whole-registered-v20-i17-recomputation-i21-v1",
    table_replay_sha256="3165cc56a0f9129e1a580d91a23728b63ffa508ec83076f15053c923388ff3a6",
    policy_snapshot_sha256="54970a389b72ae448a1423ea0b37a2c9a26e8b507fbd7a341ccf8e45e96c7382",
)
FINALS_I21_POLICY = FINALS_I20_POLICY | dict(
    integration_profile="finals-20261015-v21",
    verified_read_cache=VERIFIED_READ_V12_POLICY,
)
FINALS_I22_POLICY = FINALS_I21_POLICY | dict(
    integration_profile="finals-20261015-v22",
    fact_assembly_profile="grade-relevant-unanimity-v2",
    direct_certification_policy=C3_V2_POLICY,
    direct_certification_policy_sha256=canonical_hash(C3_V2_POLICY),
)
FINALS_D2_POLICY = FINALS_P3_POLICY | dict(
    integration_profile="finals-20261015-d2-residual-v1",
    source="upstage-ocr-page-v21",
)
FINALS_I23_POLICY = FINALS_I22_POLICY | dict(
    integration_profile="finals-20261015-v23",
    fact_assembly_profile="grade-relevant-unanimity-v3",
)
FXE_POLICY = FINALS_I23_POLICY | dict(
    integration_profile="fxe_finals-20261015-v1",
    source="fxe_upstage-ocr-page-v21",
)
FXF_POLICY = FXE_POLICY | dict(
    integration_profile="fxf_finals-20261015-v1",
    source="fxf_upstage-ocr-page-v21",
)
# Explicit QT1 opt-in; the default and all historical policy hashes stay frozen.

QT1_POLICY = FINALS_I23_POLICY | dict(
    integration_profile="finals-20261015-qt1-v1",
    qt1_table_recovery_policy=QT1_TABLE_POLICY,
)

QT2_ELEMENTS_POLICY = FINALS_I23_POLICY | dict(
    integration_profile="qt2-finals-20261015-v1",
    qt2_contextual_elements_policy=QT2_CONTEXT_POLICY,
    qt2_contextual_elements_policy_sha256=canonical_hash(QT2_CONTEXT_POLICY),
)
V2_POLICY = FINALS_I23_POLICY

# SC1 is opt-in by exact hash; preserve the default and every historical entry.

sc1_inventory_policies = tuple(
    FINALS_I23_POLICY
    | dict(
        integration_profile=f"sc1_inventory_scope_{votes}of3_v1",
        sc1_scope_confirmation=sc1_policy(votes),
    )
    for votes in (3, 2, 1)
)
S3_VERIFIED_READ_V13_POLICY = VERIFIED_READ_V12_POLICY | dict(
    profile="s3_exact-verified-read-v13",
    cold_parse_replay="one-whole-registered-v21-i17-recomputation-s3-v1",
    table_replay_sha256="ed8e027626498f1ae4902d233143585cd245ccc0ee59b656d33be929706cff5f",
)

# Explicit opt-in: source readers, model wires and all three replicas stay v23.
S3_SPEED_POLICY = FINALS_I23_POLICY | dict(
    integration_profile="s3_finals-20261015-speed-v1",
    parser_failure_policy="s3_partial-v7",
    verified_read_cache=S3_VERIFIED_READ_V13_POLICY,
)


# I24 alone selects these reviewed opt-ins for new runs; historical pins remain registered.


FINALS_I24_POLICY = FINALS_I23_POLICY | dict(
    integration_profile="finals-20261015-v24",
    source="i24_claim_source_v1",
    fxg_extraction_wire_policy=FXG_WIRE_POLICY,
    fxg_extraction_wire_policy_sha256=canonical_hash(FXG_WIRE_POLICY),
    qt1_table_recovery_policy=QT1_TABLE_POLICY,
    qt2_contextual_elements_policy=QT2_CONTEXT_POLICY,
    qt2_contextual_elements_policy_sha256=canonical_hash(QT2_CONTEXT_POLICY),
    sc1_scope_confirmation=sc1_policy(3),
    sc1_inventory_transport=I24_INVENTORY_POLICY,
    grade_required_agreement_policy=R18_POLICY.to_dict(),
    grade_required_agreement_policy_sha256=R18_POLICY.sha256,
    parser_failure_policy=S3_SPEED_POLICY["parser_failure_policy"],
    verified_read_cache=S3_VERIFIED_READ_V13_POLICY,
)
V2_POLICY = FINALS_I24_POLICY


# FXG is opt-in: the public default and all earlier policy dictionaries stay fixed.

FXG_POLICY = FINALS_I23_POLICY | dict(
    integration_profile="fxg_extraction_receipt_v1",
    source="fxg_claim_source_v1",
    fxg_extraction_wire_policy=FXG_WIRE_POLICY,
    fxg_extraction_wire_policy_sha256=canonical_hash(FXG_WIRE_POLICY),
)

# R19-T01/T07 + DEC-93 AP-06: explicit opt-in; v24 remains the default.

V1_ACTIVITY_POLICY = FINALS_I24_POLICY | dict(
    integration_profile="v1_activity_links_r19_ap06_v1",
    v1_activity_links=V1_ACTIVITY_LINK_POLICY,
    v1_activity_links_sha256=canonical_hash(V1_ACTIVITY_LINK_POLICY),
)

# V2/R19-T02,T05: additive opt-in; I25 chooses whether to compose/activate it.
QT1_V25_POLICY = FINALS_I24_POLICY | dict(
    integration_profile="qt1_v25_table_baseline_v1",
    qt1_tuple_policy=QT1_TUPLE_POLICY,
    qt1_baseline_policy=QT1_BASELINE_POLICY,
    qt1_goal_split_policy=QT1_GOAL_SPLIT_POLICY,
)


# V3 is an exact-hash opt-in; the public v24 default and old entries stay frozen.

V3_POLICY = FINALS_I24_POLICY | dict(
    integration_profile="v3_finals_dec92_v1",
    v3_dec92_policy=V3_DEC92_POLICY,
    v3_dec92_policy_sha256=canonical_hash(V3_DEC92_POLICY),
    tagging_prompt_profile=V3_PROMPT_POLICY["profile"],
    tagging_prompt_policy=V3_PROMPT_POLICY,
    tagging_prompt_policy_sha256=canonical_hash(V3_PROMPT_POLICY),
    hold_display="v3-dec92-v1",
)


# I25 composes reviewed deltas; every historical and standalone pin stays readable.
FINALS_I25_POLICY = (
    FINALS_I24_POLICY
    | {k: v for k, v in V1_ACTIVITY_POLICY.items() if v != FINALS_I24_POLICY.get(k)}
    | {k: v for k, v in QT1_V25_POLICY.items() if v != FINALS_I24_POLICY.get(k)}
    | {k: v for k, v in V3_POLICY.items() if v != FINALS_I24_POLICY.get(k)}
    | dict(integration_profile="finals-20261015-v25")
)
V2_POLICY = FINALS_I25_POLICY

# Explicit pin only: never changes the public/default v25 profile.
OPS2_POLICY = FINALS_I25_POLICY | dict(
    integration_profile="ops2_finals-20261016-v1",
    ops2_provider_fallback=dict(
        profile="ops2_openrouter_fallback_v1",
        primary="gpt-6-luna",
        fallback="openai/gpt-6-luna",
        consecutive_http_failures=3,
        triggers=["billing_not_active", "http_429_403_k3", "network_failure"],
        uncertain_costs="retain",
        replicas="three_independent_current_responses",
    ),
    ops2_page_render="ops2_fit_page_v1",
)


FXH_POLICY = FINALS_I25_POLICY | dict(
    integration_profile="fxh_finals_fresh_v1",
    source="fxh_claim_source_v1",
    fxh_runtime=FXH_RUNTIME_POLICY,
)

# I26 activates only the reviewed runtime deltas. Standalone and historical pins
# remain unchanged; chart recovery remains a separate evaluation tool.
FINALS_I26_POLICY = FXH_POLICY | dict(
    integration_profile="finals-20261016-v26",
    ops2_provider_fallback=OPS2_POLICY["ops2_provider_fallback"],
    ops2_page_render=OPS2_POLICY["ops2_page_render"],
)
V2_POLICY = FINALS_I26_POLICY


# S5 is explicit-hash only. V26 and every earlier entry stay byte-identical.
S5_LIVE_POLICY = FINALS_I26_POLICY | dict(
    integration_profile="s5_finals_live_speed_v1",
    source="s5_claim_source_v1",
    extract_batch_calls=256,
    s5_inventory_execution="s5_bounded_parallel_chunks_v1",
    s5_usage_accounting="s5_final_reporting_snapshot_v1",
    s5_c3_response_binding=S5_C3_BINDING,
)

# RB3 is selectable only by a new explicit pin; the v25 default stays frozen.
RB3_POLICY = FXH_POLICY | dict(
    integration_profile="rb3_deadline_v1",
    rb3_deadline=RB3_DEADLINE_POLICY,
    source="rb3_claim_source_v1",
)


# RB1 remains an explicit new-run pin; I26 can compose these two fields onto v26.

RB1_POLICY = FXH_POLICY | dict(
    integration_profile="rb1_finals_table_isolation_v1",
    rb1_input_isolation=RB1_INPUT_POLICY,
    rb1_input_isolation_sha256=canonical_hash(RB1_INPUT_POLICY),
)


# V27 uses the S5 source reader once; RB3 contributes admission only. Historical
# source modules remain byte-pinned for existing standalone receipts.
FINALS_I27_POLICY = S5_LIVE_POLICY | dict(
    integration_profile="finals-20261016-v27",
    rb3_deadline=RB3_DEADLINE_POLICY,
    rb1_input_isolation=RB1_INPUT_POLICY,
    rb1_input_isolation_sha256=canonical_hash(RB1_INPUT_POLICY),
    i27_sc1_optional_transient=I27_INVENTORY_POLICY,
)
V2_POLICY = FINALS_I27_POLICY


# RB2 is additive. I26 may compose these two selectors into its new policy hash.
RB2_POLICY = FXH_POLICY | dict(
    integration_profile="rb2_parser_limit_v1",
    parser_output_policy="rb2-output-v1",
    reporting_period_policy="rb2-native-period-v1",
)

# Keep the pre-addendum I27 pin readable for its already-created receipts.
FINALS_I27_PRE_RB2_POLICY = FINALS_I27_POLICY
FINALS_I27_POLICY = FINALS_I27_PRE_RB2_POLICY | dict(
    parser_output_policy=RB2_POLICY["parser_output_policy"],
    reporting_period_policy=RB2_POLICY["reporting_period_policy"],
)
V2_POLICY = FINALS_I27_POLICY

# CF2 is an explicit new-run pin. I28 may compose its selector; defaults and
# every earlier policy object remain unchanged for historical replay.
CF2_C3_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="cf2_c3_v1",
    cf2_c3_response_binding=CF2_C3_BINDING,
)


RB4_POLICY = RB3_POLICY | dict(
    integration_profile="rb4_memory_v1",
    rb1_input_isolation=RB1_INPUT_POLICY,
    rb1_input_isolation_sha256=canonical_hash(RB1_INPUT_POLICY),
    rb4_memory=RB4_MEMORY_POLICY,
)

RB4_STREAM_POLICY = RB4_POLICY | dict(
    integration_profile="rb4_memory_stream_v2",
    rb4_publication_digest=RB4_PUBLICATION_POLICY,
)


# I28 activates only RB4's memory deltas on the complete v27 composition.
# Preserve v27 and both standalone RB4 pins for immutable receipt replay.
FINALS_I28_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="finals-20261016-v28",
    rb4_memory=RB4_STREAM_POLICY["rb4_memory"],
    rb4_publication_digest=RB4_STREAM_POLICY["rb4_publication_digest"],
)
V2_POLICY = FINALS_I28_POLICY


# CF4 is explicit-hash only; historical/default v27 remains unchanged.
CF4_SOURCE_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="cf4_source_recovery_v1",
    source="cf4_claim_source_v1",
)


# CF5 is a separately pinned trial; the public V2 default remains v27.

CF5_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="cf5_finals_complete_context_v1",
    tagging_prompt_profile=CF5_PROMPT_PROFILE,
    tagging_prompt_policy=CF5_CONTEXT_POLICY,
    tagging_prompt_policy_sha256=canonical_hash(CF5_CONTEXT_POLICY),
    cf5_context_policy=CF5_CONTEXT_POLICY,
    cf5_context_policy_sha256=canonical_hash(CF5_CONTEXT_POLICY),
)


# CF1 is selectable only by exact hash; v27 default and historical pins stay fixed.
CF1_3OF3_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="cf1_finals_inventory_quotes_v1",
    cf1_inventory=CF1_INVENTORY_POLICY,
)

CF1_POLICY = CF1_3OF3_POLICY | dict(
    integration_profile="cf1_finals_inventory_dec125_v1",
    cf1_inventory=CF1_MAJORITY_POLICY,
)


# CF6 is append-only and must be explicitly pinned. I28/CF1 may compose these
# fields onto their new finals policy; V2_POLICY and old hash entries stay intact.
CF6_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="cf6_finals_default_candidate_dec127_v1",
    cf6_confirmation=CF6_CONFIRMATION_POLICY,
)
CF6_V2_POLICY = FINALS_I27_POLICY | dict(
    integration_profile="cf6_finals_default_candidate_dec127_v2",
    cf6_confirmation=CF6_V2_CONFIRMATION_POLICY,
)


# I29 activates the authorized DEC-125/127 composition on v28. Keep every
# constituent policy unchanged so saved responses retain their original reader.
FINALS_I29_INITIAL_POLICY = FINALS_I28_POLICY | dict(
    integration_profile="finals-20261016-v29",
    source=CF4_SOURCE_POLICY["source"],
    cf2_c3_response_binding=CF2_C3_POLICY["cf2_c3_response_binding"],
    cf1_inventory=CF1_POLICY["cf1_inventory"],
    cf6_confirmation=CF6_POLICY["cf6_confirmation"],
    tagging_prompt_profile=CF5_POLICY["tagging_prompt_profile"],
    tagging_prompt_policy=CF5_POLICY["tagging_prompt_policy"],
    tagging_prompt_policy_sha256=CF5_POLICY["tagging_prompt_policy_sha256"],
    cf5_context_policy=CF5_POLICY["cf5_context_policy"],
    cf5_context_policy_sha256=CF5_POLICY["cf5_context_policy_sha256"],
)
FINALS_I29_POLICY = FINALS_I29_INITIAL_POLICY | dict(
    cf6_confirmation=CF6_V2_POLICY["cf6_confirmation"],
)
# HF2 changes only deadline admission. Historical v29 remains exactly pinned.
FINALS_I29B_POLICY = FINALS_I29_POLICY | dict(
    integration_profile="finals-20261016-v29b",
    rb3_deadline=RB3_DEADLINE_V2_POLICY,
)
V2_POLICY = FINALS_I29B_POLICY

# SPT is explicit-hash only. The coordinator can compose spt_claim_pipeline onto
# its next candidate; defaults, model/source pins and HTTP limits stay unchanged.

SPT_POLICY = FINALS_I29B_POLICY | dict(
    integration_profile="spt_claim_pipeline_v1",
    spt_claim_pipeline=SPT_PIPELINE_POLICY,
)

# SPE is opt-in; integration may compose this source selector onto its new pin.
SPE_POLICY = FINALS_I29B_POLICY | dict(
    integration_profile="finals-20261016-spe-v1",
    source="spe_claim_source_v1",
)

# SPP is a parser-only opt-in candidate. Integration may compose this selector
# onto the finals candidate; old policies and the hosted default stay unchanged.
SPP_POLICY = FINALS_I29B_POLICY | dict(
    integration_profile="spp_finals_parse_v1",
    parser_execution_policy="spp-parse-v1",
)

# SPG is a new opt-in hash. The coordinator may compose this execution field
# into a later finals candidate; no existing publication/default pin changes.

SPG_POLICY = FINALS_I29B_POLICY | dict(
    integration_profile="spg_publication_v1",
    spg_publication=SPG_PUBLICATION_POLICY,
)

# I30 activates only the four reviewed execution fields. Keep the individual
# candidates and v29b intact for saved receipts and explicit rollback pins.
FINALS_I30_POLICY = FINALS_I29B_POLICY | dict(
    integration_profile="finals-20261017-v29c",
    spt_claim_pipeline=SPT_POLICY["spt_claim_pipeline"],
    source=SPE_POLICY["source"],
    parser_execution_policy=SPP_POLICY["parser_execution_policy"],
    spg_publication=SPG_POLICY["spg_publication"],
)
V2_POLICY = FINALS_I30_POLICY

# TB1 remains opt-in; historical policies and the public v29b default are immutable.

TB1_POLICY = FINALS_I29B_POLICY | dict(
    integration_profile="tb1_finals_verified_tables_v1",
    source="tb1_claim_source_v1",
    tb1_table_policy=TB1_TABLE_POLICY,
    tb1_table_policy_sha256=canonical_hash(TB1_TABLE_POLICY),
)

__all__ = [
    "C3_IDENTITY",
    "C3_POLICY",
    "C3_V2_LEGACY_POLICY",
    "C3_V2_POLICY",
    "C4_PROFILE",
    "CF1_3OF3_POLICY",
    "CF1_INVENTORY_POLICY",
    "CF1_MAJORITY_POLICY",
    "CF1_POLICY",
    "CF2_C3_BINDING",
    "CF2_C3_POLICY",
    "CF4_SOURCE_POLICY",
    "CF5_CONTEXT_POLICY",
    "CF5_POLICY",
    "CF5_PROMPT_PROFILE",
    "CF6_CONFIRMATION_POLICY",
    "CF6_POLICY",
    "CF6_V2_CONFIRMATION_POLICY",
    "CF6_V2_POLICY",
    "CLAIM_LAYOUT_POLICY",
    "CONTEXT_POLICY",
    "DEFINITIONS_HASH",
    "ELEMENT_DEFINITIONS_HASH",
    "F1_RESILIENCE_POLICY",
    "FACILITY_POLICY",
    "FINALS_C24_POLICY",
    "FINALS_D2_POLICY",
    "FINALS_E05_POLICY",
    "FINALS_F1_INITIAL_POLICY",
    "FINALS_F1_POLICY",
    "FINALS_F1_TRANSPORT_POLICY",
    "FINALS_FXB_POLICY",
    "FINALS_FXC_POLICY",
    "FINALS_H1_POLICY",
    "FINALS_H4_POLICY",
    "FINALS_H5_POLICY",
    "FINALS_H6_POLICY",
    "FINALS_H7_POLICY",
    "FINALS_HX3_POLICY",
    "FINALS_HX4_COMPLETE_POLICY",
    "FINALS_HX4_POLICY",
    "FINALS_HX5_POLICY",
    "FINALS_HX5_V1_POLICY",
    "FINALS_HX6_COMPLETE_POLICY",
    "FINALS_HX6_POLICY",
    "FINALS_HX6_RESILIENT_POLICY",
    "FINALS_I10_POLICY",
    "FINALS_I11_POLICY",
    "FINALS_I12_POLICY",
    "FINALS_I13_POLICY",
    "FINALS_I15_POLICY",
    "FINALS_I16_POLICY",
    "FINALS_I17_POLICY",
    "FINALS_I18_POLICY",
    "FINALS_I19_POLICY",
    "FINALS_I1_INITIAL_POLICY",
    "FINALS_I1_POLICY",
    "FINALS_I20_INITIAL_POLICY",
    "FINALS_I20_POLICY",
    "FINALS_I20_PRE_FXB_POLICY",
    "FINALS_I20_PRE_FXC_POLICY",
    "FINALS_I21_POLICY",
    "FINALS_I22_POLICY",
    "FINALS_I23_POLICY",
    "FINALS_I24_POLICY",
    "FINALS_I25_POLICY",
    "FINALS_I26_POLICY",
    "FINALS_I27_POLICY",
    "FINALS_I27_PRE_RB2_POLICY",
    "FINALS_I28_POLICY",
    "FINALS_I29B_POLICY",
    "FINALS_I29_INITIAL_POLICY",
    "FINALS_I29_POLICY",
    "FINALS_I2_J3_POLICY",
    "FINALS_I2_POLICY",
    "FINALS_I30_POLICY",
    "FINALS_I3_POLICY",
    "FINALS_I4_POLICY",
    "FINALS_I5_INITIAL_POLICY",
    "FINALS_I5_POLICY",
    "FINALS_I6_POLICY",
    "FINALS_I7_POLICY",
    "FINALS_I8_POLICY",
    "FINALS_I9_POLICY",
    "FINALS_K10_POLICY",
    "FINALS_K10_V2_POLICY",
    "FINALS_K11_POLICY",
    "FINALS_K11_V1_POLICY",
    "FINALS_K2_POLICY",
    "FINALS_K4_POLICY",
    "FINALS_K5_POLICY",
    "FINALS_K6_POLICY",
    "FINALS_K7_POLICY",
    "FINALS_K7_V1_POLICY",
    "FINALS_K8_POLICY",
    "FINALS_K8_V2_POLICY",
    "FINALS_K8_V3_POLICY",
    "FINALS_K9_INITIAL_POLICY",
    "FINALS_K9_POLICY",
    "FINALS_K9_V2_POLICY",
    "FINALS_K9_V3_POLICY",
    "FINALS_K9_V4_POLICY",
    "FINALS_P2_POLICY",
    "FINALS_P3_POLICY",
    "FINALS_Q1_POLICY",
    "FINALS_RG1_POLICY",
    "FINALS_S2_SPEED_POLICY",
    "FINALS_S5_POLICY",
    "FINALS_T1_POLICY",
    "FXE_POLICY",
    "FXF_POLICY",
    "FXG_POLICY",
    "FXG_WIRE_POLICY",
    "FXH_POLICY",
    "FXH_RUNTIME_POLICY",
    "H1_BOUNDARY_POLICY",
    "HTTP_DIAGNOSTIC_POLICY",
    "HX5_INPUT_POLICY",
    "HX6_RECOVERY_POLICY",
    "I18_PUBLICATION_POLICY",
    "I24_INVENTORY_POLICY",
    "I27_INVENTORY_POLICY",
    "I3_WIRE_POLICY",
    "I4_PROMPT_POLICY",
    "INTEGRATED_DEFINITIONS_HASH",
    "INTEGRATED_V2_DEFINITIONS_HASH",
    "J3_POLICY",
    "J3_PROFILE",
    "J7_POLICY",
    "J7_PROFILE",
    "J8_CELLS_POLICY",
    "J8_POLICY",
    "J8_PROFILE",
    "K10_SEMANTIC_POLICY",
    "K10_SEMANTIC_V2_POLICY",
    "K10_TRANSPORT_POLICY",
    "K10_WIRE_POLICY",
    "K11_WIRE_POLICY",
    "K11_WIRE_V1_POLICY",
    "K1_BOUNDARY_HASH",
    "K1_DEFINITIONS",
    "K1_POLICY",
    "K1_SEMANTIC_POLICY",
    "K2_RECOVERY_POLICY",
    "K3_POLICY",
    "K3_ROUTING_POLICY",
    "K5_CONTEXT_POLICY",
    "K6_CITATION_POLICY",
    "K6_COVERAGE_POLICY",
    "K6_RISK_POLICY",
    "K7_WIRE_POLICY",
    "K7_WIRE_V1_POLICY",
    "K8_WIRE_POLICY",
    "K8_WIRE_V2_POLICY",
    "K8_WIRE_V3_POLICY",
    "K9_BINDING_POLICY",
    "K9_BINDING_V1_POLICY",
    "K9_BINDING_V2_POLICY",
    "K9_BINDING_V3_POLICY",
    "K9_BINDING_V4_POLICY",
    "K9_PROMPT_POLICY",
    "K9_PROMPT_PROFILE",
    "LOCATED_TABLE_CONTEXT_POLICY",
    "MODEL_RESPONSE_POLICY",
    "OPS2_POLICY",
    "PAGE_OCR_PROFILES",
    "POLICY",
    "POLICY_HASH",
    "PREFIX_POLICY",
    "PROFILE",
    "Q1_PROMPT_POLICY",
    "Q1_SEMANTIC_POLICY",
    "Q1_TABLE_POLICY",
    "QA2_POLICY",
    "QC2_FIGURE_POLICY",
    "QT1_BASELINE_POLICY",
    "QT1_GOAL_SPLIT_POLICY",
    "QT1_POLICY",
    "QT1_TABLE_POLICY",
    "QT1_TUPLE_POLICY",
    "QT1_V25_POLICY",
    "QT2_CONTEXT_POLICY",
    "QT2_ELEMENTS_POLICY",
    "R18_POLICY",
    "RB1_INPUT_POLICY",
    "RB1_POLICY",
    "RB2_POLICY",
    "RB3_DEADLINE_POLICY",
    "RB3_DEADLINE_V2_POLICY",
    "RB3_POLICY",
    "RB4_MEMORY_POLICY",
    "RB4_POLICY",
    "RB4_PUBLICATION_POLICY",
    "RB4_STREAM_POLICY",
    "RESPONSE_ERROR_DIAGNOSTIC_POLICY",
    "RESPONSE_POLICY",
    "RG1_PUBLICATION_POLICY",
    "S1_POLICY",
    "S2_POLICY",
    "S3_SPEED_POLICY",
    "S3_VERIFIED_READ_V13_POLICY",
    "S4_POLICY",
    "S4_PUBLICATION_POLICY",
    "S5_C3_BINDING",
    "S5_LIVE_POLICY",
    "SCHEDULER_C24_POLICY",
    "SCHEDULER_POLICY",
    "SEMANTIC_POLICY",
    "SPE_POLICY",
    "SPG_POLICY",
    "SPG_PUBLICATION_POLICY",
    "SPP_POLICY",
    "SPT_PIPELINE_POLICY",
    "SPT_POLICY",
    "T1_RETRY_POLICY",
    "TB1_POLICY",
    "TB1_TABLE_POLICY",
    "V1_ACTIVITY_LINK_POLICY",
    "V1_ACTIVITY_POLICY",
    "V2_D24_POLICY",
    "V2_HF1_POLICY",
    "V2_INITIAL_POLICY",
    "V2_PA2_POLICY",
    "V2_PA3_POLICY",
    "V2_PA4_POLICY",
    "V2_PA9_POLICY",
    "V2_PB1_COMPACT_POLICY",
    "V2_PB1_INITIAL_POLICY",
    "V2_PB1_POLICY",
    "V2_PB2_ALL_CLAIMS_POLICY",
    "V2_PB2_INITIAL_POLICY",
    "V2_PB2_POLICY",
    "V2_PB4_POLICY",
    "V2_PB6_POLICY",
    "V2_PB7_POLICY",
    "V2_POLICY",
    "V2_PRE_D24_POLICY",
    "V2_PRE_HF1_POLICY",
    "V2_PRE_PA1_POLICY",
    "V2_PRE_PA2_POLICY",
    "V2_PRE_PA3_POLICY",
    "V2_PRE_PA4_POLICY",
    "V2_PRE_PA7_POLICY",
    "V2_PRE_PA8_POLICY",
    "V2_PRE_PA9_POLICY",
    "V2_PRE_PB4_POLICY",
    "V2_PRE_PB6_POLICY",
    "V2_PRE_PB7_POLICY",
    "V2_PRE_W8_POLICY",
    "V2_PRE_W9_POLICY",
    "V2_PROFILE",
    "V2_W8_POLICY",
    "V2_W9_POLICY",
    "V3_DEC92_POLICY",
    "V3_POLICY",
    "V3_PROMPT_POLICY",
    "VALUE_POLICY",
    "VERIFIED_READ_POLICY",
    "VERIFIED_READ_V10_POLICY",
    "VERIFIED_READ_V11_POLICY",
    "VERIFIED_READ_V12_POLICY",
    "VERIFIED_READ_V2_POLICY",
    "VERIFIED_READ_V3_POLICY",
    "VERIFIED_READ_V4_POLICY",
    "VERIFIED_READ_V5_POLICY",
    "VERIFIED_READ_V6_POLICY",
    "VERIFIED_READ_V7_POLICY",
    "VERIFIED_READ_V8_POLICY",
    "VERIFIED_READ_V9_POLICY",
    "W3_POLICY",
    "W8_POLICY",
    "W8_POLICY_HASH",
    "canonical_hash",
    "sc1_inventory_policies",
    "sc1_policy",
]
