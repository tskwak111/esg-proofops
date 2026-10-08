# DART 재무 대사(C1~C4) 개발 인계서

작성 2026-10-08 · 대상: DART 연결을 이어받는 개발자 · 기준: `r108-sprint1` @ `390c65b` (= 브랜치 `dart-dev`의 출발점; 이 문서는 `dart-dev`에 포함되어 GitHub에 push됨)
이 문서만 읽고 시작할 수 있게 썼다. 근거 파일 경로는 모두 저장소 상대경로다. "확인함"은 이번에 코드를 읽거나 명령을 실행해 본 것, "기록 인용"은 PR/인계 문서에 적힌 내용을 옮긴 것이다.

---

## 0. 한 줄 요약

**DART 대사 = 지속가능경영보고서(SR)에 적힌 수치·범위·기간을 DART 공시(재무제표·사업보고서)와 같은 기업·같은 기간으로 맞대 보고, "차이가 있으면 그 차이를 설명하는 문장이 공시에 있는가"만 점검하는 별도 축이다.** 회계가 맞는지는 판단하지 않고, 등급(G/P/M)·라벨에도 영향을 주지 않는다.

| 항목 | 쉬운 말 |
|---|---|
| C1 조직경계 | 보고서가 말하는 사업장·법인 범위가 재무제표의 연결 범위와 **정확히 같은 집합**인가. 다르면 차이를 설명한 인용이 있는가. |
| C2 보고기간 | 보고서 성과 수치의 기간이 재무제표 기간과 같은가(달력 날짜로 비교, 비12월 결산·다년 표 포함). 기간 밖 활동이면 "적용 아님". |
| C3 투자약정 vs CAPEX | 목표에 "N원 투자" 약정이 있을 때, 같은 기간 재무 CAPEX와 비교할 수 있는가. 임계값이 없으면(현재 `null`) "약정이 공시됨"만 `matched`로 인정하고 배수 비교는 차단. |
| C4 분류 근거 | "친환경 매출 비율" 같은 분류 수치에 **정의**와 **산식(분모)** 공시가 있는가. 분류가 옳은지는 보지 않음. |
| C5 | **실행 차단**(회계 판단이 필요한 단계). 어떤 경로에서도 실행하지 않는다. |

결과 상태는 `matched` / `needs_explanation` / `not_applicable` 세 가지이고, 정책·출처·검색이 미완이면 `execution_state=blocked, status=null`이다. **"모르겠음"을 "없음"으로 바꾸지 않는다.**

---

## 1. 지금 결론 (읽는 순서 안내)

1. **엔진과 제품 골격은 이미 있다.** DART 수집 → 후보 생성 → C1~C4 판정 → HTTP/SQLite 불변 revision → React 검토 화면까지 로컬에서 이어진다. 오프라인 검증 15/15 통과(§3.5).
2. **하지만 메인 파이프라인에서 "자동으로" 이어지지는 않는다.** 케이스는 운영자가 CLI로 만든 초안 번들을 서버에서 등록해야 생긴다(`evaluation/reconciliation_import.py`). 회사→DART `corp_code` 연결, 접수번호(`rcept_no`) 자동 확정, 주장→패킷 자동 생성, 설명 문장 자동 검색이 **없다**. 이것이 본선 전 "연결 가능"의 핵심 공백이다(§6).
3. **의미 정확도는 측정된 적이 없다.** 원문 해시·인용 재현 검사(기계적 사실)만 있고, 사람 정답(gold)이 없어 C1~C4 판정 정확도 분모는 0이다. 테스트 수를 정확도로 말하지 말 것.
4. **채택된 도메인 결정(REC-001~008)은 일부만 코드에 반영**되어 있다(§5). 스키마 1.1의 한계로 막힌 항목(시설↔법인 매핑, 다년 CAPEX)은 스키마 변경 결정이 필요하다.

---

## 2. 현재 구현 상태 표

범례: ✅ 구현·검증됨 / 🟡 부분 / ❌ 미구현 / ⛔ 의도적 차단

