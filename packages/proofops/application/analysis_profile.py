"""Current default, one policy registry, and compatible public entry points.

PC1: mechanically extracted legacy policies. Historical definitions are re-exported explicitly.
"""

from proofops.application.policies.legacy import analysis_profiles as _legacy
from proofops.application.policies.registry import (
    v2_policy_registry as _v2_policy_registry,
)

# Explicit aliases preserve historical imports and object identity.
C3_IDENTITY = _legacy.C3_IDENTITY
C3_POLICY = _legacy.C3_POLICY
C3_V2_LEGACY_POLICY = _legacy.C3_V2_LEGACY_POLICY
C3_V2_POLICY = _legacy.C3_V2_POLICY
C4_PROFILE = _legacy.C4_PROFILE
CF1_3OF3_POLICY = _legacy.CF1_3OF3_POLICY
CF1_INVENTORY_POLICY = _legacy.CF1_INVENTORY_POLICY
CF1_MAJORITY_POLICY = _legacy.CF1_MAJORITY_POLICY
CF1_POLICY = _legacy.CF1_POLICY
CF2_C3_BINDING = _legacy.CF2_C3_BINDING
CF2_C3_POLICY = _legacy.CF2_C3_POLICY
CF4_SOURCE_POLICY = _legacy.CF4_SOURCE_POLICY
CF5_CONTEXT_POLICY = _legacy.CF5_CONTEXT_POLICY
CF5_POLICY = _legacy.CF5_POLICY
CF5_PROMPT_PROFILE = _legacy.CF5_PROMPT_PROFILE
CF6_CONFIRMATION_POLICY = _legacy.CF6_CONFIRMATION_POLICY
CF6_POLICY = _legacy.CF6_POLICY
CF6_V2_CONFIRMATION_POLICY = _legacy.CF6_V2_CONFIRMATION_POLICY
CF6_V2_POLICY = _legacy.CF6_V2_POLICY
CLAIM_LAYOUT_POLICY = _legacy.CLAIM_LAYOUT_POLICY
CONTEXT_POLICY = _legacy.CONTEXT_POLICY
DEFINITIONS_HASH = _legacy.DEFINITIONS_HASH
ELEMENT_DEFINITIONS_HASH = _legacy.ELEMENT_DEFINITIONS_HASH
F1_RESILIENCE_POLICY = _legacy.F1_RESILIENCE_POLICY
FACILITY_POLICY = _legacy.FACILITY_POLICY
FINALS_C24_POLICY = _legacy.FINALS_C24_POLICY
FINALS_D2_POLICY = _legacy.FINALS_D2_POLICY
FINALS_E05_POLICY = _legacy.FINALS_E05_POLICY
FINALS_F1_INITIAL_POLICY = _legacy.FINALS_F1_INITIAL_POLICY
FINALS_F1_POLICY = _legacy.FINALS_F1_POLICY
FINALS_F1_TRANSPORT_POLICY = _legacy.FINALS_F1_TRANSPORT_POLICY
FINALS_FXB_POLICY = _legacy.FINALS_FXB_POLICY
FINALS_FXC_POLICY = _legacy.FINALS_FXC_POLICY
FINALS_H1_POLICY = _legacy.FINALS_H1_POLICY
FINALS_H4_POLICY = _legacy.FINALS_H4_POLICY
FINALS_H5_POLICY = _legacy.FINALS_H5_POLICY
FINALS_H6_POLICY = _legacy.FINALS_H6_POLICY
FINALS_H7_POLICY = _legacy.FINALS_H7_POLICY
FINALS_HX3_POLICY = _legacy.FINALS_HX3_POLICY
FINALS_HX4_COMPLETE_POLICY = _legacy.FINALS_HX4_COMPLETE_POLICY
FINALS_HX4_POLICY = _legacy.FINALS_HX4_POLICY
FINALS_HX5_POLICY = _legacy.FINALS_HX5_POLICY
FINALS_HX5_V1_POLICY = _legacy.FINALS_HX5_V1_POLICY
FINALS_HX6_COMPLETE_POLICY = _legacy.FINALS_HX6_COMPLETE_POLICY
FINALS_HX6_POLICY = _legacy.FINALS_HX6_POLICY
FINALS_HX6_RESILIENT_POLICY = _legacy.FINALS_HX6_RESILIENT_POLICY
FINALS_I10_POLICY = _legacy.FINALS_I10_POLICY
FINALS_I11_POLICY = _legacy.FINALS_I11_POLICY
FINALS_I12_POLICY = _legacy.FINALS_I12_POLICY
FINALS_I13_POLICY = _legacy.FINALS_I13_POLICY
FINALS_I15_POLICY = _legacy.FINALS_I15_POLICY
FINALS_I16_POLICY = _legacy.FINALS_I16_POLICY
FINALS_I17_POLICY = _legacy.FINALS_I17_POLICY
FINALS_I18_POLICY = _legacy.FINALS_I18_POLICY
FINALS_I19_POLICY = _legacy.FINALS_I19_POLICY
FINALS_I1_INITIAL_POLICY = _legacy.FINALS_I1_INITIAL_POLICY
FINALS_I1_POLICY = _legacy.FINALS_I1_POLICY
FINALS_I20_INITIAL_POLICY = _legacy.FINALS_I20_INITIAL_POLICY
FINALS_I20_POLICY = _legacy.FINALS_I20_POLICY
FINALS_I20_PRE_FXB_POLICY = _legacy.FINALS_I20_PRE_FXB_POLICY
FINALS_I20_PRE_FXC_POLICY = _legacy.FINALS_I20_PRE_FXC_POLICY
FINALS_I21_POLICY = _legacy.FINALS_I21_POLICY
FINALS_I22_POLICY = _legacy.FINALS_I22_POLICY
FINALS_I23_POLICY = _legacy.FINALS_I23_POLICY
FINALS_I24_POLICY = _legacy.FINALS_I24_POLICY
FINALS_I25_POLICY = _legacy.FINALS_I25_POLICY
FINALS_I26_POLICY = _legacy.FINALS_I26_POLICY
FINALS_I27_POLICY = _legacy.FINALS_I27_POLICY
FINALS_I27_PRE_RB2_POLICY = _legacy.FINALS_I27_PRE_RB2_POLICY
FINALS_I28_POLICY = _legacy.FINALS_I28_POLICY
FINALS_I29B_POLICY = _legacy.FINALS_I29B_POLICY
FINALS_I29_INITIAL_POLICY = _legacy.FINALS_I29_INITIAL_POLICY
FINALS_I29_POLICY = _legacy.FINALS_I29_POLICY
FINALS_I2_J3_POLICY = _legacy.FINALS_I2_J3_POLICY
FINALS_I2_POLICY = _legacy.FINALS_I2_POLICY
FINALS_I30_POLICY = _legacy.FINALS_I30_POLICY
FINALS_I3_POLICY = _legacy.FINALS_I3_POLICY
FINALS_I4_POLICY = _legacy.FINALS_I4_POLICY
FINALS_I5_INITIAL_POLICY = _legacy.FINALS_I5_INITIAL_POLICY
FINALS_I5_POLICY = _legacy.FINALS_I5_POLICY
FINALS_I6_POLICY = _legacy.FINALS_I6_POLICY
FINALS_I7_POLICY = _legacy.FINALS_I7_POLICY
FINALS_I8_POLICY = _legacy.FINALS_I8_POLICY
FINALS_I9_POLICY = _legacy.FINALS_I9_POLICY
FINALS_K10_POLICY = _legacy.FINALS_K10_POLICY
FINALS_K10_V2_POLICY = _legacy.FINALS_K10_V2_POLICY
FINALS_K11_POLICY = _legacy.FINALS_K11_POLICY
FINALS_K11_V1_POLICY = _legacy.FINALS_K11_V1_POLICY
FINALS_K2_POLICY = _legacy.FINALS_K2_POLICY
FINALS_K4_POLICY = _legacy.FINALS_K4_POLICY
FINALS_K5_POLICY = _legacy.FINALS_K5_POLICY
FINALS_K6_POLICY = _legacy.FINALS_K6_POLICY
FINALS_K7_POLICY = _legacy.FINALS_K7_POLICY
FINALS_K7_V1_POLICY = _legacy.FINALS_K7_V1_POLICY
FINALS_K8_POLICY = _legacy.FINALS_K8_POLICY
FINALS_K8_V2_POLICY = _legacy.FINALS_K8_V2_POLICY
FINALS_K8_V3_POLICY = _legacy.FINALS_K8_V3_POLICY
FINALS_K9_INITIAL_POLICY = _legacy.FINALS_K9_INITIAL_POLICY
FINALS_K9_POLICY = _legacy.FINALS_K9_POLICY
FINALS_K9_V2_POLICY = _legacy.FINALS_K9_V2_POLICY
FINALS_K9_V3_POLICY = _legacy.FINALS_K9_V3_POLICY
FINALS_K9_V4_POLICY = _legacy.FINALS_K9_V4_POLICY
FINALS_P2_POLICY = _legacy.FINALS_P2_POLICY
FINALS_P3_POLICY = _legacy.FINALS_P3_POLICY
FINALS_Q1_POLICY = _legacy.FINALS_Q1_POLICY
FINALS_RG1_POLICY = _legacy.FINALS_RG1_POLICY
FINALS_S2_SPEED_POLICY = _legacy.FINALS_S2_SPEED_POLICY
FINALS_S5_POLICY = _legacy.FINALS_S5_POLICY
FINALS_T1_POLICY = _legacy.FINALS_T1_POLICY
FXE_POLICY = _legacy.FXE_POLICY
FXF_POLICY = _legacy.FXF_POLICY
FXG_POLICY = _legacy.FXG_POLICY
FXG_WIRE_POLICY = _legacy.FXG_WIRE_POLICY
FXH_POLICY = _legacy.FXH_POLICY
FXH_RUNTIME_POLICY = _legacy.FXH_RUNTIME_POLICY
H1_BOUNDARY_POLICY = _legacy.H1_BOUNDARY_POLICY
HTTP_DIAGNOSTIC_POLICY = _legacy.HTTP_DIAGNOSTIC_POLICY
HX5_INPUT_POLICY = _legacy.HX5_INPUT_POLICY
HX6_RECOVERY_POLICY = _legacy.HX6_RECOVERY_POLICY
I18_PUBLICATION_POLICY = _legacy.I18_PUBLICATION_POLICY
I24_INVENTORY_POLICY = _legacy.I24_INVENTORY_POLICY
I27_INVENTORY_POLICY = _legacy.I27_INVENTORY_POLICY
I3_WIRE_POLICY = _legacy.I3_WIRE_POLICY
I4_PROMPT_POLICY = _legacy.I4_PROMPT_POLICY
INTEGRATED_DEFINITIONS_HASH = _legacy.INTEGRATED_DEFINITIONS_HASH
INTEGRATED_V2_DEFINITIONS_HASH = _legacy.INTEGRATED_V2_DEFINITIONS_HASH
J3_POLICY = _legacy.J3_POLICY
J3_PROFILE = _legacy.J3_PROFILE
J7_POLICY = _legacy.J7_POLICY
J7_PROFILE = _legacy.J7_PROFILE
J8_CELLS_POLICY = _legacy.J8_CELLS_POLICY
J8_POLICY = _legacy.J8_POLICY
J8_PROFILE = _legacy.J8_PROFILE
K10_SEMANTIC_POLICY = _legacy.K10_SEMANTIC_POLICY
K10_SEMANTIC_V2_POLICY = _legacy.K10_SEMANTIC_V2_POLICY
K10_TRANSPORT_POLICY = _legacy.K10_TRANSPORT_POLICY
K10_WIRE_POLICY = _legacy.K10_WIRE_POLICY
K11_WIRE_POLICY = _legacy.K11_WIRE_POLICY
K11_WIRE_V1_POLICY = _legacy.K11_WIRE_V1_POLICY
K1_BOUNDARY_HASH = _legacy.K1_BOUNDARY_HASH
K1_DEFINITIONS = _legacy.K1_DEFINITIONS
K1_POLICY = _legacy.K1_POLICY
K1_SEMANTIC_POLICY = _legacy.K1_SEMANTIC_POLICY
K2_RECOVERY_POLICY = _legacy.K2_RECOVERY_POLICY
K3_POLICY = _legacy.K3_POLICY
K3_ROUTING_POLICY = _legacy.K3_ROUTING_POLICY
K5_CONTEXT_POLICY = _legacy.K5_CONTEXT_POLICY
K6_CITATION_POLICY = _legacy.K6_CITATION_POLICY
K6_COVERAGE_POLICY = _legacy.K6_COVERAGE_POLICY
K6_RISK_POLICY = _legacy.K6_RISK_POLICY
K7_WIRE_POLICY = _legacy.K7_WIRE_POLICY
K7_WIRE_V1_POLICY = _legacy.K7_WIRE_V1_POLICY
K8_WIRE_POLICY = _legacy.K8_WIRE_POLICY
K8_WIRE_V2_POLICY = _legacy.K8_WIRE_V2_POLICY
K8_WIRE_V3_POLICY = _legacy.K8_WIRE_V3_POLICY
K9_BINDING_POLICY = _legacy.K9_BINDING_POLICY
K9_BINDING_V1_POLICY = _legacy.K9_BINDING_V1_POLICY
K9_BINDING_V2_POLICY = _legacy.K9_BINDING_V2_POLICY
K9_BINDING_V3_POLICY = _legacy.K9_BINDING_V3_POLICY
K9_BINDING_V4_POLICY = _legacy.K9_BINDING_V4_POLICY
K9_PROMPT_POLICY = _legacy.K9_PROMPT_POLICY
K9_PROMPT_PROFILE = _legacy.K9_PROMPT_PROFILE
LOCATED_TABLE_CONTEXT_POLICY = _legacy.LOCATED_TABLE_CONTEXT_POLICY
MODEL_RESPONSE_POLICY = _legacy.MODEL_RESPONSE_POLICY
OPS2_POLICY = _legacy.OPS2_POLICY
PAGE_OCR_PROFILES = _legacy.PAGE_OCR_PROFILES
POLICY = _legacy.POLICY
POLICY_HASH = _legacy.POLICY_HASH
PREFIX_POLICY = _legacy.PREFIX_POLICY
PROFILE = _legacy.PROFILE
Q1_PROMPT_POLICY = _legacy.Q1_PROMPT_POLICY
Q1_SEMANTIC_POLICY = _legacy.Q1_SEMANTIC_POLICY
Q1_TABLE_POLICY = _legacy.Q1_TABLE_POLICY
QA2_POLICY = _legacy.QA2_POLICY
QC2_FIGURE_POLICY = _legacy.QC2_FIGURE_POLICY
QT1_BASELINE_POLICY = _legacy.QT1_BASELINE_POLICY
QT1_GOAL_SPLIT_POLICY = _legacy.QT1_GOAL_SPLIT_POLICY
QT1_POLICY = _legacy.QT1_POLICY
QT1_TABLE_POLICY = _legacy.QT1_TABLE_POLICY
QT1_TUPLE_POLICY = _legacy.QT1_TUPLE_POLICY
QT1_V25_POLICY = _legacy.QT1_V25_POLICY
QT2_CONTEXT_POLICY = _legacy.QT2_CONTEXT_POLICY
QT2_ELEMENTS_POLICY = _legacy.QT2_ELEMENTS_POLICY
R18_POLICY = _legacy.R18_POLICY
RB1_INPUT_POLICY = _legacy.RB1_INPUT_POLICY
RB1_POLICY = _legacy.RB1_POLICY
RB2_POLICY = _legacy.RB2_POLICY
RB3_DEADLINE_POLICY = _legacy.RB3_DEADLINE_POLICY
RB3_DEADLINE_V2_POLICY = _legacy.RB3_DEADLINE_V2_POLICY
RB3_POLICY = _legacy.RB3_POLICY
RB4_MEMORY_POLICY = _legacy.RB4_MEMORY_POLICY
RB4_POLICY = _legacy.RB4_POLICY
RB4_PUBLICATION_POLICY = _legacy.RB4_PUBLICATION_POLICY
RB4_STREAM_POLICY = _legacy.RB4_STREAM_POLICY
RESPONSE_ERROR_DIAGNOSTIC_POLICY = _legacy.RESPONSE_ERROR_DIAGNOSTIC_POLICY
RESPONSE_POLICY = _legacy.RESPONSE_POLICY
RG1_PUBLICATION_POLICY = _legacy.RG1_PUBLICATION_POLICY
S1_POLICY = _legacy.S1_POLICY
S2_POLICY = _legacy.S2_POLICY
S3_SPEED_POLICY = _legacy.S3_SPEED_POLICY
S3_VERIFIED_READ_V13_POLICY = _legacy.S3_VERIFIED_READ_V13_POLICY
S4_POLICY = _legacy.S4_POLICY
S4_PUBLICATION_POLICY = _legacy.S4_PUBLICATION_POLICY
S5_C3_BINDING = _legacy.S5_C3_BINDING
S5_LIVE_POLICY = _legacy.S5_LIVE_POLICY
SCHEDULER_C24_POLICY = _legacy.SCHEDULER_C24_POLICY
SCHEDULER_POLICY = _legacy.SCHEDULER_POLICY
SEMANTIC_POLICY = _legacy.SEMANTIC_POLICY
SPE_POLICY = _legacy.SPE_POLICY
SPG_POLICY = _legacy.SPG_POLICY
SPG_PUBLICATION_POLICY = _legacy.SPG_PUBLICATION_POLICY
SPP_POLICY = _legacy.SPP_POLICY
SPT_PIPELINE_POLICY = _legacy.SPT_PIPELINE_POLICY
SPT_POLICY = _legacy.SPT_POLICY
T1_RETRY_POLICY = _legacy.T1_RETRY_POLICY
TB1_POLICY = _legacy.TB1_POLICY
TB1_TABLE_POLICY = _legacy.TB1_TABLE_POLICY
V1_ACTIVITY_LINK_POLICY = _legacy.V1_ACTIVITY_LINK_POLICY
V1_ACTIVITY_POLICY = _legacy.V1_ACTIVITY_POLICY
V2_D24_POLICY = _legacy.V2_D24_POLICY
V2_HF1_POLICY = _legacy.V2_HF1_POLICY
V2_INITIAL_POLICY = _legacy.V2_INITIAL_POLICY
V2_PA2_POLICY = _legacy.V2_PA2_POLICY
V2_PA3_POLICY = _legacy.V2_PA3_POLICY
V2_PA4_POLICY = _legacy.V2_PA4_POLICY
V2_PA9_POLICY = _legacy.V2_PA9_POLICY
V2_PB1_COMPACT_POLICY = _legacy.V2_PB1_COMPACT_POLICY
V2_PB1_INITIAL_POLICY = _legacy.V2_PB1_INITIAL_POLICY
V2_PB1_POLICY = _legacy.V2_PB1_POLICY
V2_PB2_ALL_CLAIMS_POLICY = _legacy.V2_PB2_ALL_CLAIMS_POLICY
V2_PB2_INITIAL_POLICY = _legacy.V2_PB2_INITIAL_POLICY
V2_PB2_POLICY = _legacy.V2_PB2_POLICY
V2_PB4_POLICY = _legacy.V2_PB4_POLICY
V2_PB6_POLICY = _legacy.V2_PB6_POLICY
V2_PB7_POLICY = _legacy.V2_PB7_POLICY
V2_POLICY = _legacy.V2_POLICY
V2_PRE_D24_POLICY = _legacy.V2_PRE_D24_POLICY
V2_PRE_HF1_POLICY = _legacy.V2_PRE_HF1_POLICY
V2_PRE_PA1_POLICY = _legacy.V2_PRE_PA1_POLICY
V2_PRE_PA2_POLICY = _legacy.V2_PRE_PA2_POLICY
V2_PRE_PA3_POLICY = _legacy.V2_PRE_PA3_POLICY
V2_PRE_PA4_POLICY = _legacy.V2_PRE_PA4_POLICY
V2_PRE_PA7_POLICY = _legacy.V2_PRE_PA7_POLICY
V2_PRE_PA8_POLICY = _legacy.V2_PRE_PA8_POLICY
V2_PRE_PA9_POLICY = _legacy.V2_PRE_PA9_POLICY
V2_PRE_PB4_POLICY = _legacy.V2_PRE_PB4_POLICY
V2_PRE_PB6_POLICY = _legacy.V2_PRE_PB6_POLICY
V2_PRE_PB7_POLICY = _legacy.V2_PRE_PB7_POLICY
V2_PRE_W8_POLICY = _legacy.V2_PRE_W8_POLICY
V2_PRE_W9_POLICY = _legacy.V2_PRE_W9_POLICY
V2_PROFILE = _legacy.V2_PROFILE
V2_W8_POLICY = _legacy.V2_W8_POLICY
V2_W9_POLICY = _legacy.V2_W9_POLICY
V3_DEC92_POLICY = _legacy.V3_DEC92_POLICY
V3_POLICY = _legacy.V3_POLICY
V3_PROMPT_POLICY = _legacy.V3_PROMPT_POLICY
VALUE_POLICY = _legacy.VALUE_POLICY
VERIFIED_READ_POLICY = _legacy.VERIFIED_READ_POLICY
VERIFIED_READ_V10_POLICY = _legacy.VERIFIED_READ_V10_POLICY
VERIFIED_READ_V11_POLICY = _legacy.VERIFIED_READ_V11_POLICY
VERIFIED_READ_V12_POLICY = _legacy.VERIFIED_READ_V12_POLICY
VERIFIED_READ_V2_POLICY = _legacy.VERIFIED_READ_V2_POLICY
VERIFIED_READ_V3_POLICY = _legacy.VERIFIED_READ_V3_POLICY
VERIFIED_READ_V4_POLICY = _legacy.VERIFIED_READ_V4_POLICY
VERIFIED_READ_V5_POLICY = _legacy.VERIFIED_READ_V5_POLICY
VERIFIED_READ_V6_POLICY = _legacy.VERIFIED_READ_V6_POLICY
VERIFIED_READ_V7_POLICY = _legacy.VERIFIED_READ_V7_POLICY
VERIFIED_READ_V8_POLICY = _legacy.VERIFIED_READ_V8_POLICY
VERIFIED_READ_V9_POLICY = _legacy.VERIFIED_READ_V9_POLICY
W3_POLICY = _legacy.W3_POLICY
W8_POLICY = _legacy.W8_POLICY
W8_POLICY_HASH = _legacy.W8_POLICY_HASH
canonical_hash = _legacy.canonical_hash
sc1_inventory_policies = _legacy.sc1_inventory_policies
sc1_policy = _legacy.sc1_policy


