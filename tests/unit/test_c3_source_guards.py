"""Verbatim LG p36 excerpts; invented withdrawal variants are identified separately."""

import pytest
from proofops.application.tagging.fact_assembly_c3 import safety_reasons

CONFORM = (
    "국제표준화기구의 ISO 14001(환경경영시스템)에 부합하는 체계를 기반으로, "
    "환경안전보건방침을 중심으로 환경영향 관리에 필요한 "
    "세부 규정과 지침을 마련해 적용하고 있습니다."
)
UNACQUIRED = (
    "미취득 사업장은 신규 설립 또는 인증 진행 중인 사업장으로, "
    "단계적으로 인증 범위를 확대하고 있습니다."
)
DIRECT = (
    "LG화학의 환경경영시스템(Environmental Management System, EMS)은 ISO 14001 인증을 통해 "
    "제3자 검증을 받고 있으며, 내부 감사를 통해 운영 적정성을 정기적으로 점검하고 있습니다."
)
SCOPE = (
    "ISO 14001 인증은 국내 전 생산 사업장에 적용되고 있으며, 글로벌 사업장의 경우 총 17개 "
    "생산 사업장 중 15개 사업장에서 인증을 완료하였습니다."
)


def raw(cert=DIRECT, scope=SCOPE):
    return {"elements": {"M3": {"evidence": {"quote": cert}}, "M2": {"evidence": {"quote": scope}}}}


@pytest.mark.parametrize("quote", [CONFORM, UNACQUIRED])
def test_actual_iso_nonpossession_prose_is_never_certification(quote):
    assert "CERTIFICATION_POSSESSION_UNRESOLVED" in safety_reasons(quote, raw(cert=quote))


@pytest.mark.parametrize("status", ["인증 예정", "인증 미취득", "인증 철회", "인증 취소"])
def test_explicit_counterfactual_status_cannot_override_real_positive(status):
    assert safety_reasons(DIRECT + " " + status, raw(cert=DIRECT + " " + status))


def test_report_context_is_not_validity_and_partial_scope_is_not_universal():
    assert "CERTIFICATION_VALIDITY_NOT_ESTABLISHED" in safety_reasons(
        DIRECT + " 인증 유효기간 2025", raw()
    )
    assert "PARTIAL_SCOPE_EXPANDED" in safety_reasons("글로벌 전 생산 사업장 " + DIRECT, raw())
    assert "CLAIM_CERTIFICATION_SCOPE_CONFLICT" in safety_reasons(DIRECT + UNACQUIRED, raw())
    assert not safety_reasons(DIRECT + SCOPE, raw())