| 영역 | 상태 | 근거 파일 | 비고 |
|---|---|---|---|
| OpenDART 클라이언트 | ✅ | `packages/proofops/adapters/dart/client.py` | 재시도·타임아웃 상한·리다이렉트 금지·50MB 상한·API 키 마스킹(`redact_api_key`). 엔드포인트: `list.json`, `fnlttSinglAcntAll.json`, `fnlttXbrl.xml`, `document.xml`. 전송 계층 주입 가능 → 테스트는 오프라인. |
| 회사코드(`corp_code`) 조회 | ❌ | — | `corpCode.xml`(고유번호 전체 목록) 조회 코드 없음. `corp_code`는 항상 운영자가 직접 입력. |
| 공시 목록 → 접수번호 확정 | 🟡 | `client.list_filings` | 메서드만 있고 **어디서도 호출하지 않는다**(테스트 제외 grep 확인). 수집 CLI는 `--rcept-no`를 반드시 명시("never latest"). 정정공시 최신본 선택(REC-006)은 사람이 수동 처리했다(동서 사례). |
| 원문 수집·불변 저장 | ✅ | `adapters/dart/artifacts.py`, `evaluation/reconciliation_collect.py` | 콘텐츠 해시 주소 저장, XML은 XXE/Billion-laughs 방어 파서. 수집 결과는 `collection-1` 매니페스트. 일부 실패는 종료코드 3. |
| 후보 생성 | ✅ (상한 있음) | `adapters/dart/candidates.py` (1,116줄), `evaluation/reconciliation_prepare.py` | 원문 XML 요소 ID 또는 명시적 텍스트 투영으로 후보 + 계보. 상한 2,000건(`MAX_CANDIDATES`) — 도달하면 `truncated`로 **전체 검색 완료로 해석 불가**. 후보는 사실이 아니라 "후보". |
| 정규화 | ✅ | `adapters/dart/normalization.py` | 금액·엔티티 집합·기간 정규화, 수집 매니페스트 빌더. |
| C1~C4 엔진 | ✅ | `domain/reconciliation/{c1,c2,c3,c4,engine,common}.py` | 순수 도메인. `ENGINE_VERSION = reconciliation-engine-1.2.0`. 입력은 이미 검증된 패킷만 신뢰. |
| 검증 경계(서비스) | ✅ | `application/reconciliation/service.py`, `sources.py`, `schema.py` | 정책 승인 레지스트리, 문서 신원(테넌트·회사·corp_code·FY·연결/별도·접수번호·기간), 원본 바이트 해시·locator·인용 재검증, 검색 coverage. 실패는 `blocked`. 스키마 1.1 고정. |
| 설명 문장 검색(`explanation_search`) | ❌ | `adapters/local/reconciliation_store.py:931` `_no_candidates` | 제품 경로에서는 **항상 빈 목록**. 설명 인용은 운영자가 번들에 넣은 것만 쓴다. |
| 주장→패킷 변환 | 🟡 | `application/linkage_exchange.py`, `scripts/linkage_exchange_cli.py` | `build_packet`은 신뢰된 Claim+ConfirmedTags로 SR 쪽 절반을 만들고, 재무 쪽은 호출자가 낸 `FinancialContext`를 요구. **CLI에서만 쓰이고 제품(스토어) 경로는 import하지 않는다.** 제품 경로 초안은 `reconciliation_prepare`가 따로 만든다 → 두 갈래(통합 필요). |
| 소스 바이트 검증 | ✅ | `adapters/local/linkage_reader.py`, `adapters/reconciliation/files.py` | PDF 물리 페이지 인용, 루트 제한 파일 리더, 매 읽기마다 해시·경로 재검사. |
| 제품 스토어(SQLite) | ✅ | `adapters/local/reconciliation_store.py` (937줄) | `reconciliation_` 접두 테이블, 스키마 버전, 불변 snapshot/revision, 헤드는 If-Match+트랜잭션, Idempotency-Key. 등록은 서버/운영자 전용(HTTP 아님). |
| HTTP API | ✅ | `apps/api/src/proofops_api/routers/reconciliation.py`, `contracts/reconciliation/product.openapi.yaml` | GET 목록/상세/revision/원문, POST review(reviewer)/policy-approval(admin)/evaluate(editor). 쿠키 세션·CSRF·레이트리밋. |
| UI | ✅ (검토 화면) | `apps/web/src/features/reconciliation/ReconciliationWorkspace.tsx`, `apps/web/src/App.tsx:165,282` | 경로 `/runs/:runId/claims/:claimId/reconciliation`, 주장 상세에서 링크 1개로 진입. 케이스 없으면 빈 상태. |
| 보고서·내보내기 노출 | ❌ (의도적) | `routers/exports.py` 등에 reconciliation 참조 없음 | 대사 결과는 별도 화면에만 있고 보고서/내보내기/등급에 합쳐지지 않는다. 노출 여부는 §9 질문. |
| 메인 파이프라인과의 자동 연결 | ❌ | — | 런 완료 후 자동 케이스 생성 없음. `composition.py`가 스토어를 항상 생성·`main.py`가 라우터를 항상 등록(기능 플래그 없음). |
| C5 | ⛔ | `engine.py`, `service.py:390`, `reconciliation_store.py`(`C5_DISABLED`), `evaluation/reconciliation_cli.py:145` | 엔진·서비스는 `NotImplementedError("stage_disabled")`, 스토어는 422, CLI는 별도 `not_run`(`stage_disabled`) 이벤트. |
| 테스트 | ✅ | `tests/reconciliation/` (테스트 파일 26개) | `pytest tests/reconciliation`: **644 passed, 12 skipped**(Windows Job Object 전용). 아래 §3.5. |
| CI | ✅ | `.github/workflows/ci.yml` `reconciliation` job | Ubuntu·Windows·macOS 매트릭스, Python 3.12, Java 21(Temurin), `scripts/verify_reconciliation.py` + 실제 파서 회귀. |
| 실제 기업 의미 정확도 | ❌ | — | gold 없음. 기아 전문가 CSV 8행은 접수만, 평가 `not_run`. |

### 2.1 이전 개발자 B가 남긴 상태 (기록 인용)

