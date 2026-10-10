# DEC-23 — 활동 적용범위 정책 V2

2026-10-10 사용자 승인: `outputs/agent-results/R108-redesign/lab/autonomy/DECISION-LOG.md` DEC-23(14:01).
원문 v2.0 §4.5 M2(적용범위), §6 2-4(558–562행, 적용범위·산정방법·외부검증 문서 전역 인정)를
활동 범위와 보고서 작성 범위를 구별하는 것으로 해석한다. 원문 파일과 해시는 변경하지 않는다.

`ACTIVITY_SCOPE_V2`는 현대 p144 ‘보고 범위 및 경계’, SK p2 ‘보고 경계’ 등 보고서 전체 작성
범위·경계 문장을 개별 활동의 M2 근거로 인정하지 않는다. 같은 문장·문단의 ‘전사’, 대상 공장
전체 등 활동 자체의 범위는 기존 원문 인용·귀속 가드를 통과하면 인정한다. 다른 쪽의 같은 조직
활동 범위도 기존 명시적 역할·동일성 검증을 요구하며, 임의 링크나 새 GAP-004 승인을 만들지 않는다.
P3 산정방법, M3 외부검증, P4 보증 연결과 숫자·목표연도의 직접 확인 계약은 변경하지 않는다.

새 설정은 `config/rubric/elements.yaml` M2의 `binding_policy: ACTIVITY_SCOPE_V2`에 고정한다.
이는 사다리 버전과 독립된 새 귀속 정책 버전이며 해당 필드가 규칙팩 내용 SHA-256에 포함된다.
등록은 반드시 새 rule_pack_id/hash로 하며 기존 ID, 활성화 승인, 과거 snapshot을 재사용하지 않는다.
무료 재생의 파생 pack은 별도 `*-dec23-scope-v2` 버전/새 ID/hash를 기록하고 draft로 유지한다.
정책 필드가 없는 과거 pack은 `REPORT_SCOPE_V1`과 원래 체크를 보존한다. 미지원 정책은 거부한다.
V1→V2 재채점은 `ELEMENT_MEANING_CHANGED:M2`로 RETAG_REQUIRED이며 태깅을 소급 재해석하지 않는다.

태깅: 새 V2 보고서 범위 후보는 unknown과 `REPORT_WIDE_SCOPE_NOT_ACTIVITY_SCOPE`를 기록한다.
리뷰: 잘못된 present 요청은 같은 코드로 거부하고 기존 unknown/revision을 보존한다(If-Match 유지).
검색 화면: 새 표시 artifact의 engine_state는 unknown, reason/search.reason_code는 위 코드이며
undetermined_reason은 기존 `linkage_unclear` 값이다. 공개 DTO 필드·enum·DB column migration은 없다.
원문 ref와 raw vote, 테넌트/문서/페이지/좌표, replica 및 모델·프롬프트·규칙 해시를 보존한다.
문자 탐지는 거절 가드이며 의미적 활동 귀속의 승인기가 아니다. 원문 block/section_parent 조상을
검사하되 같은 페이지의 무관한 제목만으로 활동 문장을 거부하지 않는다. 미정·충돌은 absent로 바꾸지 않는다.

롤백: 새 V2 pack의 신규 배정을 중단하고 검증된 과거 pack을 새 실행에 배정한다. V2 reader는
이미 생성된 V2 artifact의 재생에 남겨 둔다. 정책 필드를 삭제해 동일 ID/hash에 덮어쓰거나 과거
보고서를 수정하지 않는다. 본 작업은 활성화·push·배포·AWS·실제 모델 호출을 수행하지 않는다.

검증: `tests/acceptance/test_activity_scope_policy.py`, 기존 V1 report-level receipt/SQLite 재생,
`python scripts/replay_activity_scope.py --lab-root <AD>/lab --output <AD>/lab/rules/MR1`.
45행의 반납 판정/메모 기준 재생은 AI 초안·부분 도메인 판정의 제한을 유지하며 사람 전수 gold,
독립 검수 또는 production PDF→판정 정확도를 주장하지 않는다.
