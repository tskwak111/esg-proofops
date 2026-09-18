# 개발자 A 작업 설명서

## 목표와 읽을 코드
사용자는 원문을 등록하고, 주장을 선택하고, 근거와 판정 이유를 확인하며, 잘못된 태그를 수정하고 새 보고서를 받아야 한다.
B 모듈은 이 시스템에 붙는 계산 부품이다. A는 전체 연결의 책임자다.
먼저 AGENTS와 docs/00,27,28,31,19,IMPLEMENTATION_STATUS를 읽는다. 기존 구현을 처음부터 다시 만들지 않는다.

## A0. 실행 환경·현재 실패를 고정
```bash
uv sync --locked
pnpm install --frozen-lockfile
uv run python handoff/team-v2/contract/validate.py
uv run pytest tests/acceptance/test_rules.py -q
```
Python3.12, Java21(PDF), Node22, pnpm10.0.0. `java -version`이 다른 버전이면 파서 경로 설정을 확인한다.
API: `APP_ENV=local MODEL_ADAPTER=synthetic APP_ORIGIN=http://localhost:5173 uv run proofops-api`
웹: `pnpm --dir apps/web dev`. health: http://localhost:8000/v1/health/live.
기본 로그인 프로필이 없으면 503이 정상이다. 인증 검사를 끄지 말고 docs/17과 기존 session fixture로 승인된 로컬 구성을 만든다.
합성 모드는 로그인/실제 PDF-to-model 성공을 보장하지 않는다.

2026-09-18 초기 팀 CI에는 실패가 있다: 문서 fixture가 README의 추가 로컬 handoff 링크를 복사하지 못하는 오류,
실제 추출/태깅 receipt 테스트 다수 실패와 PRICE_RECHECK_REQUIRED 관측. 후자는 모든 실패의 원인으로 확정된 것은 아니다.
테스트에서 시간/가격 fixture와 live 정책을 구분해 재현하고, live 가격 만료 가드를 끄거나 날짜를 가짜로 갱신하지 않는다.
전체 CI green 전까지 팀 저장소를 정상 완료라고 부르지 않는다. docs 변경만 통과한 상태와 구분한다.

## A1. 평가 대상과 기준선
입력: D가 작성한 corpus.csv, 원본 파일, 기존 사용 기업 이력.
순서: 원본 hash 확인 → 기업단위 split 확정 → 처리 대상 범위 목록 고정 → 현재 코드로 실행 → 결과 snapshot 보존.
산출: 문서별 pages_selected/readable/unreadable, claims_found, incomplete_batches, 시간/비용/오류.
판정: 보고서 50개 전부를 모델에 보내지 않는다. 레이아웃 종류별로 선정하고 원본 전체 목록/미실행 사유를 남긴다.
실험 실행 명령은 existing `evaluation.section_pipeline`과 `evaluation.local_upstage_pilot --help`를 먼저 확인한다.
`--invoke`가 실제 호출 선택임을 확인하고 예산 잔액 없이 사용하지 않는다.
완료: 실패를 재실행할 수 있는 입력 ID·hash·명령이 존재한다.

## A2. 페이지/문단/표 파싱
위치: application/ingest/, adapters/parsing/, evaluation/report_sections.py.
구현 순서: 놓친 원문 한 사례를 fixture화 → selected page/문단/표 구조 검사 실패 테스트 → 최소 수정 → 다른 레이아웃 회귀.
목차 숫자와 물리 페이지를 구분, 다단 읽기순서·표 헤더·단위·다년도 열·스캔 실패를 기록한다.
없는 bbox는 null. 문자 합치기로 다른 셀의 숫자를 원문처럼 만들지 않는다.
완료: E 소주제·환경 Data·Appendix 범위 정답과 비교 가능하고 누락은 숨겨지지 않는다.

