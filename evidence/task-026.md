# TASK-026 — 대시보드·상태 분리 검증 근거

Date: 2026-09-09 (Asia/Seoul)

Status: 로컬 합성 경로에서 구현·검증. 실제 모델 호출, AWS 변경, 고객 데이터 처리,
법률·권리·적용성 승인은 수행하지 않았다.

## 구현 범위

- `summarize_snapshot`은 고정 Coverage, 현재 Decision revision, 승인된 requirement
  applicability를 순수 집계한다. E0~E3 분포에는 `decision_status=decided`만 포함하며
  null/blocked/not_run/not_applicable decision은 `undecided_count`로 분리한다.
- 판독 불가·미처리·검토 필요는 Coverage에 그대로 남긴다. 결손 요소는 decision별로 한 번씩
  세고, unverified/unlicensed basis는 별도 집계한다.
- known applicable만 충족률 분모에 넣는다. N_A와 deferred는 별도 수로 제외하고,
  undetermined는 별도 수로 표시한다. requirement universe 자체가 미실행이면
  `undetermined_applicability_count=null`, `fulfillment_rate=null`이며 0% 완료로 위장하지 않는다.
- `LocalSummaryStore`는 기존 local-synthetic-only SQLite와 immutable extraction artifact,
  claim head, tag/decision revision을 한 transaction에서 읽는다. run epoch, frozen rule-pack hash,
  artifact hash와 tenant/run/document identity가 맞지 않으면 실패한다. 변경 rule-pack의 current
  decision은 self-verifying target pack, exact saved decision, 이전 head, tag/input hash가 모두 같은
  immutable `rescore_artifact`가 있을 때만 허용한다.
- `GET /v1/runs/{run_id}/summary`는 viewer 인증, tenant scope, 120/min/user rate limit,
  `Cache-Control: no-store`, 고정 Summary DTO를 사용한다. 다른 tenant의 run은 404다.
- `RunSummary`는 등급 분모, 미판정, 검토 필요, 판독 불가, 미처리율, 적용/N_A/유예/미확정,
  충족률, 검증되지 않은 기준 근거와 결손 요소를 함께 렌더링한다.

Local adapter는 `LocalSummaryStore.kind = "local-synthetic-only"`로 명시했다. 적용성 manifest
producer는 아직 없으므로 adapter가 적용/N_A/유예를 발명하지 않고 미실행 null을 반환한다.

## TDD red → green

1. `uv run pytest tests/acceptance/test_dashboard.py -q`
   - 최초 exit 2: `ModuleNotFoundError: No module named 'proofops.application.summaries'`.
2. 같은 명령의 최초 구현 실행
   - exit 1: 6 passed, 2 failed. 합성 run snapshot fixture의 `scope` 누락으로 동시성 reader가
     시작 전 실패했고 HTTP도 404였다. fixture를 고정 계약에 맞게 수정했다.
3. 같은 명령의 다음 실행
   - exit 1: 7 passed, 1 failed. store 직접 출력은 정상이었지만 router의
     `StrictDTO.model_validate`가 내부 UUID 문자열을 거부해 HTTP 409를 반환했다. 기존 run/claim
     router와 같이 검증된 dict를 JSONResponse로 반환하도록 최소 수정했다.
4. `uv run pytest tests/acceptance/test_dashboard.py -q`
   - exit 0: 8 passed, 2 existing Starlette/httpx/AnyIO deprecation warnings.
5. 실제 local synthetic parse/extract/tag checkpoint 연결 사례를 추가한 뒤 같은 명령
   - exit 0: **9 passed**, 같은 2 warnings.
6. coordinator가 발견한 changed-pack rescore 회귀를 실제 durable rescore → populated Summary HTTP로
   추가한 최초 실행
   - exit 1: rescore는 ready였으나 기존 frozen-pack 단일 비교 때문에 Summary가 409였다.
   - receipt lineage 구현 직후에는 HTTP 200이 되었고, 테스트의 잘못된 E3 가정이 실패했다. 실제
     unknown 태그 decision은 규칙엔진상 blocked이므로 grade를 발명하지 않고 `undecided_count=1`을
     단언하도록 고쳤다.
   - 최종 targeted 실행 exit 0: **1 passed**, 2 existing dependency warnings. 같은 테스트에서 exact
     receipt 없는 changed-pack head가 409인지도 확인한다.

테스트는 손으로 계산한 2건의 grade denominator, 2건의 undecided, unreadable 1쪽,
applicable 2/satisfied 1, N_A 1, deferred 1, undetermined 1을 단언한다. 실제 SQLite read가
중간에서 멈춘 동안 새 immutable revision/head/epoch writer를 경합시켜 old epoch+E0 또는
new epoch+E3만 관찰되고 혼합 snapshot은 나오지 않음을 확인한다. 실제 FastAPI 인증/tenant
경계와 실제 React server render도 실행하며 결과 endpoint mock은 사용하지 않는다.

## 실행한 검증

