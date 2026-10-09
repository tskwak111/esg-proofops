# QI1 · 검증 후 태깅 프로필

`--analysis-profile finals-unattended-v2` 또는 같은 `--pipeline-profile` 값은
새 run에만 적용한다. `analyze_report`와 `PROOFOPS_ANALYSIS_PROFILE`에서도 선택한다.
기존 기본값, `unattended-v1`, INT2의 `finals-unattended-v1` 정책·출력은 유지한다.

전체 mixed-v1 parse graph 및 EV1 근거 span 검증을 먼저 고정하고, 추출한 주장에
claim-source-v3 검증 receipt를 생성한다. tag worker는 이 receipt를 재검증·재생한
주장과 graph를 받은 뒤 패킷을 동결한다. v2에서는 PageTagPipeline을 시작하거나
과거 `page_tag_pipeline` 결과를 재사용하지 않는다. 쪽별 병렬 추출과 최대 16개
주장별 HTTP 슬롯, 동일 패킷을 읽는 독립 replica 3회, 검증 receipt 중복 제거는 유지한다.
원문 검증에 실패한 주장도 무인 분류·태깅을 시도하며 ‘원문 확인 필요’를 표시한다.
retrieval은 EV1으로 검증된 근거 쪽의 정확한 span만 후보로 유지한다. 원문 미검증
주장은 binding 가드를 통과하지 못하므로 근거 후보 존재만으로 present가 되지 않는다.
사전분류 미합의·provider 실패·예산 정지는 그대로 보류하고 트랙을 만들어내지 않는다.

M1/M2/P2 정의는 원문 §4.4/4.5와 docs/28 범위 안에서 강화한다. 예시는 합성 문장이다.
`application/tagging/quality.py`의 `ELEMENT_DEFINITIONS_HASH`를 v2 분석 정책에 pin하고,
전체 rendered prompt 및 트랙별 prompt hash는 기존 settings/snapshot/replica에 저장한다.
요청 크기 실패 관찰 후 `element_wire=track-rulecards-v1`을 새 v2 정책에 pin했다.
전송할 때 요청한 트랙의 규칙 카드만 남기고 정의 예시·보호 지침·근거 패킷은 유지한다.
최초 v2 측정 정책은 `V2_INITIAL_POLICY`의 정확한 hash로만 계속 읽는다. 이 측정의
기존 checkpoint/receipt는 보존하며, 카드 축소 후 새 전체 실행은 반복하지 않는다.
최종 전송 정책의 실측 범위는 QA1 20개 새 태깅 replica와 무료 요청 크기 재생이다.
숫자·목표연도 전역 인정, absent 권한, unknown/conflict/unreadable, P4/P6의 결정론적
검증, 등급 사다리는 바꾸지 않는다. LLM은 태깅하고 Python 엔진만 등급을 계산한다.

`extraction_fragment_guard`는 source-ID 및 기존 선택형 linewrap join을 요구한다.
동일 paragraph에서 선택된 이전 줄이 `(YYYY.`로 끝나고 다음 선택 줄이 `NN),`로
시작하면 정확한 원문 범위로 연결한다. 이전 줄을 선택하지 않았거나 조건이 다르면
그 잔여 단편을 제외한다. `2) 내용` 같은 정상 목록은 유지한다. 선택하지 않은 문장을
합성하지 않는다. 새 추출 rule hash와 settings/manifest에만 pin하며 이전 receipt는 유지한다.

숫자 잠정 등급이 없고 전체 범위가 E0~E3이면 `display_type=hold`, `display=판정 보류`로
표시한다. 계산한 `grade_range` 자체는 보존한다. `hold_reasons`, `needed_evidence`는
원문 미검증·트랙 미합의·규칙 미정·현재 패킷의 인정 근거 없음과 트랙별 명시 사다리
요소를 설명한다. 미합의 때 관측 트랙, 관측값도 없을 때 조건부 세 트랙 목록을 표시한다.
좁은 범위와 숫자는 그대로다. 확정 `decision`, `review_inputs`와 기존 revision을 만들거나
바꾸지 않는다. 이 optional 표시 필드는 기존 opaque checkpoint/API 투영 경로에만 추가한다.
DB column/API enum migration 및 새 의존성은 없다. 구 reader에는 새 프로필을 배정하지 않는다.
Rollback은 신규 v2 배정을 끄고 기존 프로필로 새 실행을 생성하는 것이다. 이미 생성된
v2 receipt·revision·보고서와 provider/task/shared 원장·미정산 예약은 보존한다.

QI1 측정은 QA1의 동일 20개 저장 패킷·트랙을 새 replica로 태깅하고, MP1과 동일한 삼성·한전
원본·선택으로 각 1회 실행한다. task/group USD1과 기존 run/day/event/provider/누적 가드를
함께 적용한다. 응답이 불확실한 요청을 0으로 정산하거나 재전송하지 않는다. provider 장애로
부분 결과가 된 측정도 원래 결과로 남기며 추가 fresh 실행은 하지 않는다. 보고 비용은
정산된 사용액과 보수적으로 남은 미정산 예약을 구분한다. 자체 표본 검토는 모델 정확도나
독립 사람 검토가 아니다. AWS·hosted 배포는 이 작업의 범위 밖이다.
