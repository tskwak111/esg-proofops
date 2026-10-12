"""Q1 literal vetoes and local guidance; never generate semantic present votes."""

import re
from dataclasses import asdict, replace

from proofops.application.tagging.k4_contract import SEMANTIC_POLICY as BASE
from proofops.application.tagging.k9_contract import PRELIMINARY as K9_PRELIMINARY
from proofops.domain.provenance import canonical_hash

PROFILE = "finals-q1-structural-v1"
CLASSIFICATION_GUIDANCE = (
    "\nQ1 / 원문 v2 §4.2–4.6: 미래 시나리오·전망의 재무영향은 달성실적이 아니며 "
    "forward_looking 후보로 별도 검토한다. 목표 선언을 일괄 세이프하버로 바꾸지 않는다. "
    "문헌조사·현장실사를 실시하여 파악한 정량 없는 조사 절차와 탄소비용 사전 반영은 "
    "management이다. 설비·공정 최적화와 정량 감축 효과의 주장 성격은 각각 보존한다. "
    "예시는 원문 근거가 아니며 등급·라벨은 Python만 계산한다."
)
YEAR_GUIDANCE = (
    "\nG1은 목표 문장의 '2025년에는 ... 목표로 설정' 같은 직접 연도도 인용한다. "
    "목표연도와 관측기간을 혼동하거나 다른 문장의 연도를 차용하지 않는다."
)
QUANTITY_GUIDANCE = (
    "\nP1은 8건·3만 톤 같은 단위와 규모를 원문 그대로 보존한다. 인증 수량은 "
    "'총 17개 생산 사업장 중 15개 사업장'처럼 분모·분자를 함께 인용하고 그 전체를 "
    "normalized_value로 사용한다. 선택하지 않은 값을 복원하거나 unknown을 바꾸지 않는다."
)
PROCESS_GUIDANCE = (
    "\n탄소비용을 사전에 반영하는 명시적 절차는 M1 수단이다. 문헌조사·현장실사를 "
    "실시한 정량 없는 조사 이행의 M1/M4는 명시된 방법·실시 원문을 실제 인용한다."
)
GOVERNANCE_GUIDANCE = (
    "\n총괄임원·대표이사·이사회로 이어지는 정기 보고체계의 M5는 M1과 독립 태깅한다. "
    "그 담당조직과 보고 관계가 명시된 원문 전체를 인용한다."
)
NEGATIVE_GUIDANCE = (
    "\nG6는 관련 활동 추진만으로 불충분하다. 명명된 수단·계획을 실제 인용해야 한다. "
    "포트폴리오 확대, 활동 추진, 일반 기술·설계 적용, 실행 촉진만으로 M4 구체적 실적을 "
    "만들지 않는다. 유관부서만으로 M2 경계를 확정하지 않는다."
)
GUIDANCE = (
    CLASSIFICATION_GUIDANCE
    + YEAR_GUIDANCE
    + QUANTITY_GUIDANCE
    + PROCESS_GUIDANCE
    + GOVERNANCE_GUIDANCE
    + NEGATIVE_GUIDANCE
)
PRELIMINARY = K9_PRELIMINARY + CLASSIFICATION_GUIDANCE
PROMPT_POLICY = dict(
    profile=PROFILE,
    preliminary_sha256=canonical_hash(PRELIMINARY),
    guidance_sha256=canonical_hash(GUIDANCE),
    scope="literal-targets-only",
)
GENERIC_PLAN = r"(?:관련|다양한|일련의)\s*활동.*추진"
NAMED_PLAN = r"PPA|CCS|수소|전력\s*구매|자가\s*발전|태양광|로드맵|전환\s*계획|단계적\s*도입"
GENERIC_RESULT = (
    r"제품\s*포트폴리오\s*확대|(?:다양한|환경\s*가치를\s*반영한).*활동.*추진|"
    r"에너지\s*절감\s*기술과\s*친환경\s*설계|(?:개선과제|이행).*실행.*촉진"
)
SPECIFIC_RESULT = r"(?:19|20)\d{2}\s*년|\d+\s*(?:회|건|개|톤|%)|문헌조사|현장실사|추진반.*구성"
VAGUE_BOUNDARY = r"^(?:유관|관련)\s*부서(?:의|에서|를|에|\s|$)"
OBSERVED_YEAR = r"(?:19|20)\d{2}년(?:에는|에|도에는|도에)"
FUTURE = r"(?:19|20)\d{2}\s*년\s*까지|향후|미래|전망|예측|시나리오"
FORECAST = (
    r"예상\s*(?:매출|재무|비용)|(?:재무|경제적)\s*영향.*(?:예상|전망)|"
    r"(?:전망|예측|시나리오).*(?:매출|재무|비용)"
)
SEMANTIC_POLICY = BASE | dict(
    profile="tagging-semantic-admission-q1-v1",
    source_sections=["4.2", "4.4", "4.5", "4.6"],
    guidance_sha256=canonical_hash(GUIDANCE),
    generic_plan=GENERIC_PLAN,
    named_plan=NAMED_PLAN,
    generic_result=GENERIC_RESULT,
    specific_result=SPECIFIC_RESULT,
    vague_boundary=VAGUE_BOUNDARY,
    observed_year=OBSERVED_YEAR,
    future=FUTURE,
    forecast=FORECAST,
    category="verified-local-forecast-candidate; retag-and-GAP-001-hold; no-legal-effect",
)


