> **팀 개발 시작:** [2026-09-18 인수인계 패키지](handoff/2026-09-18/README.md)
> 개발자 A: 기존 ESG 파이프라인 / 개발자 B: 독립 DART·C1/C3 / 도메인: 원문 정답과 규칙.
> 이 저장소는 기존 로컬 commit 254f228의 현재 파일 스냅샷에서 시작합니다. 기존 Git 이력은 포함하지 않습니다.
> 새 팀 작업은 이 저장소를 clone하고 main에서 분기하세요. 기존 로컬 브랜치를 강제 push하지 마세요.

# ESG ProofOps · Implementation-ready Development Package v1.0

지속가능성 공시 입증 검토 시스템의 개발 문서·계약 패키지. 도메인 정본은 첨부 원문 v2.0(2026-09-07)이며, 기존 GitHub 의 선택 이식과 OpenDataLoader 기반 파싱 구조를 반영했다.

로컬 문서 업로드·파싱·태깅·검토·재판정·요약·평가와 버전 보존·인증·감사·비용 제한을 구현하고 후속 기능을 연결 중이다. 구현·검증 범위와 보류 입력은 [작업 현황](docs/IMPLEMENTATION_STATUS.md)에 기록한다. 실제 고객 PDF 벤치마크·Bedrock 호출·AWS 배포는 아직 수행하지 않았다. `validate_package.py`는 문서·schema·설정·참조관계만 검사한다.

## 먼저 읽기
[최상위 명세](docs/00_MASTER_SPEC.md) → [기존 코드 재사용 검토](docs/26_LEGACY_REUSE_AUDIT.md) → [파싱·근거 추적](docs/27_PARSING_AND_PROVENANCE.md) → [규칙 계약](docs/28_RULE_ENGINE_CONTRACT.md) → [미정 계약 처리](docs/31_DOMAIN_IMPLEMENTATION_GAPS.md) → [구현 계획](docs/19_IMPLEMENTATION_PLAN.md).

## Codex 에 전달
압축을풀어대상 repo 의개발영역에넣는다. 기존 repo 에 AGENTS.md 가있으면무조건덮어쓰지말고본규칙과충돌을검토해병합한다. `CODEX_START_PROMPT.md`내용을 Codex 에전달한다. 원문두파일과 source_manifest 를같이유지한다. Task 별세부명세는[작업 분해](docs/20_TASK_BREAKDOWN.md), API 는[OpenAPI](contracts/openapi.yaml), ID 연결은[추적표](docs/32_REQUIREMENT_TRACEABILITY.md)에있다.

## 패키지 자체 검증
Python3.11+와 PyYAML/jsonschema 가있는환경에서:

```bash
python -m pip install -r requirements-package-validation.txt
python scripts/validate_package.py
```

실행하면 `evidence/package_validation.json`과 `.txt`를기록한다. 설치명령은문서 검증용의존성만설치하며 AWS·모델을호출하지않는다. 원본 SHA,문서존재,JSON/YAML,OpenAPIrefs,요구사항/API/TaskDAG,fixture 형식,스키마양/음성예시를검사한다.

## 로컬 실행
Python 3.12, uv, Node.js, pnpm을 사용한다. 의존성을 설치한다:

```bash
uv sync --locked
pnpm install --frozen-lockfile
```

서로 다른 터미널에서 API와 웹을 실행한다:

```bash
APP_ENV=local MODEL_ADAPTER=synthetic APP_ORIGIN=http://localhost:5173 uv run proofops-api
pnpm --dir apps/web dev
```

웹은 `http://localhost:5173`, API 생존 확인은 `http://localhost:8000/v1/health/live`다. `APP_ORIGIN`은 변경 요청을 허용할 웹 출처이며, 비어 있으면 변경 요청을 거부한다. 회사·문서·버전은 기본 `.local/state.sqlite3`에, 원본은 `.local/objects/`에 보존한다. 로그인 계정·암호화 저장소가 연결되지 않은 기본 설정은 `/auth/login`에서 503을 반환하며 승인된 프로필을 자동 생성하지 않는다. 운영 환경은 승인된 어댑터가 연결될 때까지 시작을 거부한다.

로컬 작업자는 `uv run proofops-worker --tenant-id <UUID> --run-id <UUID> --once
--stage parse`로 지정한 실행의 파싱을 수행한다. 이후 단계는 `extract`, `tag`다.
[명시적 로컬 실행 설정](docs/17_ENV_CONFIG.md)의 parser/profile/budget 설정과
합성 모드가 필요하며, 원문 검증이나 선행 산출물이 부족하면 partial/blocked를 유지한다.
태깅을 끝냈다고 근거 없는 등급이나 완료 상태를 생성하지 않는다.

평가는 `uv run python -m evaluation.cli --predictions <JSON> --gold <JSON>
--manifest <JSON> --synthetic-fixture`로 분리된 합성 입력을 읽는다.
결과는 같은 로컬 DB에 불변 보고서로 저장하며, 관리자 평가 조회 API에서 확인한다.
실제 정답 데이터에는 `--synthetic-fixture`를 붙이지 않는다.

검증 명령:

```bash
uv run pytest tests/contracts/test_package_contracts.py tests/unit/test_package_validation.py
uv run ruff check packages apps scripts tests
uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src
uv run python scripts/verify_architecture.py
pnpm typecheck
pnpm build
```

후속 작업의 수용 테스트는 `tests/acceptance/`에 추가한다. 클라우드 환경은 17장의 계정 값을 승인된 정보로 설정한 뒤 preflight 한다. 모델·클라우드 값이 없으면 local synthetic으로 진행하고 결과에 합성 표시를 남긴다.

## 사람이 제공하거나 결정해야 할 입력

| 입력 | 필요한 내용 |
|---|---|
| 미정 도메인 기준 | [GAP-001–010](docs/31_DOMAIN_IMPLEMENTATION_GAPS.md)의 판단과 승인된 기준 원문·버전. 조항 번호와 법적 효과를 임의로 채우지 않는다. |
| 실제 문서·권리 | 사용 가능한 기업 보고서 PDF, 기업·보고기간·버전 정보, 처리·보존 권한과 허용 리전. |
| 평가 정답 | 원문 페이지·좌표와 연결된 요소 태깅 정답 및 규칙 버전. 기업 단위로 개발·검증·holdout을 분리하고 모델 출력과 독립적으로 검토한다. |
| 모델·운영 환경 | 승인된 계정·모델 binding·동의·가격/예산·배포 및 보존 설정. 실제 호출·AWS 검증·배포 승인은 별도로 남긴다. |

위 입력을 기다리지 않아도 로컬 합성 데이터로 코드·계약·경합·복구를 검증할 수 있다.
그 결과를 실제 문서 정확도나 운영 환경 검증으로 표시하지 않는다.

## 포함 범위
00–25개발명세,26재사용검토,27파싱,28규칙 계약,29대회데모,30출처,31도메인 gap,32추적표,33handoff audit. API/JSONSchema/루브릭설정초안/합성 rule·edgefixtures/프롬프트/AGENTS/Codex 시작프롬프트가함께있다. 실제규칙조항·safeharbor 등급매핑등원문미정부분은승인 gate 로남긴다.

## 문제 해결
패키지 검증의 sourcehash 오류는원문이변경됐다는뜻이다. 원문을조용히고치지말고새 sourceversion 으로갱신한다. Taskcycle/API 누락오류는 contract 와명세를같이수정한다. MODEL_BINDINGS/CONSENT 가비어있어 live 실행이막히는것은정상보호동작이다. PDF 추출실패는문서근거없음/E0와다르므로27장 qualitygate 를확인한다.
