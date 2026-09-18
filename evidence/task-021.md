# TASK-021 감사 리포트·수정 제안 증거

## 범위와 구현

- 로컬 합성 입력은 `execution_profile: local-synthetic-only`로 명시했다. 실제 고객 데이터, 제품 모델, AWS 변경은 사용하지 않았다.
- `build_report_model`은 하나의 불변 manifest와 정확히 고정된 claim/tag/decision head만 결합한다. tenant, document version, parse manifest, source SHA, rule-pack SHA, model/prompt SHA, 3개 replica SHA 및 source/basis/assurance/SafeHarbor 계보 불일치를 거부한다.
- parse artifact 발행 전에는 발견 claim과 source ref가 모두 0일 때만 `parse_manifest_id: null`을 허용한다. tag/decision revision `0/0`인 미태깅 claim은 이미 알려진 원문 위치를 보존하지만 model/prompt/replica provenance를 가질 수 없고, tagged claim은 record를 생략할 수 없다.
- 미완료·판독 불가·미처리·미확인 조항을 별도 수치와 상태로 노출한다. 수정 제안은 rule engine이 확정한 `missing_elements`의 ID만 요청하며 숫자, 연도, 조항 또는 법적 효력을 생성하지 않는다.
- JSON/CSV/HTML 출력은 Python 표준 라이브러리만 사용한다. HTML은 coverage/미완료/판정/grade/label/revision/결손과 전체 escaped audit detail을 보존하고, CSV는 좌표·parse/version까지 포함한 전체 source-ref JSON cell을 보존한다. HTML을 escape하고 CSV formula-leading cell을 앞따옴표로 방어하며 PDF는 지원하지 않는다.
- React preview는 부분 리포트, 미완료/미확인 상태, 원문 위치, 고정 revision/hash 계보, 보증 및 세이프하버의 `legal_effect: not_determined`를 표시한다.

## 실패 테스트에서 구현까지

1. 최초 AT-021 실행: `uv run pytest tests/acceptance/test_report.py -q` → exit 2, `ModuleNotFoundError: proofops.application.reporting`.
2. 첫 최소 projection 실행 → 7 passed, 2 failed. tenant pin 검증과 실제 React component가 없음을 확인했다.
3. render/provenance 회귀를 먼저 추가한 실행 → exit 2, `ImportError: cannot import name 'render_report'`.
4. 최소 구현 및 실제 SafeHarborRecord/미태깅 provenance 보정 후 AT-021 실행 → 17 passed.
5. 코디네이터 renderer/queued-partial 회귀를 추가한 RED 실행 → 3 failed, 16 passed. tagged record 누락, null parse manifest, HTML audit field 손실을 각각 확인했다.
6. bounded 보정 후 최종 AT-021 실행 → 19 passed.

테스트는 다음을 실제로 확인한다: 미완료와 미확인 조항의 가시성, 없는 숫자를 만들지 않는 제안, tenant/document/source/revision/rule-pack/SafeHarbor claim pin, source-less 확정 판정 거부, 미태깅 provenance 제한, 불변 입력 비변경, 실제 Python rule engine 및 SafeHarborRecord 연결, JSON/CSV/HTML escaping, 실제 React server render.

## 최종 검증 명령과 결과

| 분류 | 명령 | 결과 |
|---|---|---|
| AT-021 | `uv run pytest tests/acceptance/test_report.py -q` | PASS, 19 passed in 0.16s |
| 관련 acceptance/integration | `uv run pytest tests/acceptance/test_dashboard.py tests/acceptance/test_safe_harbor.py tests/acceptance/test_assurance.py -q` | PASS, 63 passed in 2.01s; dependency deprecation warnings 2건 |
| unit | `uv run pytest tests/unit -q` | PASS, 16 passed in 0.90s |
| contract | `uv run pytest tests/contracts -q` | PASS, 29 passed in 1.77s; dependency deprecation warnings 2건 |
| security | `uv run pytest tests/security -q` | PASS, 10 passed in 0.08s |
| Python lint | `uv run ruff check packages/proofops/application/reporting.py tests/acceptance/test_report.py` | PASS, All checks passed |
| Python format | `uv run ruff format --check packages/proofops/application/reporting.py tests/acceptance/test_report.py` | PASS, 2 files already formatted |
| Python type | `uv run mypy packages/proofops/application/reporting.py` | PASS, no issues in 1 source file |
| Web type | `pnpm --dir apps/web typecheck` | PASS, `tsc --noEmit` |
| Architecture | `uv run python scripts/verify_architecture.py` | PASS, all boundary/composition/contract checks passed |
| Package build | `uv build --package proofops --out-dir /tmp/proofops-task021-build` | PASS, sdist와 wheel 생성 |
| 문서/계약 검사 | `uv run python scripts/validate_package.py` | PASS, 705/705; 생성된 공용 timestamp 변경은 즉시 원복 |

진단 중 `uv run python scripts/check_architecture.py`는 존재하지 않는 파일명이어서 exit 2였다. 저장소의 실제 검사기 `scripts/verify_architecture.py`를 찾아 위와 같이 성공 실행했다.

## 미실행·후속 소유권

- 전역 Web build/E2E: `not_run`. 다른 UI 작업자가 공유 App/build를 소유한다는 코디네이터 지시를 따랐고, 이 작업의 component는 AT-021에서 esbuild + React server render로 실제 검증했다.
- `POST /v1/runs/{run_id}/exports`의 원자적 snapshot capture, 저장, idempotency, rate limit, router 및 download: `not_run`, TASK-031 소유.
- 실제 제품 모델 호출, AWS mutation, private customer processing: `not_run`, 금지 범위.
- 데이터/권리/법률 승인과 legal-effect 결정: `blocked/not_run`, human-only gate. 리포트는 법적 효력을 `not_determined`로 유지한다.

## 변경 파일

- `packages/proofops/application/reporting.py`
- `apps/web/src/features/reports/ReportPreview.tsx`
- `tests/acceptance/test_report.py`
- `evidence/task-021.md`
