"""Compound baseline citation guidance; no recovered facts or changed admission."""

from proofops.application.tagging.k7_wire import POLICY_K10
from proofops.domain.provenance import canonical_hash

GUIDANCE_V1 = (
    "\nK11 G3: 기준연도와 기준값은 같은 주장 또는 직접 연결된 동일 표에서 모두 인용한다. "
    "두 값이 하나의 연속 원문 구절에 있으면 그 기준 구절 전체를 인용하고 "
    "normalized_value를 그 인용과 정확히 같게 쓴다. 원문에 있는 연도·값 구절은 "
    "합성 문자열이 아니다. 서로 떨어져 있으면 각각 인용하고 normalized_value는 "
    "선택한 기준값 인용과 정확히 같게 둔다. present G3에 null 값을 반환하지 않는다. "
    "연도만, 값만, 다른 주장/문서 전역 값은 G3 unknown이다. 목표수치와 기준값은 "
    "역할이 다르지만 원문이 기준 수준 유지를 목표로 명시하면 동일 값이 두 역할을 "
    "가질 수 있다. G4 범위·조직경계, G5 진척은 별도 근거가 필요하다. "
    "원문에 없는 두 값을 연결하거나 과거 태깅으로 present를 채우지 않는다."
)
WIRE_V1_POLICY = POLICY_K10 | dict(
    profile="bounded-interpretation-k11-v1",
    baseline_guidance_sha256=canonical_hash(GUIDANCE_V1),
    renderer="compact-common-original-track-tail-k11-v1",
)

GUIDANCE = (
    "\nK11 G3: 기준연도와 기준값은 같은 주장 또는 직접 연결된 동일 표에서 "
    "모두 인용한다. 인용 경계를 일관되게 유지하기 위해 같은 괄호 안에 있어도 연도와 "
    "기준값(단위 포함)을 각각 짧은 원문 인용으로 선택한다. G3 normalized_value는 반드시 "
    "기준값 인용과 정확히 같게 쓴다. 연도 인용, 전체 기준 구절, 합성 문자열 또는 null을 "
    "normalized_value로 쓰지 않는다. 기준연도·값의 역할이 모호하면 unknown이다. "
    "연도만, 값만, 다른 주장/문서 전역 값은 G3 unknown이다. 원문이 기준 수준 유지를 "
    "목표로 명시하면 동일 값이 G2 목표수치와 G3 기준값 역할을 가질 수 있다. 이 경우 "
    "G2도 값(단위 포함)을 별도 인용하고 normalized_value를 그 값 인용과 같게 둔다; "
    "수준 유지의 문장은 추가 문맥 인용이다. G4 범위·조직경계와 G5 진척은 별도 근거가 "
    "필요하다. 원문에 없는 값을 만들거나 과거 태깅으로 present를 채우지 않는다."
)
WIRE_POLICY = WIRE_V1_POLICY | dict(
    profile="bounded-interpretation-k11-v2",
    baseline_guidance_sha256=canonical_hash(GUIDANCE),
    renderer="compact-common-original-track-tail-k11-v2",
)


def elements(schema, classification, *, policy=WIRE_POLICY, quality_policy=None):
    from proofops.application.tagging.k10_contract import elements as previous

    if policy not in (WIRE_V1_POLICY, WIRE_POLICY):
        raise ValueError("K11_WIRE_POLICY_MISMATCH")
    rendered = previous(schema, classification, quality_policy=quality_policy)
    guidance = GUIDANCE_V1 if policy == WIRE_V1_POLICY else GUIDANCE
    return rendered + (guidance if classification["track"] == "goal" else "")