# I31 retains v29c execution and adds verified TB1 bundles plus UX1 projection.
# Earlier definitions and source readers remain immutable for historical replay.
FINALS_I31_POLICY = FINALS_I30_POLICY | dict(
    integration_profile="finals-20261017-v29d",
    source="i31_claim_source_v1",
    tb1_table_policy=TB1_POLICY["tb1_table_policy"],
    tb1_table_policy_sha256=TB1_POLICY["tb1_table_policy_sha256"],
    ux1_data_policy_sha256="bf9c32d96dde26ab8575bedc8cbbce157e74c1a1dd9c0b57634f4cdd9fcf50b3",
)
V2_POLICY = FINALS_I31_POLICY


def policy_for(profile, *, pinned_hash=None):
    from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE
    from proofops.application.tagging.fact_assembly_c3_v2 import (
        publication_policy_for as c3_v2_policy,
    )

    if profile == C3_V2_PROFILE:
        return c3_v2_policy(profile, pinned_hash=pinned_hash)
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
        choices = tuple(policy for policy, _ in _v2_policy_registry(V2_POLICY))
    else:
        raise ValueError("ANALYSIS_PROFILE_UNKNOWN")
    for policy in choices:
        if pinned_hash is None or canonical_hash(policy) == pinned_hash:
            return policy
    raise ValueError("ANALYSIS_PROFILE_PIN_MISMATCH")


