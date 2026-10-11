# J3 선택된 인용의 명시 경계 분리

`finals-unattended-j3-v1`은 W9에서 파생한 명시적인 opt-in 분석 정책이다.
`finals-unattended-v2`의 기본값·해시·과거 실행과 모든 frozen source reader를 유지한다.
새 실행은 `extraction_j3=true`와 source-ID/W9 옵션을 동결하며 별도의 분석·추출 규칙
해시를 가진다. 추출 시스템 프롬프트와 후보 선택 규칙은 W9와 같다. 요청에는 새
`selected_span_policy_sha256`을 포함하므로 같은 원문·선택 ID여도 receipt가 충돌하지 않는다.

LLM이 이미 선택한 paragraph의 명시 `•` 글머리만 원문 그대로 분리한다. 단순 줄바꿈,
Scope 1/2, 수단 나열, 접속사에서는 분리하지 않는다. 불완전한 항목이 있거나 분리된
인용이 기존 token/인용 검증을 통과하지 못하면 선택된 부모 인용 전체를 유지한다.
표에서는 선택된 일반 행 안의 완전한 origin cell 경계만 사용하며 파서 grid의
불일치를 거부한다. 시계열 PB1 관측은 값·단위·연도가 있는 행 그대로 유지한다.
선택되지 않은 원문, 인접 셀 숫자·연도·주어를 합성하지 않는다.

`result.json`의 `j3_refinements`는 부모와 자식의 원문 offset을 보존한다. 재생 시 raw
선택 응답에서 이를 다시 계산하고 저장된 인용과 부모 관계의 위조를 모두 거부한다.
새 자식은 각각 새 원문 검증과 태깅을 거쳐야 한다. 부모의 verified/present, replica,
등급·revision을 자식에게 복사하지 않는다. unknown/conflict/unreadable 처리는 그대로다.

공개 요청/응답 DTO와 DB column 변경은 없다. 내부 분석/pipeline profile allowlist에
선택값 하나를 추가했으며 기존 opaque 설정·snapshot에 정책과 옵션을 저장한다.
별도 DB migration은 없다. 신규 정책 생성 중단으로 롤백하되 이미 만든 J3 snapshot의
reader와 이력을 유지해야 한다. 구버전 reader는 미지원 정책을 명시적으로 거부한다.
I1은 필요할 때 이 커밋을 가져가 opt-in을 선택한다. 기본 배포 정책은 변경하지 않는다.

같은 DL3 AI draft 문자열/1:1 proxy의 무료 저장 선택 재생 결과는
`outputs/agent-results/R108-redesign/lab/fix/J3/accepted-replay/scores.json`에 있다.
59/156→71/156 재현, 59/61→71/74 정밀이며 새 태깅·등급 E2E 측정이 아니다.
더 넓은 셀 후보를 만든 3쪽의 제한적 추출 실험은 정밀 84/89(94.38%)로 기각했고,
해당 후보 구성·프롬프트는 제품에 적용하지 않는다. 비용·실패 시도와 원시 응답은 보존한다.