- GitHub `tskwak111/esg-proofops` PR **#7**(OPEN, base `main`, head `feature/developer-b-reconciliation`, 129파일): 제품 통합·실제 원문 평가·로컬 복구 준비. 삼성전자·오뚜기·동서 실제 DART 원문에서 후보 6,001건의 해시·인용 위치 검증, 재무제표 575행 매핑 초안. **모든 후보 목록이 상한에 도달해 전체 평가 결과는 의도적으로 `fail / candidate_catalog_truncated_incomplete_search`.** 숫자는 원문 보존·위치 재현 검사이지 의미/등급 정확도가 아님.
- PR **#10**(MERGED 2026-09-29): 엔진 1.2.0 — C1 기간/연결 검사, C3 CAPEX 기간 일치, 약정 공시 시 임계값 없이 `matched`, 완전 검색 영수증은 SR·재무 두 문서 모두 포함.
- `r108-sprint1`은 위를 **통합 커밋**(`0e68850`, `ba511da` 등)으로 담고 있어 PR 헤드의 조상이 아니다. 같은 영역을 PR #7 헤드와 비교하면 `c3.py`·`engine.py`가 다르다(r108 쪽이 최신).
- **문서가 빠져 있다:** `docs/RECONCILIATION.md`, `RECONCILIATION_HANDOFF.md`, `RECONCILIATION_PRODUCT.md`, `evidence/reconciliation*/` 는 `origin/main`에 있지만 `r108-sprint1` 트리에는 `RECONCILIATION_PRODUCT_CONTRACT.md`만 있다. 읽으려면: `git show origin/main:docs/RECONCILIATION_PRODUCT.md` (또는 `..._HANDOFF.md`, `RECONCILIATION.md`). 특히 `RECONCILIATION_HANDOFF.md` §3~4(버전 3종, 엄격 결과 15키)는 꼭 읽을 것.
- 기아(Kia) 후속(인계 패키지 `outputs/developer-b-handoff-20260929/kia-b-followup-handoff/`): 동일 SHA-256의 SR PDF를 쓴 **로컬 시험 run**은 있으나 회사 등록명 "실제 보고서 검토 시험", `corp_code=null`, SR `local_synthetic=true`라서 기아 법인(`00106641`)의 확정 등록 실행이 아니다. 기아 reconciliation case/coverage/policy 등록은 **0건(미등록/not_run)**. 전문가 CSV는 24열 8행(C1 4·C2 2·C3 2, **C4 없음**), SHA-256 `df4b7817…3017`.

---

## 3. 환경·실행

### 3.1 체크아웃/브랜치 전략
- 브랜치 `dart-dev`: `r108-sprint1` HEAD `390c65b`에서 분기, **로컬 전용·push 안 됨.** GitHub push·PR 생성은 사용자 승인 후에만(`AGENTS.md`).
- 작업 위치는 `r108-sprint1` 디렉터리가 아니라 **별도 worktree**를 권장: `git worktree add ../dart-dev dart-dev` (메인 작업 트리는 미커밋 변경 13건이 있어 건드리지 말 것. 이번 검증도 그 상태에서 읽기만 했고, 변경 파일은 모두 대사 경로 밖이다).
- 메인과 rebase 주기: **2~3일마다, 그리고 메인이 `tagging/`·`claims`·`run_store` 관련 커밋을 올릴 때마다** `git fetch && git rebase r108-sprint1`. 충돌 최소화를 위해 DART 개발자는 아래 "소유 경로"만 수정한다.
  - **DART 소유(자유 수정):** `packages/proofops/adapters/dart/`, `domain/reconciliation/`, `application/reconciliation/`, `adapters/reconciliation/`, `adapters/local/reconciliation_store.py`, `adapters/local/linkage_reader.py`, `application/linkage_exchange.py`, `apps/api/.../routers/reconciliation.py`, `apps/web/src/features/reconciliation/`, `evaluation/reconciliation_*.py`, `scripts/{verify,check}_reconciliation*.py`, `scripts/linkage_exchange_cli.py`, `tests/reconciliation/`, `contracts/reconciliation/`.
  - **공유(메인 담당자와 사전 합의 후 최소 수정):** `apps/api/.../composition.py`, `main.py`, `apps/web/src/App.tsx`, `.github/workflows/ci.yml`, `pyproject.toml`/`uv.lock`, `packages/proofops/domain/rules/`(읽기만).
  - **메인 소유(수정 금지):** 태깅·판정·규칙·보고서·업로드 보안 코드. 대사는 이를 **읽기만** 한다.
- ⚠ 결합 위험: 스토어가 메인의 **비공개 멤버**(`self.jobs._get`, `self.jobs._raw`, `self.jobs._transaction`)와 `claims.current_tag`, `domain.rules.engine.MAPPINGS`에 의존한다(`reconciliation_store.py` `_reviewed_head`). 메인이 태그 헤드 구조를 바꾸면 여기서 깨진다 → 백로그 D-03.

### 3.2 도구
- Python ≥ 3.12(`.venv`는 3.12), `uv 0.12.x`. 설치: `uv sync --locked`.
- 대사 단위 테스트·검증 스크립트는 **Java가 필요 없다.** Java 21은 CI의 "실제 Java 파서 회귀"(`tests/acceptance/test_parsing.py` 등, 메인 파이프라인 쪽)용이다. 이 Mac에는 Java 25가 있어 그 회귀를 돌리려면 Java 21을 설치하고 `PROOFOPS_TEST_JAVA`를 지정해야 한다.
- Node(웹 타입체크·빌드)는 PR #10 기록상 Node 22.23.2. UI를 건드릴 때만 필요(이번에 웹 빌드는 실행하지 않음).

