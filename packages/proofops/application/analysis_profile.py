"""One explicitly selected profile; old configurations remain byte-identical."""

from proofops.application.ingest.h1_boundaries import POLICY as H1_BOUNDARY_POLICY
from proofops.application.ingest.i3_wire import POLICY as I3_WIRE_POLICY
from proofops.application.ingest.j7_split import CONTEXT_POLICY
from proofops.application.ingest.j8_cells import POLICY as J8_CELLS_POLICY
from proofops.application.ingest.k1_boundaries import POLICY_HASH as K1_BOUNDARY_HASH
from proofops.application.ingest.k3_table_routing import POLICY as K3_ROUTING_POLICY
from proofops.application.ingest.k5_context import POLICY as K5_CONTEXT_POLICY
from proofops.application.ingest.k6_coverage import POLICY as K6_COVERAGE_POLICY
from proofops.application.ingest.q1_tables import POLICY as Q1_TABLE_POLICY
from proofops.application.ingest.sentence_prefix import POLICY as PREFIX_POLICY
from proofops.application.openai_retry import POLICY as T1_RETRY_POLICY
from proofops.application.openai_transport import POLICY as K10_TRANSPORT_POLICY
from proofops.application.provider_resilience import (
    HTTP_DIAGNOSTIC_POLICY,
    RESPONSE_ERROR_DIAGNOSTIC_POLICY,
    SCHEDULER_C24_POLICY,
    SCHEDULER_POLICY,
)
from proofops.application.provider_resilience import POLICY as F1_RESILIENCE_POLICY
from proofops.application.tagging.dec24 import (
    DEFINITIONS_HASH,
    INTEGRATED_DEFINITIONS_HASH,
    INTEGRATED_V2_DEFINITIONS_HASH,
)
from proofops.application.tagging.fact_assembly_c3 import POLICY as C3_POLICY
from proofops.application.tagging.fact_assembly_c3 import REVIEWED_IDENTITY as C3_IDENTITY
from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE
from proofops.application.tagging.finals_i4 import POLICY as I4_PROMPT_POLICY
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
from proofops.application.tagging.q1_contract import PROMPT_POLICY as Q1_PROMPT_POLICY
from proofops.application.tagging.q1_contract import SEMANTIC_POLICY as Q1_SEMANTIC_POLICY
from proofops.application.tagging.quality import ELEMENT_DEFINITIONS_HASH
from proofops.application.tagging.semantic_admission import POLICY as W8_POLICY
from proofops.application.tagging.semantic_admission import POLICY_HASH as W8_POLICY_HASH
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
V2_POLICY = FINALS_I11_POLICY


