# C3 — R8 한정 활성 발행 계약

`management-direct-certification-c3-v1`은 DEC-43/R8을 이행하는 명시 선택 profile이다.
C2의 코드·정책 해시·비활성 reader와 이전 receipt는 보존한다. C3는 같은 독립
3개 원시 receipt에 C2 matcher와 추가 인증/범위/기간/충돌 가드를 적용한다.
공개 확정은 R8의 LG 원본·테넌트·claim·packet·graph·승인 rulepack 해시에 한정한다.
모의 receipt는 공개하지 않으며 다른 입력은 의미 검토 전 후보로만 남긴다.

`LocalC3Publication`은 실제 원문·선택 스팬 receipt·parser candidate artifact와 새
run snapshot을 저장하고 기존 SQLite review/tag/decision revision store를 사용한다.
load는 원본 선택 스팬을 재검증하고 receipt 및 Python 판정을 재계산한다.
중단 후 같은 snapshot 재개는 같은 revision을 반환하고 다른 입력은 충돌로 거부한다.
기존 ReviewService의 권한·If-Match·원문/귀속 검증을 거친 사람 태깅 수정은 새
revision을 만든다. 기존 태그·판정·수출 파일은 덮어쓰지 않는다.

공개 API/DB column migration은 없다. 기존 `r108-hosted-result-v1`의 선택 필드
`confirmation_source=auto_direct_certification_c3_v1`, `confirmation_policy_sha256`,
`confirmation_basis`, `confirmation_display`를 C3 결과에서 제공한다. API snapshot은
원본 PDF와 evidence/manifest의 해시를 포함한다. 구 reader는 새 profile을 지원하지
않으므로 rollback은 새 C3 생성 중단과 C3 reader 유지이며 과거 C2에는 영향이 없다.
일반 unattended profile과 production 설정은 자동 변경하지 않는다.

화면의 E3는 프로젝트 루브릭상 공시 입증요소 충족을 뜻한다. 적용범위 15/17과
보고서 문맥 2025를 보존하고 인증 유효기간은 미기재로 표시한다. 실제 성과·법적
적합성·현재 인증 유효성을 보장하지 않는다. 선택 필드 `lower_bound_display`는
서버가 제공한 보조 문구만 표시하고 확정 집계·라벨로 사용하지 않는다. 구 결과에서
선택 필드가 없으면 화면은 기존과 동일하다.

C3의 `source_ref_page_space=original`은 원본 physical page를 그대로 보존한다.
테넌트·문서·receipt·원문 파일을 재검증한 뒤 같은 p36의 검증된 좌표만 렌더한다.
A3 미리보기는 C3에서만 DPI를 낮춰 기존 2,000px/400만 픽셀/timeout/메모리 한도를
유지한다. 원문 판독·태깅·근거 권한은 달라지지 않고 기본 144 DPI reader는 유지한다.

평가: `python -m evaluation.c3_activation requests|api|assess`.
실호출은 명시 `api` 단계만이며 기존 R108 누적 fence와 더 엄격한 USD0.50 한도를
사용한다(작업 승인 상한 USD0.60). 키는 출력하지 않는다.

## I11 / v12 한정 채택

v12의 `direct_certification_policy`는 기존 C3 policy/hash를 그대로 채택한다.
`certification_profile_for`는 R8의 tenant/original/claim/claim hash/packet/graph/rulepack
모든 pin이 일치하는 경우에만 C3를 선택한다. 선택 함수는 검증된 receipt·원문 replay와
Python decided·If-Match·불변 revision을 대체하지 않는다. 임의 보고서의 일반 자동
확정은 C4/R9에 의해 기본 비활성이다. 과거 v11·K10·C2/C3/C4 reader는 보존한다.
API/DB migration과 운영 설정 변경은 없으며 새 기본값의 rollback은 기존 reader를
유지한 채 신규 실행의 정책 배정만 되돌린다. LG p24 G3는 원문에 2019년과 951만
tCO₂e가 함께 있지만 저장 태깅이 미해결이므로 재추출 전 unknown/보류를 유지한다.