def publication_policy_for(profile, *, pinned_hash=None):
    from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE
    from proofops.application.tagging.fact_assembly_c3_v2 import (
        publication_policy_for as c3_v2_policy,
    )

    if profile == C3_V2_PROFILE:
        return c3_v2_policy(profile, pinned_hash=pinned_hash)
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
        tuple(policy for policy, hosted in _v2_policy_registry(V2_POLICY) if hosted)
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
    args.extraction_atomic_v3 = (
        selected.get("extraction_candidate_profile") == "extraction-atomic-v3"
    )
    args.extraction_failure_diagnostics = bool(selected.get("extraction_failure_diagnostics"))
    args.extraction_i4_identity = bool(selected.get("extraction_selection_ids"))
    args.extraction_qc_native_figures = bool(selected.get("native_figure_policy"))
    args.extraction_fxg_split = bool(selected.get("fxg_extraction_wire_policy"))
    args.extraction_qt1_goal_split = bool(selected.get("qt1_goal_split_policy"))
    args.extraction_located_table_context = bool(selected.get("located_table_context"))
    args.parser_local_resource_policy = selected.get("local_resource_policy")
    args.parser_failure_policy = selected.get("parser_failure_policy")
    args.parser_output_policy = selected.get("parser_output_policy")
    args.parser_execution_policy = selected.get("parser_execution_policy")
    if selected.get("parser_source_recovery"):
        args.parser_source_recovery = selected["parser_source_recovery"]
    args.extraction_h1 = bool(selected.get("selected_boundary_recovery"))
    args.extraction_i5_tables = selected.get("table_failure_profile") == "i5-grid-unreadable-v1"
    if selected.get("tagging_budget") == S2_POLICY["tagging_budget"]:
        args.tagging_max_calls = selected["tagging_budget"]["max_calls"]
    args.extraction_k6 = bool(selected.get("coverage_policy"))
    args.extraction_q1 = bool(selected.get("activity_table_policy"))
    args.extraction_qt1 = bool(selected.get("qt1_table_recovery_policy"))
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
    if selected.get("page_recovery_policy") in (HX6_RECOVERY_POLICY, CLAIM_LAYOUT_POLICY):
        # HX6 needs the complete original-byte reader even when hosted Darwin's
        # initial arguments requested the older glyph-only source profile.
        args.claim_source_profile = selected["source"]
    if profile in (V2_PROFILE, J3_PROFILE, J7_PROFILE, J8_PROFILE) and getattr(
        args, "claim_source_profile", None
    ) in {
        None,
        "claim-source-v3",
        *(
            PAGE_OCR_PROFILES.keys()
            - {
                "upstage-ocr-page-v1",
                "upstage-ocr-page-v2",
                "upstage-ocr-page-v3",
                "upstage-ocr-page-v4",
            }
        ),
    }:
        args.claim_source_profile = (
            selected["source"] if selected.get("table_worker_routing") else "upstage-ocr-page-v10"
        )
    allowed_source_profiles = (
        PAGE_OCR_PROFILES.keys() - {"upstage-ocr-page-v1", "upstage-ocr-page-v2"}
    ) | {"claim-source-v4"}
    if getattr(args, "claim_source_profile", None) not in allowed_source_profiles:
        args.claim_source_profile = "claim-source-v3"
    if selected == FINALS_HX4_POLICY:
        args.claim_source_profile = "upstage-ocr-page-v16-hx4"
    elif selected == FINALS_HX5_POLICY:
        args.claim_source_profile = "upstage-ocr-page-v16-hx5"
    elif selected == FINALS_RG1_POLICY:
        args.claim_source_profile = "upstage-ocr-page-v17-rg1"
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
    """V12 and successors authorize only the exact reviewed C3 input."""
    policy = policy_for(V2_PROFILE, pinned_hash=pinned_hash)
    if policy.get("direct_certification_policy") == C3_V2_POLICY:
        # Retain the legacy exact-identity lookup for existing callers; new
        # source-stable runs use prepare_case and the V2 fingerprint gate.
        return (
            C3_POLICY["profile"]
            if all(identity.get(key) == value for key, value in C3_IDENTITY.items())
            else None
        )
    if policy.get("direct_certification_policy") != C3_POLICY:
        return None
    if policy.get("direct_certification_policy_sha256") != canonical_hash(C3_POLICY):
        raise ValueError("CERTIFICATION_POLICY_PIN_MISMATCH")
    if all(identity.get(key) == value for key, value in C3_IDENTITY.items()):
        return C3_POLICY["profile"]
    return None
