"""Budget interpretation only; immutable sources and evidence IDs stay server-side."""

import json
from copy import deepcopy

from proofops.application.tagging.k10_contract import GUIDANCE as K10_GUIDANCE
from proofops.domain.provenance import canonical_hash

POLICY_V1 = dict(
    profile="bounded-interpretation-k7-v1",
    priority="parent-sentence-or-origin-cell > column-header > other",
    limit="provider-request-body-16384-bytes-including-JSON-escaping",
    truncation="literal-codepoint-prefix; explicit-omission-record; interpretation-only",
    fallback="atomic-without-context; never-remove-evidence-or-change-source-authority",
    citations="evidence-catalog-ID-enum-only; interpretation-exposes-no-source-IDs",
)
POLICY = POLICY_V1 | dict(
    profile="bounded-interpretation-k7-v2",
    priority_source="checked-focal-block-kind; order-changes-only-when-truncating",
)
INSTRUCTIONS = (
    "\nInterpretation context is not citable evidence. Only IDs in evidence_catalog "
    "and element_evidence_ids are allowed in evidence_refs. Never cite a source UUID "
    "or context. Every present element requires a non-empty evidence_refs array with "
    "an allowed ID and exact catalog substring; otherwise return unknown, [] and null. "
    "interpretation_budget records omitted context: do not infer missing conditions, "
    "scope, numbers or absence from a truncated sentence."
)


MANAGEMENT_GUIDANCE = (
    "\nM1 현재 운영: 이사회·위원회가 안건을 검토·승인/점검하는 절차는 구체적 운영이다. "
    "검토 예정/검토하겠다 의향만은 unknown. M4 날짜 있는 조직 구성은 구체적 이행이며 "
    "감축량 달성 실적을 뜻하지 않는다. 가상 대조(원문 근거로 인용 금지): "
    "'가상기업 이사회는 환경투자 안건을 검토·승인합니다'는 M1 운영; "
    "'가상기업은 도입을 검토할 예정'은 M1 unknown. "
    "'가상기업은 2023년 2월 CCS 추진반을 구성하여 사업을 추진한다'는 M4 구성 사실; "
    "'가상기업은 CCS를 추진할 계획'만은 M4 unknown. "
    "M2의 적용 조직·사업장 범위는 별도 근거가 필요하다. 그룹이라는 추진 주체나 감축 "
    "목적만으로 범위를 채우지 않는다. G4는 Scope와 조직경계 모두 필요하며 "
    "공장명만으로 Scope를 추론하지 않는다. 원문 인용·귀속 검증은 그대로 적용한다."
)
POLICY_K8 = POLICY | dict(
    profile="bounded-interpretation-k8-v1",
    management_guidance_sha256=canonical_hash(MANAGEMENT_GUIDANCE),
)


MANAGEMENT_GUIDANCE_V2 = MANAGEMENT_GUIDANCE + (
    " M4 조직 구성의 인용은 주체·날짜·완료 행동을 포함한 해당 atomic_quote 원문 문장 "
    "전체로 한다. 주체가 빠진 구성 구절만 인용하지 않는다. M2 범위는 별도로 판단한다."
)
POLICY_K8_V2 = POLICY | dict(
    profile="bounded-interpretation-k8-v2",
    management_guidance_sha256=canonical_hash(MANAGEMENT_GUIDANCE_V2),
)


NAMED_MEANS_GUIDANCE = (
    " M1 명명된 수단은 표준·설비 외에 원문에 명시된 기술 조치도 포함한다. "
    "건축물 단열 성능 개선은 단열이라는 수단을 명시하며, 막연한 에너지 효율 향상 의향과 다르다. "
    "가상 대조(원문 근거로 인용 금지): '가상기업은 건축물 단열 성능을 개선합니다'는 M1 수단; "
    "'가상기업은 효율 향상을 위해 노력할 예정입니다'만은 M1 unknown. M2/M4는 별도 근거가 필요하다."
)
POLICY_K8_V3 = POLICY_K8_V2 | dict(
    profile="bounded-interpretation-k8-v3",
    named_means_guidance_sha256=canonical_hash(NAMED_MEANS_GUIDANCE),
    named_means_trigger="management-atomic-quote-literal-insulation-only",
)


POLICY_K10 = POLICY_K8_V3 | dict(
    profile="bounded-interpretation-k10-v1",
    guidance_sha256=canonical_hash(K10_GUIDANCE),
    renderer="compact-common-original-track-tail-k10-v1",
)


def fit_context(system, user, check):
    """Check the exact provider body; deterministically share the projection across replicas."""
    value = deepcopy(user)
    data = value["untrusted_document_data"]
    policy = data.pop("tagging_wire_policy", POLICY)
    context = data.pop("sentence_context", None)
    if not context:
        wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        check(system, wire)
        return wire
    source_kind = context.pop("_source_kind", None)
    refs = context.get("source_refs", [])
    # K5 table contexts put column headers before the focal origin cell.
    if policy == POLICY_V1 and len(refs) > 1 and any(r.get("table_id") is not None for r in refs):
        refs = [refs[-1], *refs[:-1]]
    pieces = [
        (r["quote"], r.get("page_num"), r.get("verification_state", "candidate")) for r in refs
    ]
    if not pieces:
        pieces = [(context["text"], None, context.get("verification_state", "candidate"))]
    total = sum(len(p[0]) for p in pieces)
    budget = dict(
        policy_sha256=canonical_hash(policy),
        original_sha256=canonical_hash(context),
        original_chars=total,
        retained_chars=total,
        truncated=False,
        fallback=None,
    )
    data["interpretation_budget"] = budget

    def render(count):
        remaining, blocks = count, []
        ordered = (
            [pieces[-1], *pieces[:-1]]
            if (
                policy in (POLICY, POLICY_K8, POLICY_K8_V2)
                and source_kind == "table"
                and count < total
            )
            else pieces
        )
        for text, page, quality in ordered:
            take = min(remaining, len(text))
            if take:
                blocks.append(
                    dict(
                        text=text[:take],
                        page_num=page,
                        quality=quality,
                        rule_credit=False,
                        truncated=take < len(text),
                    )
                )
            remaining -= take
        budget.update(
            retained_chars=count,
            truncated=count < total,
            fallback="atomic_without_context" if not count else None,
        )
        if blocks:
            data["sentence_context"] = dict(blocks=blocks, rule_credit=False)
        else:
            data.pop("sentence_context", None)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def fits(count):
        wire = render(count)
        try:
            check(system, wire)
        except ValueError as error:
            if str(error) != "PROBE_REQUEST_TOO_LARGE":
                raise
            return False
        return True

    if fits(total):
        return render(total)
    if not fits(0):
        # The contextless request must still obey the provider's hard limit.
        check(system, render(0))
    low, high = 0, total
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return render(low)
