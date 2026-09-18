# 24 · Codex 작업 지침

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 읽기 순서
root AGENTS → 00_MASTER_SPEC → sources/PROJECT_DOMAIN_V2_ORIGINAL → 26_LEGACY_REUSE_AUDIT → 27_PARSING_AND_PROVENANCE → 28_RULE_ENGINE_CONTRACT → 31_DOMAIN_IMPLEMENTATION_GAPS → 19_IMPLEMENTATION_PLAN → 현재 Task 와연결된 API/schema/tests 순서로읽는다. 모든26문서를매번전체복사해 prompt 에넣는대신현재작업범위의계약을읽고고정한다.

## 2. 작업 경계
개발자는새제품을기획하는것이아니다. 도메인 정본은원문 v2.0이고기존 V4저장소/일반개발프롬프트보다우선한다. 새 SaaS 기능·결제·기업점수·뉴스 truth·법적면책판정·자율규칙 변경을추가하지않는다. 불명확한것은31장 gate 로보존한다. 환경계정 값/모델 ID/공식조항을상상해서넣지않는다.

## 3. 코드 운영
Task DAG 를따른다. 우선현재 repo 상태/branch/테스트를확인하고사용자작업을덮지않는다. 필요한경우별도 worktree 또는 branch 로격리한다. runtime 은 domain→application/ports→adapters 방향을지킨다. 기존 research_v4를무단 삭제/물리이동하지않고,26장확인된이식범위만 characterization 후옮긴다. 새 dependency 는이유/대안/license/lock 을기록한다.

API/DB 변경은 contract 와 migration→테스트→구현순서다. 별도 SQL DB 를문서없는이유로추가하지않는다. 가짜0bbox/unknown=false/LLMgrade/표숫자복사를지름길로쓰지않는다. 테스트를지우거나기대치를현재잘못된구현에맞춰낮추지않는다.

## 4. 작업 보고 형식
Task 완료시 변경파일, 구현한요구사항, 실행한명령+실제결과, 새로발견한 gap, 외부 환경때문에 not_run 인항목을기록한다. 모든검증을했다고포괄적으로쓰지않는다. 실 API·PDFbenchmark·AWSdeploy 를하지않았으면명시한다. API key/승인없는실제 모델호출은하지않는다.

## 5. 완료 명령 계약
패키지단계는 `python scripts/validate_package.py`. 앱구현후 `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy packages apps/api apps/worker`, `uv run pytest tests/unit tests/contracts tests/acceptance`, `pnpm --dir apps/web lint`, `pnpm --dir apps/web typecheck`, `pnpm --dir apps/web test`, `pnpm --dir apps/web build`, `pnpm --dir apps/web exec playwright test`, `uv run python scripts/verify_architecture.py`, `uv run python scripts/verify_rulepack.py`를실행할수있도록 TASK-000/CI 에서진입점을구현한다. 실제 package layout 에맞는 import root 설정은 pyproject/TSconfig 로고정한다.

AWSpreflight/통합/실제 모델평가는별도승인환경에서실행하고증거를보관한다. 어느단계가실행불가능하면실행되지않았다고기록하고해당완료배지를주지않는다.

## 6. Codex 시작 메시지
```text
이 저장소에서 ESG ProofOps 개발을 시작해라.
AGENTS.md와 docs/00_MASTER_SPEC.md를 먼저 읽고, 첨부 도메인 v2.0을 고정 기준으로 삼아라.
기존 esg-evidence-audit 코드는 docs/26_LEGACY_REUSE_AUDIT.md의 선택 이식 대상일 뿐 새 도메인 정본이 아니다.
TASK-000부터 dependency DAG 순서로 진행하되, 테스트→구현→실제 검증의 작은 단위로 완료해라.
OpenDataLoader/표 교차검증/원문 provenance와 순수 규칙엔진 경계를 지켜라.
도메인 gap은 명시된 blocked 상태로 구현하고 E 기준·조항·모델 ARN·성능 수치를 임의로 만들지 마라.
API·schema·requirements·tests의 연결을 유지해라.
현재 저장소 상태와 실행 가능한 검증을 먼저 확인한 뒤 첫 Task를 수행하고, 완료/미실행 증거를 구분해 보고해라.
```
