# 18 · CI/CD·개발 흐름

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. Git 작업
기존 main 을 보존하고 `feature/proofops-{task}` 브랜치에서 작은 PR 로 진행한다. 각 PR 에는 Requirement/Task/Test ID, 도메인 변경 없음, contract 변화, source migration, 테스트 실제 명령·결과, 비용/보안 영향, UI screenshot 을 기록한다. commit 은 feat/fix/test/docs/refactor/chore 유형을 사용한다. 테스트 삭제·threshold 완화로 빌드를 맞추지 않는다.

## 2. CI jobs (구현 후 추가할 workflow)
| Job | 실행 | 차단 기준 |
|---|---|---|
| package-contracts | `python scripts/validate_package.py` | 문서/fixture/OpenAPI/schema/link 불일치 |
| python | uv sync --locked; ruff; mypy; pytest unit/contracts | lint/type/unit 실패 |
| frontend | pnpm install --frozen-lockfile; lint; typecheck; test; build | TS/컴포넌트/build 실패 |
| architecture | AST forbidden imports, extra runtime dependency | domain→SDK/scripts/legacy import |
| integration | local adapters+staging marked tests | CAS/outbox/source security contract 실패 |
| supply-chain | secret scan, SBOM, dependency audit, license inventory | secret, 승인되지 않은 copyleft/default adapter |
| containers-iac | Docker build, CDK synth/diff/test, image scan | root container/public S3/wildcard IAM |
| E2E | Playwright synthetic + tenant isolation | 주요 여정/출처/리뷰 실패 |
| ai-eval | schedule/manual, 승인 budget/keys | 이전 validation 대비 critical regression |

PR CI 에는 기본적으로 고객 원고/실제 모델 API key 를 제공하지 않는다. fork PR 에 secret 을 주는 pull_request_target 패턴은 금지한다. GitHub action 은 가능하면 full commit SHA 로 pin 하고 실재 SHA 는 설치 시 공식 release 확인 후 사용한다. 문서에 임의 SHA 를 만들어 넣지 않는다.

## 3. 배포 workflow
main merge→이미지 build/digest→staging migration dry-run→stagingdeploy→smoke+contract→manual production approval→production rollout→20분 관측 gate(운영 절차 목표). 작업 실행 중 rulepack/model snapshot 은 바꾸지 않는다. cloud 계정 없는 상태에서 deploy 단계 skip 을 성공배포로 표시하지 않는다.

GitHub OIDC 로 한정 배포 role 을 assume 하고 대상 branch/environment 를 trust policy 에서 제한한다. AWS long-lived keys 를 repo secret 에 저장하지 않는다. rollback 은 이전 digest/rulepack/indexalias 를 가진 배포 manifest 를 선택한다. rule/schema destructive change 가 있으면 rollback compatibility 를 PR 에 먼저 작성한다.

## 4. 증거 산출물
각 CI run 은 commit/lock/config/hash, 실행 명령, junit/coverage, API diff, 보안 scan, E2E evidence 를 보관한다. `pass`, `failed`, `not_run`을 구분하고 API key 없어서 모델평가를 skip 한 run 에 “AI 정확도 검증” 배지를 주지 않는다. 패키지 생성 검증은 앱 CI 와 분리된 문서 단계 검증이다.
