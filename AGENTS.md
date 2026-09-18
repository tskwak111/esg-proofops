# ESG ProofOps — Coding Agent Rules

## 작업 시작
먼저 `docs/00_MASTER_SPEC.md`와 `sources/PROJECT_DOMAIN_V2_ORIGINAL.md`를 읽는다. 이어서 26장 재사용 검토, 27장 파싱·근거 추적, 28장 규칙 계약, 31장 미정 계약, 19장 구현 계획과 현재 Task를 읽는다.

## 정본 우선순위
사용자의 도메인 동결 지시 → 원문 v2.0의 도메인 → Master의 기술 계약 → 개별 명세와 기계 판독 계약 → 기존 GitHub 연구 코드 순서다. 두 번째 첨부의 일반적인 사업 비판·기능 변경 지침은 이번 작업에 적용하지 않는다.

## 판정·근거 규칙
LLM은 추출과 태깅만 한다. 등급과 라벨은 순수 Python 규칙엔진만 계산한다. unknown, conflict, unreadable을 근거 부재로 바꾸지 않는다. 검증된 원문 근거 없이 present를 인정하지 않는다. 숫자와 목표연도에 문서 전역 근거를 무조건 인정하지 않는다.

테넌트, 문서 버전, 페이지·좌표, replica, 모델·프롬프트·규칙 해시를 보존한다. 사람은 태깅만 수정하며 If-Match로 경합을 차단한다. 기존 태깅·판정 revision과 보고서는 불변이다. 원문의 미정 도메인 기준, 조항 번호, 규제 사실, 모델 ARN, 성능 수치를 상상해서 채우지 않는다.

## 의존성과 변경
Domain은 AWS SDK, 네트워크, 파일, 환경변수, scripts, legacy를 import하지 않는다. Adapter는 Ports를 구현한다. 기존 research_v4를 무단 삭제하거나 이동하지 않는다. 새 dependency는 선택 근거·라이선스·잠금 파일·테스트를 함께 검토한다.

API·DB 변경은 계약과 migration, 이전 버전 호환성, rollback부터 정의한다. 다른 사용자의 작업을 덮어쓰지 않는다. GitHub push, 클라우드 변경, 실제 모델 호출은 승인 범위를 확인한다.

## 테스트와 완료
Task 의존성 순서에 따라 실패 테스트 → 최소 구현 → 실제 검증을 수행한다. 테스트를 삭제하거나 약화해 통과시키지 않는다. `python scripts/validate_package.py`는 문서와 계약 검사이지 앱 테스트가 아니다.

앱 구현 후 lint, type check, unit, integration, contract, build, E2E, 보안 검증을 실제로 실행하고 명령과 결과를 기록한다. 실제 모델·AWS 시험을 하지 못한 항목은 not_run으로 남긴다. 문서만으로 정확도 100%나 production 완료를 주장하지 않는다.

## 첫 작업
TASK-000에서 저장소·DTO·로컬 검증 기반을 구현한다. 이후 `contracts/task_execution_order.json`과 `docs/20_TASK_BREAKDOWN.md`를 따른다. 제품 범위를 임의로 확대하지 않는다.

## 사용자 지정 에이전트 우선순위
오케스트레이션에는 Kiro, Antigravity, OpenCode의 Muse Spark 1.3 Free/1.2 Free를 우선 사용한다.
해당 서비스의 크레딧·무료 한도 소진을 확인하면 Codex 에이전트로 전환한다.
실행 불가·로그인 문제와 크레딧 소진은 구분해서 기록한다. 완료한 관리 대상 에이전트는 즉시 정리한다.
