# C4 일반 직접 인증 관리체계 경로

C4 작업 승인으로 추가한 `management-direct-certification-c4-v1`은 기업/원문/claim
allowlist 없이 같은 원본 문단에서 ISO 14001 환경경영시스템, ISO 50001 에너지경영시스템,
ISO 45001 안전보건경영시스템의 직접 인증 보유와 명시된 적용범위를 찾는다.
이 명칭 registry 밖의 인증/체계는 추측하지 않으며 기존 검토 경로에 남긴다.
후보 탐색은 원문 스팬을 제안할 뿐, 출처 승인이나 등급을 산출하지 않는다.

`adapters.local.c4_processing.process_report`가 보고서 그래프 전체를 순회하여 후보별로
원본 glyph/좌표/픽셀 검증 → 새 동결 packet → 별도 replica 요청 세 개 → 각각의
인용/귀속 matcher → 3/3 일치 → 기존 순수 Python 규칙 → 불변 발행을 수행한다.
실제 transport는 원장과 원시 응답 sidecar를 대조한다. 같은 요청의 재개는 저장된
receipt를 재검증하며 서로 다른 replica를 합치지 않는다. 모의 원문/모의 응답은
공개 확정을 얻지 못한다. 지급 권한과 예약 fence는 transport의 책임이다.

M1–M4의 근거와 activity/boundary는 해당 후보 스팬 안에 있어야 한다. M2는 각 회차의
완전한 적용범위 인용으로 판독하며 짧은 범위 hint만으로 채우지 않는다. 다른 사업장·기간,
GRI 안내·보증의견 합집합·제품/교육/정책 개정 전용, 부합/미취득/계획/철회/취소,
범위 확대·유효기간 추정·본문 상충·미해결 조건부 요소는 발행하지 않는다.
각주가 붙은 범위는 별도의 검토를 요구한다. unknown/conflict는 absent로 바꾸지 않는다.
기간은 본문 명시 연도 또는 같은 쪽의 해당 보고서 제목 문맥으로만 기록한다.
인증 유효기간을 확인하지 않은 출력은 항상 ‘인증 유효기간: 미기재’를 표시한다.

`LocalC4Publication`은 발행 전과 reload 시 원본 및 선택 스팬 receipt를 재검증한다.
기존 ReviewService/SQLite의 tenant·If-Match·새 tag/decision revision·export 불변성을
사용한다. API/DB column migration과 새 의존성은 없다. 새 profile reader dispatch만
추가한다. C2/C3의 코드, 정책 hash, receipt와 reader 의미는 바꾸지 않는다.
롤백은 새 C4 생성 중단과 C4 reader/불변 산출물 유지다. 지원하지 않는 구 reader로
C4를 읽거나 기존 결과를 재채점한 것으로 가장하지 않는다.

C3 웹 `5d9ae05`는 그대로 사용한다. 기존 UI discriminator
`confirmation_source=auto_direct_certification_c3_v1`을 직접 인증 표시 유형으로 유지하고,
실제 구현 버전은 새 C4 `confirmation_policy_sha256`과 receipt의 profile로 식별한다.
`confirmation_basis`/`confirmation_display`는 해당 원문의 체계·인증·범위·페이지·기간에서
자동 생성한다. 새 C4 profile이 C3의 특정 claim 승인을 이용했다는 뜻은 아니다.
기존 확정 0 결과는 수정하지 않으며, 새 보고서 실행에서 새 원자 후보 revision을 만든다.
production 설정, 클라우드 배포, C3 웹 소스는 이 작업에서 변경하지 않는다.

로컬 실측: `python -m evaluation.c4_general prepare` 및 `api`.
임의 입력: `python -m evaluation.c4_general report --graph graph.json --source original.pdf
--rulepack approved-rulepack.json --output /absolute/new-output --run-id UUID`.
그래프 JSON은 tenant/원본 candidate/issue를 보존한 canonical snapshot이고 규칙집은
기존 승인 snapshot이어야 한다. 이 명령도 기존 R108 누적 fence 및 C4 USD0.50 한도
(작업 승인 USD0.80보다 엄격)를 사용한다. 키와 runtime 설정은 출력/수정하지 않는다.
음성 결과는 원문 기반 변형 fixture 검사이며 실모델 음성 정확도 또는 독립 gold가 아니다.

## I11 / R9 기본 비활성

v12 `finals-20261013-v12`는 C4 일반 발행을 기본 비활성으로 통합한다.
같은 문단 후속 문장의 취소·부정·제외 누락은 R9에서 확인했으며 별도 C5 수정 대상이다.
기존 C4 policy/reader/receipt bytes는 과거 재생용으로 유지한다. 음성 12유형 변형
fixture의 차단 결과는 이 문맥 누락에 대한 일반 활성 승인 근거가 아니다.
v12는 R8의 정확한 C3 입력 identity만 선택하며 새로운 회사/claim/packet에는 확대하지 않는다.
