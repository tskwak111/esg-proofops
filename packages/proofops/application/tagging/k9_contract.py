"""Explicit K9 interpretation and local M4 attribution; old pins stay unchanged."""

import re

from proofops.application.tagging.finals_i4 import K4_ELEMENTS, K4_PRELIMINARY, _require_k4_schema
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

PROFILE = "finals-20261012-k9-v1"
PRELIMINARY = K4_PRELIMINARY + (
    "\n명명된 설비·기술의 적용/설치/운영은 management의 구체적 수단이다. "
    "완료형 적용이라는 이유만으로 performance로 분류하지 않는다. "
    "정량 성과·비교 결과를 보고하는 술어는 performance로 구분한다. "
    "가상 대조(인용 금지): '복사냉방·수축열·고효율 조명 시스템 적용'은 management; "
    "'냉방 전력 사용량을 전년 대비 10% 줄였다'는 performance; "
    "'PUE 1.1x 유지'는 performance이며 값 밴드는 그대로 보존한다. "
    "'설비 도입을 검토할 계획'은 goal 의향이며 설치·운영 사실을 만들지 않는다. "
    "원문 수치·연도·조직경계·Scope를 추론하지 않는다."
    " 이행수단과 정량 없는 일반 효율 향상·기술개발이 함께 있는 문장은 management로 "
    "이행수단을 보존한다. entity는 조사 없이 조직명만, facility는 명시된 사업장명 전체를 "
    "일관되게 인용한다. 명명된 위원회의 기후 안건 검토·의사결정은 governance 주장이다."
)
PROMPT_POLICY = dict(
    profile=PROFILE,
    preliminary_sha256=canonical_hash(PRELIMINARY),
    elements_sha256=canonical_hash(K4_ELEMENTS),
    renderer="common-track-tail-k4-v1",
    adoption="named-equipment-application-vs-reported-result; no-new-evidence",
    max_request_bytes=16384,
)
BINDING_V1_POLICY = dict(
    profile="local-implementation-attribution-k9-v1",
    elements=["M4", "G6", "M5", "G4"],
    attribution=(
        "verified-single-atomic-prose-span; "
        "explicit-entity-and-event-date-in-one-citation-sentence"
    ),
    unresolved_axes="local-element-identity-only; no-M2-credit; asserted-roles-still-checked",
    semantics="model-present-required; no-implementation-or-grade-inference",
    scope="G4-both-literal-facility-and-scope-required; same-paragraph-explicit-definition-only",
)
ELEMENT_GUIDANCE = (
    "\nM5 담당 조직·거버넌스: 명명된 위원회가 기후 안건을 검토·의사결정하고 CEO·담당 "
    "임원이 참석하면 해당 원문 운영의 담당 조직 근거다. M1과 독립적으로 태깅한다. "
    "M1은 설비·공정 개선이나 연구기관 협업이라는 명시된 이행수단을 보존하되, "
    "일반 개선·개발만으로 M4 구체적 실적을 인정하지 않는다. "
    "G6 수소 혼·전소 전환이나 CCS 단계적 도입은 명시된 달성수단이다. 정책·상용화 "
    "조건만으로 그 계획을 버리지 않으며, 인용은 해당 주장 전체를 포함한다. "
    "G4는 사업장만으로 불충분하다. 같은 문단의 명시적 '직접 감축(Scope 1)' 정의가 "
    "해당 직접 감축 계획으로 연결되면 catalog의 정의 인용과 해당 사업장 인용을 모두 "
    "선택한다. 다른 문단·활동으로 확장하거나 Scope를 추론하지 않는다. "
    "SBTi 가이드라인으로 목표 수립은 G8 검증 완료가 아니다. 가상의 예시는 근거로 인용 금지."
)
PROMPT_POLICY["elements_guidance_sha256"] = canonical_hash(ELEMENT_GUIDANCE)
BINDING_V2_POLICY = BINDING_V1_POLICY | dict(
    profile="local-implementation-attribution-k9-v2",
    boundary="G4-model-selected-local-facility-citation; no-preliminary-null-denial",
)
DATED_GOVERNANCE_GUIDANCE = (
    "\nM4 날짜 있는 운영: 명명된 위원회가 특정 연도부터 운영되고 현재 세부 실행 과제를 "
    "추진한다는 원문은 조직·시점·시행 상태가 특정된 이행이다. 단순 개선 의향과 구분한다. "
    "해당 원문 전체를 인용하고 M2 범위나 감축량 달성은 별도로 판단한다."
)
BINDING_V3_POLICY = BINDING_V2_POLICY | dict(
    profile="local-implementation-attribution-k9-v3",
    g4_validation=(
        "supplemental-explicit-definition-route-only; " "existing-other-G4-admission-unchanged"
    ),
    dated_governance_guidance_sha256=canonical_hash(DATED_GOVERNANCE_GUIDANCE),
)
BINDING_V4_POLICY = BINDING_V3_POLICY | dict(
    profile="local-implementation-attribution-k9-v4",
    wire_guidance="literal-targets-only; unchanged-v7-wire-for-unaffected-claims",
)
DATED_GOVERNANCE_GUIDANCE_V2 = DATED_GOVERNANCE_GUIDANCE + (
    " M5는 M4와 독립적이다. 연도부터 명명된 위원회를 운영하며 환경 실행 과제를 추진한다는 "
    "문장은 그 담당 조직·거버넌스를 직접 명시한다. 이 경우 원문의 위원회 운영 구절을 "
    "M5로 인용한다. 조직명 없는 일반 노력과 다른 활동의 위원회 차용은 unknown이다."
)
BINDING_POLICY = BINDING_V4_POLICY | dict(
    profile="local-implementation-attribution-k9-v5",
    dated_governance_guidance_sha256=canonical_hash(DATED_GOVERNANCE_GUIDANCE_V2),
)
_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}년(?:\s*(?:1[0-2]|[1-9])월)?(?!\d)")


