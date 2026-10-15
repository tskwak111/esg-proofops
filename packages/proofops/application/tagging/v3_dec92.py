"""V3 / DEC-92/93 opt-in: category records and literal source semantics only.

No votes, checklist booleans, grade mappings or legal effects are manufactured.
Historical PB1/Q1 prompts and policy dictionaries are intentionally unchanged.
"""

import re
from dataclasses import asdict, replace

from proofops.application.tagging.q1_contract import PRELIMINARY as Q1_PRELIMINARY
from proofops.application.tagging.q1_contract import forecast_quote
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

PROFILE = "v3_dec92_categories_means_v1"
CLASSIFICATION_GUIDANCE = """
DEC-92/93: a company's simple target, net-zero or RE100 future declaration is a
forward_looking category candidate, independently of its goal track. Current
RE100 membership, an existing management system, achieved results, national
NDC descriptions and a purpose clause alone are not target declarations.
Keep the main predicate's track. A future review promise stays goal; a separate
assertion that an existing review procedure operates stays management.
Forecasts remain forecasts even without disclosed assumptions/scenarios; never
promote a forecast quantity to achieved performance/P1. Emissions estimates stay
emissions_estimate with identified_as_estimate, estimation_method, uncertainty
checked separately. Basis words in another company's scenario prove nothing.
Missing checklist facts require new tagging/review, never absent or true.
Category is a project record only: E/label/basis boolean remain null and legal
effect not_determined. Never claim immunity or reuse old responses as new votes.
Organization formation and a carbon-reduction purpose do not report a reduction
achievement, amount or year. Keep only the explicit formation/action. PUE value
maintenance remains performance; investment necessity alone is not a goal.
""".strip()
_OLD_CATEGORY = (
    "Ordinary company targets/deadlines are goal with category null. "
    "Forward-looking requires explicit forecast/estimate AND linked calculation basis, "
    "assumptions or uncertainty; words alone need review."
)
PRELIMINARY = Q1_PRELIMINARY.replace(_OLD_CATEGORY, CLASSIFICATION_GUIDANCE).replace(
    "목표 선언을 일괄 세이프하버로 바꾸지 않는다. ", ""
)
ELEMENT_GUIDANCE = """
V3 DEC-92/93: M1 may cite a named EXISTING review procedure in the immediately
preceding verified sentence of this same paragraph only when actor and activity
explicitly continue. Select the full preceding sentence from the catalog. A
review object plus '예정' alone is not a means. Do not turn a goal promise into
current management, or copy M1 to M4 or P1. Existing '검토·승인합니다' remains M1.
Organization formation is not reduction performance: no inferred amount,
achievement or performance year from a formation date. A separate literal
achievement sentence is reviewed independently. Forecast quantities are not P1.
Estimate checklist: identified_as_estimate, estimation_method, uncertainty;
forecast checklist: assumptions, scenario_or_premises. Missing facts stay unknown.
These records have no approved E/label/boolean mapping and no legal effect.
""".strip()
FORECAST = r"전망|예측|예상|forecast|projection|projected"
REVIEW_INTENT = r"검토.{0,20}(?:예정|계획|방침|하겠|할\s*것)"
NAMED_REVIEW = r"심의위원회|검토위원회|승인\s*절차|심의\s*절차|검토\s*절차|검토\s*프로세스"
EXISTING = (
    r"운영(?:합니다|하고|된다|됩니다|한다|해)|수립했|수립하였|갖추고|적용(?:합니다|하고)"
    r"|검토[·ㆍ/ ]*승인합니다"
)
FORMATION = r"(?:추진반|위원회|조직).{0,15}(?:구성|설립|신설)"
ACHIEVEMENT = r"(?:감축|절감|감소).{0,12}(?:달성|했|하였|했습니다)|줄였"
POLICY = dict(
    profile=PROFILE,
    preliminary_sha256=canonical_hash(PRELIMINARY),
    element_guidance_sha256=canonical_hash(ELEMENT_GUIDANCE),
    category="model-selected-company-target-or-literal-forecast;missing-facts-retag-required",
    m1="verified-immediately-preceding-sentence;same-paragraph;explicit-actor-and-activity",
    authority="source-and-binding-verified-model-votes;three-independent-replicas",
    mapping="category-only;grade-label-basis-null;legal-effect-not-determined",
    inference="no-inferred-reduction-performance;no-formation-year-as-performance-year",
    patterns=dict(
        forecast=FORECAST,
        review_intent=REVIEW_INTENT,
        named_review=NAMED_REVIEW,
        existing=EXISTING,
        formation=FORMATION,
        achievement=ACHIEVEMENT,
    ),
)
PROMPT_POLICY = dict(
    profile=PROFILE,
    preliminary_sha256=canonical_hash(PRELIMINARY),
    guidance_sha256=canonical_hash(ELEMENT_GUIDANCE),
    scope="DEC-92/93 category-only;literal-existing-M1",
)


def validate_policy(policy):
    if policy != POLICY:
        raise ValueError("V3_DEC92_POLICY_MISMATCH")


def preliminary(schema, *, quote=None):
    from proofops.application.tagging.finals_i4 import _require_k4_schema

    _require_k4_schema(schema)
    return PRELIMINARY.replace("{{OUTPUT_SCHEMA_JSON}}", canonical_json(schema))