### 3.3 DART API 키 규칙
- 키는 **저장소 루트 `.env.dart.local`** 의 `DART_API_KEY=...` 한 줄. `.gitignore`가 `.env.*`를 막는다(`!.env.example`만 예외). 현재 메인 루트에는 이 파일이 **없다**(`.env.openai/openrouter/upstage/vercel.local`만 있음). 개발자 본인이 OpenDART에서 키를 발급받아 자기 환경에만 두는 것을 권장하고, 키를 채팅·로그·커밋에 공유하지 않는다.
- 수집 CLI는 `.env`를 자동으로 읽지 않는다. 명시 주입: `uv run --env-file .env.dart.local --no-sync python -m evaluation.reconciliation_collect ...` (키는 절대 명령줄 인자로 받지 않는다).
- **키 값을 출력하지 말 것:** `cat .env.dart.local`, `env | grep DART`, `set -x`, 디버그 로그에 URL 전체(`crtfc_key=` 포함) 출력 금지. 클라이언트는 `DartError` 메시지와 `repr`에서 키를 `[REDACTED]`로 지우지만, 호출 측 로그까지는 보장하지 않는다.
- 실제 DART 호출(네트워크)은 사용자 키·일일 한도를 쓰므로 **호출 전 사용자 확인**을 받는다. 개발·테스트는 주입형 전송 계층으로 오프라인에서 한다. 유료 모델 호출은 이 기능에 필요 없다(LLM 미사용).

### 3.4 테스트·검증 명령
```bash
# 개발 중 집중 검사 (약 10초)
uv run --no-sync python -m pytest tests/reconciliation -q -p no:cacheprovider

# 릴리스급 오프라인 검증 15개 게이트 (약 30초, 새 출력 폴더 필요, 기존 경로면 거부)
uv run python scripts/verify_reconciliation.py --output <새 임시 폴더> --timeout-seconds 600

# 개별: ruff / mypy (CI와 동일 범위는 verify 스크립트의 RECONCILIATION_PATHS 참조)
uv run --no-sync python -m ruff check packages/proofops/domain/reconciliation packages/proofops/adapters/dart
uv run --no-sync python -m mypy packages/proofops/domain/reconciliation packages/proofops/application/reconciliation packages/proofops/adapters/dart

# 문서·계약 검사(앱 테스트 아님)
python3 scripts/validate_package.py
```
`verify_reconciliation.py`는 (1) pytest(`tests/reconciliation` + `tests/acceptance/test_{rules,upload_security,upload}.py`) (2) ruff check (3) ruff format (4) mypy (5) product mypy (6) architecture, 그리고 합성 시나리오 8개(`contracts/reconciliation/examples/*.json`)를 CLI로 돌려 스키마와 기대 `execution_state/status`를 대조한다.

### 3.5 이번 검증 결과 (2026-10-08, 오프라인, 유료 0, 네트워크 0)
- 명령: `uv run python scripts/verify_reconciliation.py --output <scratch>/verify-out --timeout-seconds 600` in `r108-sprint1` @ `390c65b` (+ 대사와 무관한 미커밋 변경 13건).
- 결과: **`status: passed`, 15/15 통과**, 총 28.5초. 세부: pytest 868 passed / 12 skipped(전부 Windows Job Object 전용) · ruff check · ruff format(59개 파일) · mypy(29개 파일) · product mypy(4개 파일) · architecture · 픽스처 생성 · 합성 CLI 8건(`c1-difference-no-explanation`, `c1-different-entity-types`, `c1-same-entities`, `c1-search-incomplete`, `c2-same-period`, `c3-policy-unresolved`, `c4-definition-and-method`, `c4-search-incomplete`) 모두 기대 상태 일치.
- `pytest tests/reconciliation` 단독: 644 passed, 12 skipped.
- **이 숫자는 코드 계약과 합성 시나리오가 깨지지 않았다는 뜻이지 C1~C4 의미 정확도가 아니다.** 실행하지 않은 것: 웹 타입체크/빌드, 브라우저 E2E, Windows/macOS CI 매트릭스, 실제 Java 파서 회귀, 실제 DART 호출 → `not_run`.

---

## 4. 도메인 원칙 (동결 — 바꾸려면 사용자 결정 필요)

1. **LLM은 판정하지 않는다.** 이 기능은 LLM을 쓰지 않는다. 등급·라벨·`confidence`·`sublabel`은 결과 스키마에 키 자체가 없다(엄격 15키, `additionalProperties:false`).
2. **unknown / conflict / unreadable ≠ absent.** 검색이 완료(`complete`)로 증명되기 전의 "설명 없음"은 `needs_explanation`이 아니라 `blocked`(`search_incomplete`)다.
3. **검증된 원문 근거만 인정.** 모든 `sources[]`는 원본 바이트 해시 + 형식별 locator + 인용 문자열 재검증을 통과해야 한다. 해시만 맞아도 불충분.
4. **불변 revision.** 이전 revision·결과·보고서를 수정/삭제하지 않는다. 새 정책/재평가는 새 revision. 변경은 If-Match + Idempotency-Key.
5. **사람은 사실만 확인한다.** 검토자는 출처·사실·검색 범위를 확정할 수 있어도 결과 상태나 등급을 직접 고르지 못한다. 정책 승인은 admin만, 승인 레코드는 실제 행위자·시각·정책 해시를 남긴다. 가져온(import) 번들의 `approved`는 신뢰하지 않고 무효화한다.
6. **C5 실행 금지.** 스키마 1.1에 C5를 추가하지 않고 G/P/M과 섞지 않는다.
7. **합성 ≠ 실제.** `synthetic` 정책은 실제 패킷에 적용 불가(`synthetic_policy_real_packet`). 합성 승인으로 실기업 판정을 만들 수 없다.
8. **정책 값을 상상하지 않는다.** C3 임계값(예: 5.0배)은 `null`, CAPEX 계정 허용 목록은 빈 목록. 공식 조항·법적 효력·모델 ARN·성능 수치를 채워 넣지 않는다.
9. 숫자·목표연도에 문서 전역 근거를 무조건 인정하지 않는다(`docs/R00_DOMAIN_DECISIONS.md`, GAP-004).

