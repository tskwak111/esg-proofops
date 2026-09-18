# 소유권과 일괄 통합 계획

## 업무 분리
| 담당 | 소유 범위 | 완료 산출물 |
|---|---|---|
| A · 기존 개발자 | 기존 파서/주장/근거/태깅/규칙, API·워커·UI·DB·보고서, 공유 DTO·lock·CI | 낯선 보고서의 end-to-end 실행, 미확정 처리, 제품 통합 |
| B · 신규 개발자 | 아래 신규 경로만 | DART 증거 수집, C1/C3 순수 판정, CLI, 합성·실데이터 검증 |
| 도메인·데이터 | templates 제출본, 정답 원문 위치, 규칙 제안·경계 사례 | 검토된 주석과 규칙 결정표; 미정은 unresolved 유지 |

B 소유 경로:
- packages/proofops/domain/reconciliation/ (순수 DTO·판정)
- packages/proofops/application/reconciliation/ (use case·Ports·packet 검증)
- packages/proofops/adapters/dart/ (네트워크·원본 보존)
- evaluation/reconciliation_cli.py
- tests/reconciliation/, config/accounting/
- evidence/reconciliation/ (권리 확인된 최소 근거와 집계; 키·원본 덤프 금지)

A는 위 경로를 수정하지 않는다. B는 기존 domain/rules, SourceRef, api dto, frontend, lockfile을 수정하지 않는다.
새 dependency가 필요하면 B가 선택 이유·라이선스·버전과 변경안을 적고 A가 잠금 파일을 갱신한다.
공유 contract 파일은 A 소유. 변경 요청은 PR에서 입력/출력 예제·호환성 영향과 함께 제안한다.
새 마이크로서비스·별도 웹앱·별도 DB를 만들지 않는다.

## 병렬 작업
A: 현재 오류 기준선 → 각주·조건·귀속 병목 → 실제 태깅부터 보고서까지 연결 → 미사용 기업 평가.
B: DART 가용성 조사와 합성 packet → stage 가드 → C1 → C3 정책 게이트 → 독립 CLI.
데이터: 기업 단위 분할 → 소량 pilot 주석 → 불일치 조정 → 본 주석과 규칙 승인안.
C3 정책 승인이 늦어져도 B는 수집·정규화·보류·CLI를 완성한다. 값을 임의로 정하지 않는다.

## 일정 제안 (착수일 D0 기준, 납기 확정 아님)
- D0: 45분, 소유 경로·contract 1.0 및 접근권한 확인. A/B 각 feature 브랜치 생성.
- D+2 근무일: 20분, 실제 주석 가용성·합성 계약 결과만 교환. 코드 통합하지 않음.
- D+5 근무일: 30분, C1 시연·데이터 pilot·규칙 질문 결정. 계약 변경은 여기서 명시적으로 버전 변경.
- D+10 근무일: 2시간 통합 창 제안. 각자의 완료 조건을 통과한 경우만 merge.
D+10은 추정 통합 창이지 서비스 출시 보장이 아니다. 미충족이면 보류 항목과 다음 창을 기록한다.

## Git 작업과 통합
새 팀 저장소의 main을 공통 기준으로 사용한다. 기존 로컬 작업 폴더는 보존한다.
A: feature/core-reliability, B: feature/reconciliation. 각자 main에서 분기한다.
주 1~2회 진행 결과와 계약 문제만 공유하고, 통합 창에서 B PR을 A가 검토·병합한다.
GitHub 댓글/초대는 사람이 직접 수행하거나 별도 지시 후 실행한다.

통합 순서:
1. A/B가 같은 schema_version=1.0 입출력과 golden fixture를 검증한다.
2. B의 순수 모듈·adapter·CLI 테스트, 기존 관련 회귀를 통과한다.
3. A가 검증된 태그와 지정된 문서 버전을 packet으로 변환하는 bridge를 추가한다.
4. 결과를 기존 grade와 분리한 immutable reconciliation revision에 저장한다.
5. API·DB 변경 계약, migration/read compatibility, 기능 off rollback을 먼저 정의한다.
6. UI와 보고서에 별도 축·미실행/실패·양쪽 원문을 연결한다.
7. 같은 태그·규칙의 기존 grade/label 및 과거 보고서 해시 불변을 검증한다.
8. 타 테넌트·기간·버전 혼입, 중복 재시도, If-Match 충돌, 실패 후 복구를 검사한다.

반환 조건: A가 API·저장소 경계를 완성하기 전 B 모듈을 운영 완료라고 부르지 않는다.
Rollback: 신규 연계 실행 off, 새 revision 보존, 기존 G/P/M 경로 유지. 파괴적 migration 금지.

## 비용·완료 기록
제품 모델 예산 USD 10은 팀 전체 기존 누적 한도이며 B에게 새 USD 10을 부여한 것이 아니다.
B 기본 실행은 모델·DART 네트워크 없이 fixtures로 한다. live 호출은 사용자의 기존 승인 범위와 잔액을 A와 확인한다.
DART 키는 개인 .env.local 또는 환경변수 DART_API_KEY에 두고 로그·fixture·PR에 넣지 않는다.
완료 기록: 기준 commit, 실제 실행 명령/exit code, 데이터 split, synthetic/live, 오류·보류·비용, not_run 목록.