def forward_candidate(text, *, track):
    """Literal candidate only; caller must validate actor, source and model choice."""
    if forecast_quote(text) or (
        track in ("goal", "performance") and re.search(FORECAST, text, re.I)
    ):
        return "forward_looking", "forecast_checklist_requires_review"
    # A source-bound goal can be a short table cell without a future verb or
    # the word 'target'. The model selects the main predicate; this is only a
    # category consistency check, never a keyword-based track conversion.
    if track == "goal":
        return "forward_looking", "target_category_mapping_unresolved"
    return None, "not_forward_candidate"


def validate_classification(result, claim, graph):
    """Veto inconsistent headers; never silently convert saved model votes."""
    from proofops.application.tagging.k4_contract import estimate_evidence

    track = result.track.track if result.track else None
    category = result.safe_harbor_category
    expected, reason = forward_candidate(claim.quote, track=track)
    if reason == "forecast_checklist_requires_review" and category != "forward_looking":
        # Calculation words do not turn an explicitly future quantity into an
        # emissions estimate (or an achieved result).
        raise ValueError("V3_DEC92_FORECAST_RETAG_REQUIRED")
    if category == "emissions_estimate":
        if not estimate_evidence(
            dict(
                tenant_id=claim.tenant_id,
                document_version_id=graph.document_version_id,
                claim_source_refs=[asdict(r) for r in claim.source_refs],
                safe_harbor_category=category,
            ),
            graph,
        ):
            raise ValueError("V3_DEC92_ESTIMATE_RETAG_REQUIRED")
    elif (expected and category != expected) or (category == "forward_looking" and not expected):
        raise ValueError("V3_DEC92_CATEGORY_RETAG_REQUIRED")
    if (
        re.search(FORMATION, claim.quote)
        and track == "performance"
        and not re.search(ACHIEVEMENT, claim.quote)
    ):
        raise ValueError("V3_DEC92_FORMATION_NOT_PERFORMANCE_RETAG_REQUIRED")
    return result


def guard(element, *, claim_quote):
    """Negative admission only: keep raw evidence and uncertainty states."""
    if element.state != "present":
        return element
    reason = None
    if element.element_id == "P1" and re.search(FORECAST, claim_quote, re.I):
        reason = "V3_DEC92_FORECAST_NOT_PERFORMANCE"
    elif (
        element.element_id == "P1"
        and re.search(FORMATION, claim_quote)
        and not re.search(ACHIEVEMENT, claim_quote)
    ):
        reason = "V3_DEC92_FORMATION_NOT_REDUCTION"
    elif element.element_id == "M1" and re.search(REVIEW_INTENT, claim_quote):
        if not any(
            re.search(NAMED_REVIEW, r.quote) and re.search(EXISTING, r.quote)
            for r in element.evidence_refs
        ):
            reason = "V3_DEC92_NAMED_EXISTING_MEANS_REQUIRED"
    return (
        replace(
            element, state="unknown", normalized_value=None, credited_from=None, reason_code=reason
        )
        if reason
        else element
    )


def hold_projection(item):
    from proofops.application.tagging.quality import _cause_specific_hold

    result = _cause_specific_hold(item)
    category = (item.get("frozen_packet") or {}).get("safe_harbor_category")
    category = category or result.get("safe_harbor_category")
    codes = {item.get("reason"), result.get("reason")}
    codes.update(
        (r.get("stable_reason") or {}).get("error_code")
        for r in item.get("preliminary_records", [])
    )
    retag = any(c and c.startswith("V3_DEC92_") and c.endswith("RETAG_REQUIRED") for c in codes)
    if category not in ("forward_looking", "emissions_estimate") and not retag:
        return result
    if retag:
        display, detail = "범주·원문 확인 필요", "새 정책에 따른 태깅 필요"
    elif category == "emissions_estimate":
        display, detail = "추정치 · 산정 근거 확인 필요", "추정 표시·산정 방법·불확실성 확인 필요"
    elif (item.get("frozen_packet") or {}).get("track") == "goal" and not re.search(
        FORECAST, (item.get("frozen_packet") or {}).get("atomic_quote", ""), re.I
    ):
        display, detail = "목표 선언 · 세이프하버 범주", "등급 매핑 미정 · 가정·시나리오 확인 필요"
    else:
        display, detail = "전망치 · 가정·시나리오 확인 필요", "전망값 그대로 표시 · 실적 인정 아님"
    names = (
        ("identified_as_estimate", "estimation_method", "uncertainty")
        if category == "emissions_estimate"
        else ("assumptions", "scenario_or_premises")
    )
    # The tagging wire does not collect checklist facts. Never infer them from
    # keywords or ordinary G/P/M elements, including three matching old outputs.
    return result | dict(
        evidence_grade=None,
        label=None,
        grade_range=None,
        display_type="hold",
        display=display,
        grade_basis="retag_required" if retag else "safe_harbor_mapping_unresolved",
        gap_ids=list(dict.fromkeys([*result.get("gap_ids", []), "GAP-001"])),
        hold_reasons=list(
            dict.fromkeys(
                [
                    *[
                        r
                        for r in result.get("hold_reasons", [])
                        if r != "추정치 · 산정 근거 확인 필요"
                    ],
                    detail,
                ]
            )
        ),
        v3_safe_harbor=dict(
            category=category,
            checklist={name: "unknown" for name in names},
            checklist_status="retag_required",
            reasonable_basis_documented=None,
            grade_mapping=None,
            legal_effect="not_determined",
            policy_sha256=canonical_hash(POLICY),
        ),
    )
