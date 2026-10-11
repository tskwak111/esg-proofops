# J7 선택된 문장·글머리 내부의 독립 주장 분리

`finals-unattended-j7-v1`은 J3 위의 명시적 opt-in이다. 기존 J3/W9 정책,
시스템 프롬프트, 후보 선택, frozen source reader와 규칙엔진을 유지한다.
`extraction_j7=true`는 `extraction_j3`, W9/PB1 및 source-ID를 필요로 한다.
새 분석·추출 규칙 해시와 요청의 `selected_span_policy_sha256`이 이전 receipt와
격리한다. 기존 실행에 J7을 추가하는 resume은 거부한다.

LLM이 선택한 범위에서 J3의 글머리/완전한 셀 분리를 먼저 적용한다. paragraph는
독립적인 동작 서술어 뒤의 병렬 절을 추가로 분리한다. 총괄과 상세 업무,
같은 전환의 범위·연도 나열, 지시어로만 연결된 수단·결과는 유지한다.
명시적인 목표 시점 비교는 자체 수치가 있는 별도 주장으로 보존한다.
Scope·숫자·목표연도, 인용부호·괄호 내부, 단순 줄바꿈에서는 분리하지 않는다.
한 자식이라도 불완전하거나 기존 quote/offset/token 검증에 실패하면 부모를 유지한다.
64개 초과 확대는 원래 선택 전체로 되돌리며 결과를 잘라내지 않는다.

반납안내 §5의 수단+수치 효과 예상은 원문에 독립 절 경계가 있는 경우 분리한다.
수치 없는 기대는 수단에 포함한다. 목표·수단 트랙과 G/P/M 요소는 각 자식의
새 태깅에서 결정하며, 설치연도를 효과 예상의 목표연도로 복사하지 않는다.
조건절은 원문 그대로 해당 주장과 함께 둔다. 앞쪽 조건이 두 절 모두를 지배하면
부모를 유지한다. 공유 조건을 합성·복사하거나 자식에서 삭제하지 않는다.
선택되지 않은 표의 수단 제목을 효과 인용에 붙이는 작업은 이 정책 범위가 아니다.
의지 표현을 제거하는 필터를 추가하지 않는다.

자식은 동일 문서버전/parse manifest/원문 block의 실제 code-point offset과 bbox를
보존한다. `j7_refinements`의 부모·자식 offset은 raw 응답에서 다시 계산하며,
저장 인용·ancestry 위조는 거부한다. 부모의 verified/present, 태깅, track, replica,
등급·revision을 상속하지 않는다. 새 source 검증과 태깅 전에는 보류한다.
unknown/conflict/unreadable을 absent로 바꾸는 동작은 없다.

API profile allowlist와 내부 opaque settings/snapshot의 opt-in만 추가한다.
공개 DTO·DB column migration은 없고 구버전 reader는 새 정책을 거부한다.
롤백은 신규 J7 실행 생성 중단으로 한다. 생성된 J7 이력·receipt와 reader는 보존한다.
저장 선택 재생의 DL3 문자/1:1 AI draft proxy와 실제 새 모델 E2E 정확도를 구분한다.
