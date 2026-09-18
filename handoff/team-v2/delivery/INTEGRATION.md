# 서로 독립적으로 만든 코드를 합치는 방법

## 계약 교환 세 번
1. 개발 시작: schema1.1 + synthetic 예제 checksum을 교환. 두 사람이 validator 실행.
2. 첫 동작: A가 실제 packet 1개, B가 독립 결과 1개를 반환. source가 미확인이면 blocked가 올바름.
3. 기능 통합: B PR 검토→A의 bridge/storage/UI→전체 회귀. 마지막 날 처음 만나는 통합 금지.

## A가 구현할 연결 (아직 없는 신규 계약 제안)
- 저장: ReconciliationRevision = tenant_id/run_id/claim_id/decision_revision/package_hash,
  packet_hash/policy_hash/engine_version/reconciliation_revision/results/created_at/actor.
- 기존 Decision grade/label은 바꾸지 않는다. 연계 revision이 어떤 tag/decision snapshot에 대응하는지 기록.
- 추가 조회 endpoint 제안: GET /v1/runs/{run_id}/claims/{claim_id}/reconciliation.
  A가 OpenAPI/DTO/contract test를 먼저 확정한 뒤 구현한다. 이 URL은 현재 존재하는 API가 아니다.
- 결과: schema_version=1.1, execution_state, results[], revision, packet/policy hashes.
- 과거 run: 연계 없음 → not_run/feature_not_executed. 빈 results를 matched로 해석 금지.
- 권한: session tenant의 run/claim/document/package만 조회. 요청의 tenant_id를 신뢰하지 않음.
- 변경: 직접 grade/status 수정 endpoint 금지. 태그/근거 수정 → 새 packet → 새 연계 revision.
- 경합: 원본 수정의 If-Match와 run snapshot hash를 비교. 오래된 입력 결과는 최신 head로 발행하지 않음.

## DB와 migration
현재 schema/entity 계약을 먼저 읽고 별도 immutable artifact + 현재 head 참조로 표현 가능하면 재사용.
새 table/column이 필요하면 storage_entities와 migration을 함께 변경하고 구버전 read·rollback을 테스트.
기존 rows를 새 status 값으로 일괄 덮지 않는다. 읽기 스키마 버전으로 구분하고 미지원 버전은 명시 오류.
retry key는 tenant+claim+packet_hash+policy_hash+engine_version. 중복 요청은 같은 결과를 읽는다.

## 화면
기존 왼쪽 주장/원문·오른쪽 판정 구조를 재사용한다.
입증 등급과 연계 상태를 서로 다른 영역에 표시한다.
연계 행: C항목 / 상태 / SR 값 / 재무 값 / 설명 인용 / 양쪽 원문 링크 / 보류 사유.
needs_explanation은 “설명 보완 권장”, blocked는 “검토 대기”, not_run은 “미실행”.
원문 근거를 열 수 없으면 오류와 미확정으로 표시. 자동으로 위치를 추정해 하이라이트하지 않음.
원문 quote와 시스템 해설을 구분하고 회계 적정성 판단을 하지 않는 기능임을 표시한다.

## 테스트를 통과해야 합침
- 같은 G/P/M tags+rule에서 연계 on/off로 기존 grade/label 동일.
- 타 tenant/company/period/doc version source 거부.
- B 결과 packet_hash/policy_hash 위조 거부.
- 중복 요청·중간 실패·동시 수정 후 stale 결과 발행 거부.
- 수정 전 보고서 hash 보존, 새 report에 최신 확정 snapshot만 포함.
- query 실패·원문 읽기 실패·규칙 미정은 설명 부재로 바뀌지 않음.
- 기존 API client가 새 기능 미실행 run을 정상 조회.
- C5 입력과 금지된 출력 처리.
- 실제 브라우저에서 원문 확인→태그 수정→재판정→export 전체 재현.

## rollback
새 연계 실행을 off하고 기존 입증 경로는 유지한다. 신규 artifact는 삭제하지 않는다.
구버전 코드에 새 schema를 무리하게 읽히지 말고 지원 reader를 유지하거나 명시적으로 거부한다.
제품 배포 승인은 별도 범위. GitHub push 승인만으로 클라우드 배포를 수행하지 않는다.