## A3. 주장 추출
위치: application/claims.py, apps/agent/src/proofops_agent/upstage_extraction.py, evaluation/context_extraction.py.
주장마다 원문 quote/source_ref, atomic statement, track 후보, year/boundary와 추출 기록을 보존한다.
한 문장의 목표+성과를 2개로 분리하되 의미 없는 표 제목을 주장으로 만들지 않는다.
완료: D gold와 누락/잘못된 분리/중복을 구분해 정밀도·재현율을 산출. 모델 출력만 보고 gold 수정 금지.

## A4. 근거·표·각주 조건 병목
위치: application/evidence/, domain/numeric.py, source_condition 관련 API/스토어.
먼저 tests/acceptance/test_source_condition_ownership.py, test_source_condition_interpretation.py,
tests/integration/test_native_source_verification.py를 읽고 현 계약을 이해한다.
검증 단계: 문자열 실재 → 주장 귀속 → 각주 셀 귀속 → 조건의 적용범위 → 수치 계산 사용 가능성.
각 단계를 독립 기록. 각주 2)가 같은 페이지에 있다는 이유로 모든 2) 셀에 연결하지 않는다.
unknown은 계산 입력 불가. 원문이 확인돼도 조건 의미가 미해결이면 보류.
완료: 이어지는 각주·다른 열 번호·다른 연도/단위·문서 간 숫자 유입 반례 통과.

## A5. 태깅과 규칙
입력 evidence packet은 최종 태깅 전에 동결. replica별 ID를 다르게 해 동일 캐시를 합의로 세지 않는다.
검증된 요소만 규칙엔진에 전달하고 미정 GAP은 D의 승인된 사례가 오기 전 유지한다.
D가 규칙을 바꾸면 rulepack 새 버전과 truth table 회귀, 이전 버전 재현을 확인한다.
P6/세이프하버·비GHG Scope 등 모호한 조건을 개발자 판단으로 채우지 않는다.
완료: 같은 입력·규칙 hash는 같은 의미 결과. model이 grade를 반환해도 무시/거부한다.

## A6. 검토와 원문 화면
apps/web/src/features/claims, SourceViewer, API reviews/source_conditions 및 reporting을 재사용한다.
사용 흐름: 주장 선택 → 후보와 확정 근거 구분 → 원문 위치 → 태그 수정 → If-Match → 새 판정 → 새 보고서.
수정 실패를 성공처럼 보이지 않게 한다. 이전 revision 링크와 미확정 이유를 보인다.
완료: tests/acceptance/test_reviews.py, test_report.py와 실제 브라우저 흐름. E2E는 모형 API 응답만으로 대신하지 않는다.

## A7. B 모듈 통합
contract/1.1 packet을 기존 태그/문서 메타에서 만든다. B의 내부 파일/DB 경로에 의존하지 않는다.
전체 코드 병합 전 fixture exchange로 계약 검증. 자세한 저장/API/버전 전략은 delivery/INTEGRATION.md.
B 출력이 schema에 맞더라도 tenant, packet/policy/source hash를 확인한다. 기존 Decision에 C결과를 섞지 않는다.
완료: 동일 G/P/M 입력에서 B on/off로 grade/label 불변, C결과만 별도 표시.

## A8. 평가·운영·제출
D와 평가 split을 잠그고 예측 생성 후 gold를 비교한다. 알려진 실패 기업만 반복해 성능을 부풀리지 않는다.
정밀도·재현율·보류율·검토 수정률·시간·비용을 함께 보고한다. 보류를 정확한 음성으로 세지 않는다.
전체 lint/type/unit/integration/contracts/security/build/E2E, 배포 대상의 권한/비용/복구를 기록한다.
운영 설정 없으면 not_run. 한계·실행명령·대표 성공/보류 데모를 준비한다.

## 기본 회귀 명령
```bash
uv run pytest tests/acceptance/test_rules.py tests/acceptance/test_reviews.py tests/acceptance/test_report.py -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation
uv run python scripts/verify_architecture.py
uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security -q
pnpm typecheck
pnpm build
```
이 명령 목록은 실행 계획이다. 실제 통과 여부는 각 commit에서 기록한다. 실패 테스트를 삭제·완화하지 않는다.