| Command | Actual result |
|---|---|
| `uv run ruff check packages/proofops/application/summaries.py packages/proofops/adapters/local/summary_store.py apps/api/src/proofops_api/routers/summaries.py tests/acceptance/test_dashboard.py` | exit 0, `All checks passed!` |
| `uv run ruff format --check packages/proofops/application/summaries.py packages/proofops/adapters/local/summary_store.py apps/api/src/proofops_api/routers/summaries.py tests/acceptance/test_dashboard.py` | exit 0, 4 files already formatted |
| `uv run mypy packages/proofops/application/summaries.py packages/proofops/adapters/local/summary_store.py apps/api/src/proofops_api/routers/summaries.py --follow-imports=silent` | exit 0, no issues in 3 source files |
| `uv run pytest tests/acceptance/test_dashboard.py -q` | exit 0, **9 passed**, 2 existing dependency warnings |
| `uv run pytest tests/acceptance/test_rescore.py -q` | exit 0, **42 passed**, 2 existing dependency warnings |
| `uv run pytest tests/acceptance/test_dashboard.py tests/acceptance/test_coverage.py tests/acceptance/test_reviews.py tests/acceptance/test_rules.py tests/acceptance/test_industry.py tests/acceptance/test_regulatory.py tests/acceptance/test_exceptions.py -q` | exit 0, **168 passed**, 2 existing dependency warnings |
| `uv run pytest tests/integration/test_local_tag_runner.py tests/integration/test_claim_api.py tests/integration/test_local_api_composition.py -q` | exit 0, **21 passed**, 2 existing dependency warnings |
| `uv run pytest tests/integration/test_local_api_composition.py -q` | exit 0, **1 passed**, 2 existing dependency warnings; composed API includes summary auth/404 route |
| `uv run pytest tests/unit -q` | exit 0, **16 passed** |
| `uv run pytest tests/contracts -q` | exit 0, **29 passed**, 2 existing dependency warnings |
| `uv run pytest tests/security -q` | exit 0, **10 passed** |
| `uv run python scripts/verify_architecture.py` | exit 0, all purity/DTO/ports/composition/LLM-tag contract checks passed |
| `pnpm --dir apps/web typecheck` | 첫 실행 exit 2: concurrent `ClaimWorkspace.tsx:64`의 unused `ReviewPage`; 해당 소유자가 수정한 뒤 재실행 exit 0 |
| `pnpm --dir apps/web build` | 첫 실행은 같은 foreign-WIP type error로 exit 2; 재실행 exit 0, Vite 45 modules, `index-D8FkiPzt.js` 293.48 kB (gzip 92.06 kB) |
| `uv build --package proofops --out-dir /tmp/proofops-task026-build` | exit 0, sdist와 wheel 생성 |
| `uv build --package proofops-api --out-dir /tmp/proofops-task026-build` | exit 0, sdist와 wheel 생성 |
| `git diff --check -- packages/proofops/application/summaries.py packages/proofops/adapters/local/summary_store.py apps/api/src/proofops_api/routers/summaries.py apps/web/src/features/dashboard/RunSummary.tsx tests/acceptance/test_dashboard.py` | exit 0, no output |

## 중요 검토와 계약 조정

- docs/28 §5는 unknown applicability를 별도 표시하도록 요구하지만 기존 Summary
  OpenAPI/JSONSchema에는 필드가 없었다. coordinator에게 공유 계약 변경을 요청했고 root가
  `undetermined_applicability_count: integer >= 0 | null`을 optional로 추가했다. 새 producer는
  항상 필드를 반환하고, 옛 artifact는 필드 누락을 허용한다.
- strict Pydantic DTO는 Python 내부 UUID 문자열을 자동 변환하지 않는다. router에서 불필요한
  재검증을 제거하고, 순수 집계의 UUID/정수/coverage/grade-label 검증과 JSONSchema HTTP 검증을
  유지했다.
- original frozen pack만 허용하던 summary provenance 검사는 합법적인 rules-only rescore head를
  거부했다. 검사를 제거하지 않고, 원본 pack decision 또는 immutable rescore receipt의
  self-verifying target pack + exact decision record + previous head + tag/input hash 결합만 허용한다.
- 추가 중요/치명 이슈는 찾지 못했다. shared App/main/composition/contract 변경은 coordinator
  소유이며 이 worker가 덮어쓰지 않았다.

## Rollback과 미실행 게이트

DB schema와 dependency/lockfile 변경은 없다. rollback은 summary router wiring과
`LocalSummaryStore` construction을 비활성화하면 되며 기존 extraction/tag/decision revisions와
artifact는 그대로 보존한다.

- Full interactive browser E2E: `not_run`; 실제 React SSR acceptance와 TypeScript/Vite build는 실행했다.
- 실제 Bedrock/model/AWS/DynamoDB/staging/load: `not_run`; 승인 범위 밖이다.
- 실제 고객/비공개 문서, 데이터·권리·법률 승인, 실제 산업/유예 applicability manifest:
  `blocked/not_run`. 미실행 상태는 null로 노출한다.
- dependency/license scan: 해당 없음; dependency와 lockfile을 변경하지 않았다.
- `python scripts/validate_package.py`: 앱 테스트가 아니라 공유 문서/계약 검사이며 coordinator가
  공유 계약을 소유하므로 이 worker의 완료 근거로 사용하지 않았다.