def policy_for(profile, *, pinned_hash=None):
    from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE
    from proofops.application.tagging.fact_assembly_c4 import publication_policy_for as c4_policy

    if profile == C4_PROFILE:
        return c4_policy(profile, pinned_hash=pinned_hash)
    from proofops.application.tagging.fact_assembly_c3 import PROFILE as C3_PROFILE
    from proofops.application.tagging.fact_assembly_c3 import publication_policy_for as c3_policy

    if profile == C3_PROFILE:
        return c3_policy(profile, pinned_hash=pinned_hash)
    from proofops.application.tagging.fact_assembly_c2 import POLICY as C2_POLICY
    from proofops.application.tagging.fact_assembly_c2 import PROFILE as C2_PROFILE

    if profile == C2_PROFILE:
        choices = (C2_POLICY,)
    elif profile == J7_PROFILE:
        choices = (J7_POLICY,)
    elif profile == J8_PROFILE:
        choices = (J8_POLICY,)
    elif profile == J3_PROFILE:
        choices = (J3_POLICY,)
    elif profile == PROFILE:
        choices = (POLICY,)
    elif profile == V2_PROFILE:
        choices = (
            V2_POLICY,
            FINALS_I10_POLICY,
            FINALS_K10_POLICY,
            FINALS_K10_V2_POLICY,
            FINALS_C24_POLICY,
            FINALS_Q1_POLICY,
            FINALS_E05_POLICY,
            FINALS_I9_POLICY,
            FINALS_I8_POLICY,
            FINALS_I7_POLICY,
            FINALS_K9_POLICY,
            FINALS_K9_INITIAL_POLICY,
            FINALS_K9_V2_POLICY,
            FINALS_K9_V3_POLICY,
            FINALS_K9_V4_POLICY,
            S4_POLICY,
            FINALS_S5_POLICY,
            FINALS_I6_POLICY,
            FINALS_K7_POLICY,
            FINALS_K8_POLICY,
            FINALS_K8_V2_POLICY,
            FINALS_K8_V3_POLICY,
            FINALS_K7_V1_POLICY,
            FINALS_I5_POLICY,
            FINALS_T1_POLICY,
            FINALS_F1_POLICY,
            FINALS_F1_TRANSPORT_POLICY,
            FINALS_F1_INITIAL_POLICY,
            FINALS_I5_INITIAL_POLICY,
            FINALS_I4_POLICY,
            FINALS_H1_POLICY,
            FINALS_K5_POLICY,
            FINALS_K6_POLICY,
            FINALS_I3_POLICY,
            FINALS_K4_POLICY,
            S2_POLICY,
            FINALS_I2_POLICY,
            FINALS_I2_J3_POLICY,
            FINALS_I1_POLICY,
            K1_POLICY,
            FINALS_K2_POLICY,
            K3_POLICY,
            FINALS_I1_INITIAL_POLICY,
            V2_D24_POLICY,
            V2_W9_POLICY,
            V2_PRE_W9_POLICY,
            V2_W8_POLICY,
            V2_PRE_W8_POLICY,
            V2_PRE_D24_POLICY,
            V2_PA9_POLICY,
            V2_PB7_POLICY,
            V2_PRE_PB7_POLICY,
            V2_PB6_POLICY,
            V2_PRE_PB6_POLICY,
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
            W3_POLICY,
            S1_POLICY,
        )
    else:
        raise ValueError("ANALYSIS_PROFILE_UNKNOWN")
    for policy in choices:
        if pinned_hash is None or canonical_hash(policy) == pinned_hash:
            return policy
    raise ValueError("ANALYSIS_PROFILE_PIN_MISMATCH")


def publication_policy_for(profile, *, pinned_hash=None):
    from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE
    from proofops.application.tagging.fact_assembly_c4 import publication_policy_for as c4_policy

    if profile == C4_PROFILE:
        return c4_policy(profile, pinned_hash=pinned_hash)
    from proofops.application.tagging.fact_assembly_c3 import PROFILE as C3_PROFILE
    from proofops.application.tagging.fact_assembly_c3 import publication_policy_for as c3_policy

    if profile == C3_PROFILE:
        return c3_policy(profile, pinned_hash=pinned_hash)
    from proofops.application.tagging.fact_assembly_c2 import PROFILE as C2_PROFILE
    from proofops.application.tagging.fact_assembly_c2 import (
        publication_policy_for as c2_publication,
    )

    if profile == C2_PROFILE:
        return c2_publication(profile, pinned_hash=pinned_hash)
    policy = policy_for(profile, pinned_hash=pinned_hash)
    allowed = (
        (
            policy_for(profile),
            FINALS_I10_POLICY,
            FINALS_K10_POLICY,
            FINALS_K10_V2_POLICY,
            FINALS_C24_POLICY,
            FINALS_Q1_POLICY,
            FINALS_E05_POLICY,
            FINALS_I9_POLICY,
            FINALS_I8_POLICY,
            FINALS_I7_POLICY,
            FINALS_K9_POLICY,
            FINALS_K9_INITIAL_POLICY,
            FINALS_K9_V2_POLICY,
            FINALS_K9_V3_POLICY,
            FINALS_K9_V4_POLICY,
            S4_POLICY,
            FINALS_S5_POLICY,
            FINALS_K7_POLICY,
            FINALS_K8_POLICY,
            FINALS_K8_V2_POLICY,
            FINALS_K8_V3_POLICY,
            FINALS_K7_V1_POLICY,
            FINALS_I6_POLICY,
            FINALS_I5_POLICY,
            FINALS_T1_POLICY,
            FINALS_F1_POLICY,
            FINALS_F1_TRANSPORT_POLICY,
            FINALS_F1_INITIAL_POLICY,
            FINALS_I5_INITIAL_POLICY,
            FINALS_I4_POLICY,
            FINALS_H1_POLICY,
            FINALS_K6_POLICY,
            FINALS_I3_POLICY,
            W3_POLICY,
            K1_POLICY,
            FINALS_K2_POLICY,
            S1_POLICY,
            S2_POLICY,
            FINALS_K5_POLICY,
        )
        if profile == V2_PROFILE
        else (policy_for(profile),)
    )
    if policy not in allowed:
        raise ValueError("ANALYSIS_PROFILE_PUBLICATION_PIN_MISMATCH")
    return policy