def validate_policy(policy):
    if policy != SEMANTIC_POLICY:
        raise ValueError("Q1_STRUCTURAL_POLICY_MISMATCH")


def guard(element):
    if element.state != "present":
        return element
    quotes = [" ".join(r.quote.split()) for r in element.evidence_refs]
    reason = None
    if (
        element.element_id == "G6"
        and quotes
        and all(re.search(GENERIC_PLAN, q) and not re.search(NAMED_PLAN, q, re.I) for q in quotes)
    ):
        reason = "Q1_G6_NAMED_PLAN_REQUIRED"
    elif (
        element.element_id == "M4"
        and quotes
        and all(re.search(GENERIC_RESULT, q) and not re.search(SPECIFIC_RESULT, q) for q in quotes)
    ):
        reason = "Q1_M4_CONCRETE_RESULT_REQUIRED"
    elif (
        element.element_id == "M2" and quotes and all(re.search(VAGUE_BOUNDARY, q) for q in quotes)
    ):
        reason = "Q1_M2_BOUNDARY_UNSPECIFIED"
    return (
        replace(
            element, state="unknown", normalized_value=None, credited_from=None, reason_code=reason
        )
        if reason
        else element
    )


def forecast_quote(quote):
    text = " ".join(quote.split())
    return bool(re.search(FUTURE, text) and re.search(FORECAST, text))


def forecast_evidence(data, graph):
    from proofops.application.evidence.span_citations import verify_source_ref
    from proofops.domain.values import SourceRef

    if graph is None or (data["tenant_id"], data["document_version_id"]) != (
        graph.tenant_id,
        graph.document_version_id,
    ):
        return []
    refs = [SourceRef(**r) for r in data["claim_source_refs"]]
    if not refs or not any(forecast_quote(r.quote) for r in refs):
        return []
    checked = [verify_source_ref(r, graph, tenant_id=graph.tenant_id) for r in refs]
    return (
        [asdict(r) for r in checked]
        if all(r.verification_state == "verified" for r in checked)
        else []
    )


def observed_period(value):
    """Accept only a literal annual observation with a Korean case suffix."""
    return bool(re.fullmatch(OBSERVED_YEAR, value.strip()))


def guidance_target(quote):
    return bool(
        forecast_quote(quote)
        or re.search(
            r"목표로\s*설정|관련\s*활동|포트폴리오|활동.*추진|친환경\s*설계|실행.*촉진|"
            r"문헌조사|현장실사|탄소비용|정기\s*보고체계|\d+\s*만\s*톤|사업장.*중.*인증|공조|냉수펌프",
            quote,
        )
    )


def preliminary(schema, *, quote=None):
    from proofops.application.tagging.k9_contract import preliminary as old

    return old(schema, quote=quote) + (
        CLASSIFICATION_GUIDANCE if quote is None or guidance_target(quote) else ""
    )


def element_guidance(quote):
    """Only relevant clauses consume the unchanged 16KiB provider limit."""
    parts = []
    if re.search(r"목표로\s*설정", quote):
        parts.append(YEAR_GUIDANCE)
    if re.search(r"\d+\s*만\s*톤|사업장.*중.*인증", quote, re.S):
        parts.append(QUANTITY_GUIDANCE)
    if re.search(r"탄소비용|문헌조사|현장실사", quote):
        parts.append(PROCESS_GUIDANCE)
    if re.search(r"정기\s*보고체계", quote):
        parts.append(GOVERNANCE_GUIDANCE)
    if re.search(r"관련\s*활동|포트폴리오|활동.*추진|친환경\s*설계|실행.*촉진", quote):
        parts.append(NEGATIVE_GUIDANCE)
    return "".join(parts)