---

## 5. R00 §12 채택 결정(REC-001~008)별 코드 반영과 남은 작업

출처: `docs/R00_DOMAIN_DECISIONS.md` 채택 표, 후속 목록 `outputs/agent-results/R86-record-decisions/NOTES.md`(우선순위 5·6). 기록 시점의 "실행 정책 등록 없음"은 지금도 같다(승인된 정책 레지스트리 항목 0건).

| ID | 채택 규칙 요지 | 코드 반영 | 남은 작업 (파일) |
|---|---|---|---|
| REC-001 A | 검증된 집합끼리, 기간·조직기준 일치 시만 비교. 시설↔법인은 **출처 검증된 명시적 통제/경계 관계**가 있을 때만 매핑. 미해결=blocked/null. 차이가 명시 설명되면 matched. | 🟡 `c1.py`: 정확 집합 일치, 기간(`c1_period_unresolved/mismatch`)·연결구분(`c1_consolidation_unknown`) 차단, 종류 다르면 `kind_mismatch` 차단, 빈 집합 차단. | 시설↔법인 **매핑 입력이 스키마 1.1에 없음**(PR #10 기록) → 스키마 1.2 또는 별도 `relation` 사실 정의 후 `common.py`·`input.schema.json`·`c1.py`·`service.py`. 결정 필요(§9 Q4). |
| REC-002 A | 설명=present는 같은 회사·기간의 **등록된 공시 패키지 안 정확 인용**이 비교 경계 차이와 명시 연결될 때만. 완전 검색+인용 없음→needs_explanation, 불완전/판독불가→blocked. | 🟡 `common.resolve_difference`, `service.reconcile`(설명 후보는 coverage에 등록된 source만, 역할 `explanation` 필수). | **설명 후보를 만드는 코드가 없음**(`_no_candidates`). 결정적(LLM 없음) 후보 추출 + "경계 차이와의 명시 연결" 표현 필요: `reconciliation_store.py`, `adapters/dart/candidates.py`, `service.py`. |
| REC-003 B | 재무제표 항목→CAPEX 운영자 승인 매핑, 같은 기간·통화 합산. 다년은 정확한 schedule이 있을 때만. | 🟡 `c3.py`: 승인 플래그·허용 계정 ID 전부 포함·통화·기간 일치 검사. `evaluation/reconciliation_source_audit.py`가 **미승인** 계정 초안(`include_in_capex=null`)만 생성. | 승인된 계정 목록(사람 결정) 입력 경로, 다년 schedule 표현(스키마 1.2). 승인 없이 합산 금지 유지. |
| REC-004 B | 임계값 `null` 유지, 임계값 기반 결과 차단, 매칭되는 투자약정 공시의 직접 존재만 matched. | ✅ `c3.py`: `commitment_source_id`가 있으면 `commitment_disclosed`로 matched, `c3_threshold is None`이면 `c3_policy_unapproved` 차단. | 없음(회귀 테스트 `tests/reconciliation/test_c3.py` 유지). 5.0배는 비활성. |
| REC-005 A | "설명 없음→needs_explanation"은 등록된 SR/FS 패키지 **모든 페이지·허용 주석**이 coverage에 있고 관련 페이지 판독 가능, 경계 있는 검색 manifest 완료일 때만. | 🟡 `service._apply_coverage`: 문서 단위 `required_document_ids`(SR·재무 둘 다 필수), 실패 문서 있으면 불완전. | **페이지/주석 단위 coverage manifest 없음.** 후보 상한 2,000 초과 시 완전 검색 불가 처리 포함: `candidates.py`, `service.py`, `schema.py`(coverage 모양). |
| REC-006 A | 실제 시작/종료일·연결범위 사용, **평가 기준일까지의 최신 정정 공시를 고정**하고 이전 버전·`rcept_no` 보존. 기간 불일치→blocked, 완전한 공식 조회 후 기간 동일 재무제표 없음→사유 있는 not_applicable. 연율화 금지. | 🟡 `identity.rcept_no/as_of_date`, `service._document_reason`(`document_not_available_as_of` 포함), `client.get_financial_statements(expected_rcept_no=…)`가 혼합 접수번호 거부. 연율화 없음. | **정정본 자동 선택·이력 보존 코드 없음**(`list_filings` 미사용). "완전 조회 후 없음→not_applicable(사유)" 경로 없음. `adapters/dart/`(신규 `filings.py`), `reconciliation_collect.py`. |
| REC-007 A | C4 matched는 같은 주장/기간 공시가 분류 **정의 + 포함·제외 근거 또는 분모**를 줄 때만. 완전 검색 후 없으면 needs_explanation, 관계 불명→blocked. 분류의 옳고 그름은 판단 안 함. | 🟡 `c4.py`: 정책의 `c4_required_explanations`(definition, calculation_basis) 각각 출처 id 필요, 검색 미완이면 `search_incomplete`. | "같은 주장·기간" 결속은 문서 레지스트리 `decision_binding`에 의존 — 분모 연도 불일치(예: 각주가 2023 북미 기준) 자동 판별은 없음. 사람 검토로 막고 있음. 후속: 기간 결속 검사 강화. |
| REC-008 A | `stage>CURRENT_STAGE`면 C5 전부 런타임 차단, 별도 `not_run` 봉투(`status=null`, `reason=stage_disabled`), 스키마 1.1·G/P/M에 섞지 않음. | ✅ 엔진·서비스·스토어·CLI 각각 차단(§2 C5 행), `tests/reconciliation/test_integration.py:207`. | 없음. 새 진입점(자동 생성기 등)에도 C5 차단 테스트를 반드시 추가. |

**정책 실행 등록:** 위 채택 규칙을 실제 `policy` JSON(`contracts/reconciliation/policy.schema.json`)으로 만들고 `source_policy_sha256`·승인자·승인 시각을 레지스트리에 등록한 기록은 **없다**(기아 인계 패키지에서도 "채택 문서만 있음 / 실행 등록 없음"). `config/accounting/reconciliation_rules.yaml`은 `status: draft, approved: false`.

---

## 6. 우선순위 백로그 요약 (상세는 `BACKLOG.csv`)

기준일 2026-10-08, 본선 2026-10-19(남은 11일). **P0 합계 약 40~48시간(1주 내외)**.

### P0 — 본선 전 "연결 가능" 최소 경로 (1순위)
목표: **한 건의 실제 메인 런 주장에서 출발해, 운영자 한 명이 명령 몇 개로 케이스를 만들고 화면에서 검토→정책 승인→평가→불변 revision 조회→원문 다운로드까지 갈 수 있게 한다.** 자동 판정 정확도는 목표가 아니다.

| ID | 내용 | 시간 |
|---|---|---|
| D-01 | `dart-dev` worktree 세팅, 검증 15/15 재현, origin/main 대사 문서 읽기 | 2h |
| D-02 | 회사→`corp_code` 연결 테이블(대사 전용, 메인 스키마 불변) + 운영자 명령, 형식·중복 검증 | 6~8h |
| D-03 | 메인 비공개 API 의존 고정 계약 테스트 + 가능하면 공개 어댑터 한 겹 | 4h |
| D-04 | 접수번호 확정 도우미: `list_filings` → 정기 사업보고서·정정본 목록 → **운영자가 선택해 pin**(자동 선택 금지) + 응답 해시 보존(REC-006) | 8~10h |
| D-05 | 주장→케이스 초안 한 번에 만들기(`claim` + 확정 태그 + corp_code + pin된 rcept_no → 번들 → 등록). `linkage_exchange.build_packet`과 `reconciliation_prepare` 갈래 통합 | 12~14h |
| D-06 | 연결 스모크: 합성 런 + HTTP + SQLite(+가능하면 브라우저)로 D-05 경로 end-to-end, G/P/M 출력 불변 확인 | 6h |
| D-07 | 기능 플래그(기본 OFF): 메인 팀이 제출본에서 대사 라우트·링크를 끌 수 있게 | 2~3h |

### P1 — 연결 후 정확도·결정 반영
D-08 정책 실행 등록 도구(REC 채택 → 실제 policy JSON, 승인은 admin UI) · D-09 설명 후보 결정적 추출(REC-002/005) · D-10 페이지/주석 단위 coverage manifest · D-11 후보 상한 truncated 정책 · D-12 기간 결속 강화(C4/C2) · D-13 스키마 1.2 초안(시설↔법인, 다년 CAPEX; 승인 후)

### P2 — 평가·확장
D-14 gold 정의와 기아 CSV 8행 평가 어댑터 · D-15 보고서/내보내기 노출 설계(결정 후) · D-16 DART 클라이언트 보강(한도·재시도 관측성) · D-17 CI/문서 정리

각 항목의 목표·파일·수용 기준·테스트는 `BACKLOG.csv`. 항목마다 "실행하지 않은 것 = not_run" 표기를 PR에 남길 것.

---

## 7. 메인 파이프라인 연결 계약

### 7.1 대사가 메인에서 **받는** 입력 (읽기 전용)
| 입력 | 출처(메인) | 사용처 |
|---|---|---|
| `tenant_id`, `run_id`, `claim_id` | 인증 세션·런·주장 저장소 | 케이스 신원, 교차 테넌트는 404 |
| `company_id`, `sustainability_document_version` | 런 스냅샷 `document.company.company_id`, `claim.document_version_id` | `identity` 일치 검사(`CASE_IDENTITY_MISMATCH`) |
| 주장 `quote`, `track`, 원문 위치·`source_sha256`, `source_quality=="verified"` | `claims.get`, 확정 태그 헤드 | 패킷 `claim`, `CLAIM_BINDING_MISMATCH`, 미검증 주장은 `CLAIM_NOT_VERIFIED` |
| 확정 태그의 트리거 사실(조직경계·이행범위·정량값·금액·매출비중)과 근거 ref | `domain.rules.engine.ConfirmedTags` → `linkage_exchange.TRIGGER_TAG_MAP` | 어떤 C항목이 트리거되는지, SR 쪽 값(`raw/normalized/kind/unit`) |
| 현재 태그 헤드 revision·mutation epoch | `claim_head`(원자 읽기) | 케이스가 어떤 태깅 입력을 근거로 했는지 보존 |
| `local_synthetic` | 런 문서 | `synthetic` 일치 강제 |
| 보고 기간(`period_start/end`), SR 공시일(`sr_published_at`), 연결/별도 | 현재는 **운영자 입력** | C1/C2 비교 기준. 메인에 확정 필드가 없다(§9 Q3) |
| SR 원본 바이트 | 업로드 저장소(해시 검증) | `sources[]` 재검증 |

대사 쪽이 **직접 가져와야** 하는 것(메인에 없음): `dart_corp_code`, `rcept_no`, 재무 기간, 재무 문서 원본, 재무 쪽 값.

### 7.2 대사가 **내는** 출력
- **엄격 결과 1.1(15키)**: `schema_version, claim_id, item, execution_state(completed|blocked), status(matched|needs_explanation|not_applicable|null), review_required, reason_codes[], source_ids[], explanation_source_id, sustainability_value, financial_value, packet_sha256, policy_sha256, synthetic, engine_version`. `engine_version`은 상수가 아니다: `reconciliation-engine-1.2.0`(엔진 도달) 또는 `reconciliation-application-provenance-1`(검증 경계에서 선차단) 둘 다 정상이다.
- **표시 봉투** `reconciliation-presentation-1`(별도 버전): 한글 설명 문구, 출처 참조(시스템·corp_code·FY·수집시각), 검증 상태 `verified/not_verified`. 고지문: "회계 처리의 적정성을 판단하지 않으며, 공시 간 차이에 대한 설명의 존재 여부만 점검".
- **CaseDetail**(UI/API): `case_id, run_id, claim_id, item, revision, synthetic, review_state(pending|reviewed), policy_approved, packet, policy, sources, latest_result`. ETag=`"<revision>"`. 평가는 HTTP 성공이어도 결과가 blocked일 수 있다.
- 저장: `reconciliation_*` 테이블 4종 불변(case/revision/source/idempotency) + head. 롤백=라우터/UI 비활성화(스냅샷 보존).

### 7.3 메인 쪽에서 필요한 최소 변경 (누가·어느 파일)
| 변경 | 담당 | 파일 | 필수? |
|---|---|---|---|
| 없음 — 서버 운영자 경로(CLI 등록)는 현재도 동작 | — | — | 필수 변경 0 |
| 대사 기능 플래그(기본 OFF) 읽기 | 메인 담당자 승인 후 DART 개발자 | `apps/api/src/proofops_api/composition.py`, `main.py`, `apps/web/src/App.tsx:282` 링크 조건 | 제출본 안정성용(권장) |
| 회사 `corp_code`를 메인 회사 레코드에 두는 안 | 메인 | 런/회사 스냅샷 스키마 | **비권장** — 대사 전용 링크 테이블로 메인 스키마 불변 유지(D-02) |
| 주장 상세의 대사 상태 배지(없음/검토 대기/완료) | 메인 + DART | `App.tsx`, 대사 목록 API | 선택 |
| 보고서·내보내기 포함 | 메인 | `routers/exports.py` 등 | 선택, 별도 결정(등급 오염 금지) |

### 7.4 연결 시점 판단 기준 (모두 만족해야 "메인에 연결")
1. `dart-dev`를 최신 `r108-sprint1`에 rebase한 뒤 `verify_reconciliation.py` **15/15** + 메인의 기존 회귀(`tests/acceptance/test_rules.py` 등)가 그대로 통과.
2. 같은 런에서 **대사 사용 전/후 G/P/M 등급·보고서 바이트가 동일**함을 확인(오염 0).
3. D-05 경로로 실제 메인 런의 주장 1건 이상이 케이스→검토→정책 승인→평가→revision 조회→원문 다운로드까지 사람이 재현 가능(단, 정책 승인자·실제 DART 호출은 사용자 승인 하에).
4. 기능 플래그 OFF에서 메인 동작이 변하지 않고, ON에서도 대사 실패가 메인 요청을 깨뜨리지 않음(격리).
5. 표시 문구에 정확도·준법 주장이 없음(합성/미승인/미검증 표시 유지).
6. **시간 기준(제안):** 2026-10-16(본선 3일 전)까지 1~5가 충족되지 않으면 이번 제출본에는 연결하지 않고(플래그 OFF·링크 숨김) 계속 개발. 충족되면 메인 담당자 리뷰 후 병합.

---

## 8. 위험

| 위험 | 영향 | 완화 |
|---|---|---|
| 메인 작업 트리가 빠르게 변함(태깅·claims) | rebase 충돌, `_reviewed_head`가 비공개 API 의존으로 깨짐 | 소유 경로 제한, D-03 계약 테스트, 2~3일 rebase |
| 후보 상한 2,000건 도달 → 전체 검색 불완전 | `needs_explanation`을 확정할 수 없음(blocked 지속) | D-10/D-11, 상한 도달 시 UI에 명시 |
| 정정공시 | 최초 vs 정정 `rcept_no` 불일치로 수집 차단(동서 실례) | D-04 pin 도구, 두 문서를 섞지 않음 |
| gold 없음 | 정확도를 말할 수 없음 | 기계적 검사와 의미 정확도를 분리 보고, D-14 |
| 실기업 데이터 권리 | 기아 SR PDF 재배포 권리 **pending**, 과거 시험 권리 프로필 2026-09-25 만료 | PDF·원문을 커밋하지 않음, 권한 확인 후에만 사용 |
| 실기업은 `synthetic=false`가 필요 | 신뢰된 회사 신원 없으면 `unresolved_company_identity`로 차단 | D-02에서 신원 연결을 사람이 확정 |
| 스키마 1.1 한계 | 시설↔법인, 다년 CAPEX 표현 불가 | 보수적으로 blocked 유지, Q4 결정 후 1.2 |
| DART 키 노출 | 보안 사고 | §3.3 규칙, 로그 점검 |
| 같은 이름 다른 법인 | 잘못된 corp_code 연결 | 운영자 확인 + FY/연결구분/접수번호 신원 일치 검사(이미 서비스에 있음) |
| 로컬 SQLite 전제 | 클라우드 배포 시 재설계 | 이번 범위 아님(배포 대상 미정) |

---

## 9. 결정이 필요한 질문 (사용자/메인 담당자)

1. **Q1 범위:** 본선 전 연결 목표는 (a) 기아 FY2024 C2 한 건 같은 **단일 시연 경로**인가, (b) C1~C4 전체 경로인가? (백로그 순서가 달라짐. 제안: a)
2. **Q2 케이스 생성 방식:** 운영자 CLI(현행·안전)로 유지하나, 관리자 HTTP 엔드포인트로 "주장에서 케이스 생성"을 열 것인가? (클라이언트 파일경로·레지스트리를 받지 않는 서버 소유 방식이어야 함)
3. **Q3 `corp_code`/보고기간의 소유:** 대사 전용 링크 테이블(제안) vs 메인 회사 레코드 필드 추가. 보고기간·연결구분·SR 공시일의 확정 출처는 누구인가?
4. **Q4 스키마 1.2 허용 여부:** 계약은 "1.1 불변"이다. REC-001 시설↔법인 매핑, REC-003 다년 CAPEX를 위해 1.2를 열어도 되는가? 안 열면 해당 케이스는 계속 blocked.
5. **Q5 정책 승인자:** REC-001~008을 실제 `policy`로 등록할 때 승인자(admin)는 누구이며, C1 동일성·C3 계정 허용·C4 필수 설명의 최종 값은?
6. **Q6 실기업 사용 범위:** 어느 회사/보고서를 실제 시연에 쓰는가(권리 상태 포함)? 기아 등록 run을 새로 만들 것인가(현재 시험 run은 synthetic·corp_code null)?
7. **Q7 DART 호출 승인:** 개발자 본인 키 사용, 일일 호출량, 수집 원문의 로컬 보관·재배포 범위.
8. **Q8 UI·보고서 노출:** 제출본에서 대사 링크를 보이게 할지, 보고서/내보내기에 포함할지, 플래그 기본값(제안: OFF).
9. **Q9 Git 전략:** `dart-dev`를 push해도 되는가? PR 대상 브랜치(`r108-sprint1` vs `main`)는? PR #7(OPEN)은 정리/닫기할 것인가?
10. **Q10 gold 확정 주체:** R82 결정 요청 #1과 동일 — 누가 기대값을 승인하는가(승인자·행·근거·시각 기록).
11. **Q11 문서 복원:** `origin/main`에만 있는 `docs/RECONCILIATION*.md`를 `dart-dev`에 되살려도 되는가(r108에서 의도적으로 뺀 것인지 불명)?
12. **Q12 기아 C4:** 전문가 CSV에 C4가 없다. C4 시연 기대값은 누가 정하는가?

---

## 10. 읽을 자료 (순서)

1. 이 문서 → `docs/RECONCILIATION_PRODUCT_CONTRACT.md`(보유) → `git show origin/main:docs/RECONCILIATION_HANDOFF.md`, `…RECONCILIATION_PRODUCT.md`
2. `docs/R00_DOMAIN_DECISIONS.md` (REC 채택 표) + `outputs/agent-results/R86-record-decisions/NOTES.md`(구현 후속 순서)
3. 코드: `domain/reconciliation/engine.py` → `c1~c4.py` → `application/reconciliation/service.py` → `adapters/local/reconciliation_store.py` → `adapters/dart/candidates.py`
4. 계약/예시: `contracts/reconciliation/*.schema.json`, `examples/*.json`, `product.openapi.yaml`
5. 이전 개발자 B 패키지: `outputs/developer-b-handoff-20260929/`(`REQUEST.md`, `kia-b-followup-handoff/README.md`·`REPLY.md`), R82(데이터 관리자 회신, gold 결정 요청), R84(정책 초안·출처 한계: KSSB 대응 조항·법적 효력·SASB 배포권·5.0배는 **미검증**). `developer-b-real-company-20260922.zip`은 NAVER 인계본(24개 파일: C1/C2 번들 예시, 청구서 JSON 3, `integration.patch` 등) — 기아에 ID 재사용 금지.
6. PR #7/#10 본문(`gh pr view 7 10 -R tskwak111/esg-proofops`).

> 이 인계서는 앱 코드를 수정하지 않았고 유료 API·DART 호출·push를 하지 않았다. 검증은 오프라인 15개 게이트만 실행했다.