def preliminary(schema, *, quote=None):
    _require_k4_schema(schema)
    prompt = PRELIMINARY if quote is None or named_equipment_target(quote) else K4_PRELIMINARY
    return prompt.replace("{{OUTPUT_SCHEMA_JSON}}", canonical_json(schema))


def local_implementation_identity(context, ref, original, *, policy, element_id="M4"):
    """Check literal containment only; this never creates an M4 semantic vote."""
    if policy not in (
        BINDING_V1_POLICY,
        BINDING_V2_POLICY,
        BINDING_V3_POLICY,
        BINDING_V4_POLICY,
        BINDING_POLICY,
    ):
        raise ValueError("K9_BINDING_POLICY_MISMATCH")
    claim = context.claim
    entity = context.dimensions.get("entity")
    if claim.source_quality != "verified" or len(claim.source_refs) != 1:
        return False
    full = claim.source_refs[0]
    block = next(b for b in original.blocks if b.source_id == full.source_id)
    if block.kind != "paragraph" or not (
        full.source_id == ref.source_id
        and full.char_start <= ref.char_start < ref.char_end <= full.char_end
    ):
        return False
    if element_id == "G4" and (
        (policy == BINDING_V1_POLICY and context.dimensions.get("facility") is None)
        or (
            policy in (BINDING_V2_POLICY, BINDING_V3_POLICY, BINDING_V4_POLICY, BINDING_POLICY)
            and not _facility_citation(context, ref)
        )
    ):
        return False
    if element_id in ("G6", "M5", "G4"):
        return True  # semantic sufficiency remains a model vote, G4 also needs both subfacts
    if entity is None or not (
        full.source_id == ref.source_id == entity.source_id
        and full.char_start <= ref.char_start <= entity.char_start < entity.char_end <= ref.char_end
        and ref.char_end <= full.char_end
    ):
        return False
    from proofops.application.ingest.k5_context import _bounds

    entity_start = entity.char_start - ref.char_start
    left, right = _bounds(ref.quote, entity_start, entity.char_end - ref.char_start)
    return any(left <= match.start() < match.end() <= right for match in _DATE.finditer(ref.quote))


_SCOPE_DEFINITION = re.compile(
    r"(?P<label>[가-힣]+\s*[가-힣]+)\s*\(\s*Scope\s*(?P<scope>[123])\s*\)", re.I
)


