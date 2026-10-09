# PT1 무인 분석 계약

사용자 결정 2026-10-09. 새 실행의 `pipeline_profile=unattended-v1`만 활성화한다.
기본 프로필과 이전 checkpoint, 태깅·판정 revision, 보고서는 재작성하지 않는다.
런처: `--pipeline-profile unattended-v1`; finals_demo: `PROOFOPS_PIPELINE_PROFILE=unattended-v1`.
공개 API: `X-Pipeline-Profile: unattended-v1`; 웹의 무인 분석 체크박스는 기본 OFF.

원문 미검증도 추적 가능한 literal 후보로 분류·관계·요소 태깅에 전달한다.
테넌트/원본/페이지/좌표/문자 일치 검사는 유지하며 검증 상태를 승격하지 않는다.
`source_status={status:verified|unverified,reason,display}`를 checkpoint와 읽기 API에 보존한다.
미검증 표시는 `원문 확인 필요`다. 검증되지 않은 dimension은 null, 요소는 unknown이다.

`provisional_grade`는 순수 Python 규칙엔진 결과의 읽기 전용 별도 필드다.
2/3 동일 상태·값·binding·scope의 검증된 present만 사용한다. unknown/conflict는 보존한다.
모델 absent/N/A는 검색 전수성·적용성 권한이 없어 unknown으로 남는다.
등급이 확정되지 않을 때 엔진이 산출한 reachable floor만 하한으로 표시하며 열린 요소와 범위를 함께 보존한다.
미정 규칙·세이프하버 매핑·분류 미합의는 임의 E등급을 만들지 않고 산출 보류로 표시한다.
모든 잠정 요소에 투표 수/replica/검증 인용을 기록하고 `잠정·미확정`을 표시한다.
확정 `decision`과 `review_inputs`는 null이며 provisional 입력을 검토 revision으로 발행하지 않는다.

주장별 예외는 stage/reason으로 격리한다. lease·권한·테넌트/정본 실패는 우회하지 않는다.
예산 거절 후 남은 주장은 `budget_unanalyzed`/`예산 상한으로 미분석`으로 기록한다.
run/stage completed는 처리 종료이며 coverage.complete=false, 확정등급 0은 그대로 유지한다.
추출 제공자 장애는 해당 원문 구역을 failed/unknown으로 남기며 다른 구역의 처리 결과를 발행한다.

API는 source_status/provisional_grade/pipeline_stage의 optional 추가 필드와 ReviewProjection을 사용한다.
DB column migration 없음: 기존 불변 opaque checkpoint에 profile을 pin한다. 구버전 실행은 필드 없이 유지한다.
롤백은 새 profile 생성 중단 후 해당 checkpoint reader를 유지하거나 이전 reader에 배정하지 않는 방식이다.
이미 저장된 잠정 결과를 확정 revision으로 변환하거나 기존 결과에 덮어쓰지 않는다.
