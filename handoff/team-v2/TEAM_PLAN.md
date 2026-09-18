# 3명 업무 분담 · 날짜별 일정 없음

## 1. 책임 배분
초기 추정: 전체 작업량 A45/B30/데이터25%. 개발만 A60/B40%. 측정된 공수나 완료율이 아니다.
실제 남은 오류·DART 형식·정답 검토량에 따라 달라진다. AI 코드 생성 시간과 인간 검토 시간도 같지 않다.

| 담당 | 끝까지 책임질 결과 | 다른 담당에게 요구할 입력 |
|---|---|---|
| A: 본인+개발 보조 | ESG 원본→주장/근거→규칙→검토/보고서, 평가·운영 및 팀 통합 | B의 검증된 연계 결과, 데이터 담당의 원문 정답·규칙안 |
| B: 추가 개발자 | 공시 수집→동일 기업·기간 검증→C1~C4→JSON/CLI | 초기에 합성 packet, 이후 A의 실제 packet·도메인 정책 |
| D: 도메인·데이터 | 문서 목록·기업 split·주장/요소/표/보증/연계 정답·미정 규칙 결정안 | PDF/공시 원본, 페이지 미리보기·좌표·예측을 숨긴 작업용 파일 |

A 소유: 기존 packages/application/ingest,evidence,tagging; domain/rules; API·worker·web·DB·locks·CI.
B 소유: domain/reconciliation/, application/reconciliation/, adapters/dart/,
evaluation/reconciliation_cli.py, tests/reconciliation/, config/accounting/, evidence/reconciliation/.
D 제출: 데이터 양식의 복사본과 검토 문서. 제품 코드·승인 rulepack을 직접 변경하지 않는다.
계약 schema, 공유 DTO, lock 변경은 A가 관리한다. B가 원하면 변경 이유와 양·음성 예제를 함께 요청한다.

## 2. 독립 개발의 실제 의미
B는 A의 로그인/화면/DB를 기다리지 않는다. packet JSON→결과 JSON을 먼저 만든다.
A는 B의 DART 완성을 기다리지 않는다. 합성 결과로 UI/API 연결을 검사하되 화면에 synthetic을 표시한다.
D는 모델 결과를 기다리지 않는다. 원문을 보고 gold 초안을 만든다. 모델 결과를 본 데이터는 독립 test에서 제외한다.
각자의 원본·중간 결과·실행 기록을 보존하고, 마지막 합칠 때 서로의 내부 DB를 직접 읽지 않는다.

## 3. 작업량을 산출물로 보기
A: 상세 playbook 9개 작업 묶음 + 전체 회귀/통합 확인표.
B: 상세 playbook 8개 작업 묶음 + C1~C4 사례·가드·CLI.
D: CSV 8종 + 규칙 질문 18개 + 원문 근거 및 독립 평가 split.
범위가 큰 작업이다. 한 번에 전부 끝냈다고 선언하지 말고 묶음별 구현/검증/실데이터 상태를 기록한다.

## 4. 21일 1차 제출의 뜻
- A: 실제 PDF 1개 이상으로 주장을 선택해 원문·태그·판정/보류·검토·리포트까지 재현할 수 있는 commit.
- B: 독립 CLI, C1~C4의 실행 가능한 branch와 명시적 보류, 수집 가용성 보고, 계약 테스트.
  C1/C3을 먼저 완성하고 C2/C4가 아직 남으면 그 상태를 적는다. 빠진 것을 완료로 처리하지 않는다.
- D: 전체 목표에 대한 실제 작성 수·미검토 수·미정 질문, 우선 사용할 adjudicated 자료.
- 공통: 실행 명령, 증거 파일, 실패 목록, 상대 담당에게 필요한 입력.
이후 통합·정답 확정·대표 보고서 평가·수정은 계속한다. 21일이라는 날짜 때문에 기능이나 목표 수량을 삭제하지 않는다.

## 5. 연락과 통합
오랫동안 각자 개발 후 처음 합치는 방식은 피한다. 개발은 분리하되 최초 schema/예제 교환,
첫 작동 결과 교환, 최종 기능 PR 통합이라는 세 체크포인트를 둔다. 날짜는 정하지 않는다.
진행 보고는 delivery/STATUS_TEMPLATE.md 형식. 계약 문제가 생기면 바로 기록해 두 사람이 같은 가정을 쓰게 한다.
브랜치 A=feature/core-reliability, B=feature/reconciliation. 코드 기준은 새 팀 GitHub main.
원래 로컬 폴더의 다른 Git 이력을 팀 main에 force push하지 않는다.

## 6. 비용·승인
모델 예산은 기존 누적 USD10, 사람별 USD10이 아니다. 실제 잔액·예약을 A가 확인해 호출량을 배정한다.
DART_API_KEY는 B의 로컬 환경변수, 모델 키는 별도 개인 설정. .env 내용을 PR/스크린샷에 공유하지 않는다.
서버/배포/데이터 권리·규칙 승인 입력은 근거가 없으면 not_run/unresolved. 개발 코드는 그 보류 상태까지 구현한다.