def apply_pilot_profile(args):
    profile = getattr(args, "analysis_profile", None) or getattr(args, "pipeline_profile", None)
    if profile not in (PROFILE, V2_PROFILE, J3_PROFILE, J7_PROFILE, J8_PROFILE):
        return
    if getattr(args, "resume", False):
        return  # persisted pins restored and checked by the pilot
    args.llm_provider = "openai"
    args.model = None
    args.parser = "mixed-v1"
    args.pipeline_profile = profile
    selected = policy_for(profile, pinned_hash=getattr(args, "analysis_policy_sha256", None))
    args.analysis_policy_sha256 = canonical_hash(selected)
    args.tagging_prompt_profile = selected.get("tagging_prompt_profile")
    args.extraction_i4_identity = bool(selected.get("extraction_selection_ids"))
    args.parser_local_resource_policy = selected.get("local_resource_policy")
    if selected.get("parser_source_recovery"):
        args.parser_source_recovery = selected["parser_source_recovery"]
    args.extraction_h1 = bool(selected.get("selected_boundary_recovery"))
    args.extraction_i5_tables = selected.get("table_failure_profile") == "i5-grid-unreadable-v1"
    if selected.get("tagging_budget") == S2_POLICY["tagging_budget"]:
        args.tagging_max_calls = selected["tagging_budget"]["max_calls"]
    args.extraction_k6 = bool(selected.get("coverage_policy"))
    args.extraction_q1 = bool(selected.get("activity_table_policy"))
    if profile in (V2_PROFILE, J3_PROFILE, J7_PROFILE, J8_PROFILE):
        args.extraction_fragment_guard = True
        args.extraction_pb1 = True
        args.extraction_w9 = selected.get("table_claims") == "pb1-w9-v1"
        args.extraction_k3 = bool(selected.get("table_worker_routing"))
        args.extraction_sentence_prefix = bool(selected.get("extraction_sentence_prefix"))
        args.extraction_j3 = bool(selected.get("selected_span_refinement"))
        args.extraction_j7 = selected.get("selected_span_refinement") == "j7-independent-clauses-v1"
        args.extraction_j8 = selected.get("table_cells") == J8_CELLS_POLICY["profile"]
        args.extraction_i3_wire = selected.get("extraction_wire") == "owned-cell-compact-i3-v1"
        args.extraction_pb1_context_guard = True
        args.extraction_table_footnotes = bool(selected.get("table_footnotes"))
        args.extraction_k1 = bool(selected.get("extraction_k1"))
        args.extraction_table_rows = True
        args.preliminary_actor_role = True
    # Hosted Linux uses its independently approved OCR reader. Keep that explicit
    # source policy pinned in the run; other callers retain the SV1 native policy.
    if profile in (V2_PROFILE, J3_PROFILE, J7_PROFILE, J8_PROFILE) and getattr(
        args, "claim_source_profile", None
    ) in (
        None,
        "claim-source-v3",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v7",
        "upstage-ocr-page-v8",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
        "upstage-ocr-page-v12",
        "upstage-ocr-page-v13",
    ):
        args.claim_source_profile = (
            selected["source"] if selected.get("table_worker_routing") else "upstage-ocr-page-v10"
        )
    if getattr(args, "claim_source_profile", None) not in {
        "upstage-ocr-page-v3",
        "upstage-ocr-page-v4",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v7",
        "upstage-ocr-page-v8",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
        "upstage-ocr-page-v11",
        "upstage-ocr-page-v12",
        "upstage-ocr-page-v13",
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
    if profile in (V2_PROFILE, J3_PROFILE, J7_PROFILE, J8_PROFILE):
        args.position_context_order = False
        args.preliminary_goal_role = True


def certification_profile_for(identity, *, pinned_hash=None):
    """V12 authorizes only the exact reviewed C3 input; C4 cannot be selected."""
    policy = policy_for(V2_PROFILE, pinned_hash=pinned_hash)
    if policy.get("direct_certification_policy") != C3_POLICY:
        return None
    if policy.get("direct_certification_policy_sha256") != canonical_hash(C3_POLICY):
        raise ValueError("CERTIFICATION_POLICY_PIN_MISMATCH")
    if all(identity.get(key) == value for key, value in C3_IDENTITY.items()):
        return C3_POLICY["profile"]
    return None