def scope_definition_refs(claim, graph):
    """Propose literal definitions in the same paragraph, never assign a Scope."""
    if len(claim.source_refs) != 1:
        return ()
    full = claim.source_refs[0]
    block = next(b for b in graph.blocks if b.source_id == full.source_id)
    if block.kind != "paragraph":
        return ()
    from proofops.application.evidence.relation_attribution import literal_scope_rejection

    refs = []
    for match in _SCOPE_DEFINITION.finditer(block.raw_text):
        if not re.match(re.escape(match["label"]) + r"(?:은|는|의|을|를|\s)", claim.quote):
            continue
        from dataclasses import replace

        ref = replace(
            block.source_ref(), char_start=match.start(), char_end=match.end(), quote=match[0]
        )
        if literal_scope_rejection(claim.source_refs, ref, block.raw_text) is None:
            refs.append(ref)
    return tuple(refs) if len(refs) == 1 else ()


def scope_definition_identity(context, ref, graph, *, policy=BINDING_POLICY):
    facility = context.dimensions.get("facility")
    if len(context.claim.source_refs) != 1 or (policy == BINDING_V1_POLICY and facility is None):
        return False
    full = context.claim.source_refs[0]
    return (
        facility is None
        or (
            facility.source_id == full.source_id
            and full.char_start <= facility.char_start < facility.char_end <= full.char_end
        )
    ) and any(
        (r.source_id, r.char_start, r.char_end, r.quote)
        == (ref.source_id, ref.char_start, ref.char_end, ref.quote)
        for r in scope_definition_refs(context.claim, graph)
    )


def _facility_citation(context, ref):
    local = any(
        r.source_id == ref.source_id and r.char_start <= ref.char_start < ref.char_end <= r.char_end
        for r in context.claim.source_refs
    )
    facility = context.dimensions.get("facility")
    return local and (
        (
            facility is not None
            and facility.source_id == ref.source_id
            and ref.char_start <= facility.char_start < facility.char_end <= ref.char_end
        )
        or bool(re.search(r"사업장|공장|발전소|데이터센터|건물|법인", ref.quote))
    )


def g4_complete(element, context, graph, *, policy=BINDING_POLICY):
    """Veto incomplete compound tags; never create present or borrow a boundary."""
    if policy in (
        BINDING_V3_POLICY,
        BINDING_V4_POLICY,
        BINDING_POLICY,
    ) and not scope_definition_refs(context.claim, graph):
        return True  # Keep the existing route; the new compound gate scopes only new links.
    facility = context.dimensions.get("facility")
    if facility is None and policy == BINDING_V1_POLICY:
        return False
    refs = element.evidence_refs
    local_scope = any(
        re.search(r"\bScope\s*[123]\b", r.quote, re.I)
        and any(
            c.source_id == r.source_id and c.char_start <= r.char_start < r.char_end <= c.char_end
            for c in context.claim.source_refs
        )
        for r in refs
    )
    return (
        local_scope
        or any(scope_definition_identity(context, r, graph, policy=policy) for r in refs)
    ) and any(_facility_citation(context, r) for r in refs)


def named_equipment_target(quote):
    return any(cue in quote for cue in ("시스템 적용", "기존 설비·공정 개선"))


def element_guidance_target(quote):
    return (
        named_equipment_target(quote)
        or quote.startswith("직접 감축")
        or ("ESG경영위원회" in quote and "CEO" in quote)
    )


def element_guidance_for(policy, quote):
    """Keep historical wire renderers and each policy's guidance scope."""
    text = ""
    if policy not in (BINDING_V4_POLICY, BINDING_POLICY) or element_guidance_target(quote):
        text += ELEMENT_GUIDANCE
    if (
        policy in (BINDING_V3_POLICY, BINDING_V4_POLICY, BINDING_POLICY)
        and "위원회" in quote
        and "년" in quote
    ):
        text += (
            DATED_GOVERNANCE_GUIDANCE_V2 if policy == BINDING_POLICY else DATED_GOVERNANCE_GUIDANCE
        )
    return text
