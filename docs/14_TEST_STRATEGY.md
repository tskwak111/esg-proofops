# 14 · 테스트·평가 전략

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 검증 층위
| 층 | 실행 대상 | 필수 사례 | 완료 판단 |
|---|---|---|---|
| Unit | 순수 rules, geometry, hashes, numeric, consensus | E0–E3 경계, AND/OR, offset, Decimal, replica 분리 | deterministic assertions 전부 통과 |
| Contract | JSONSchema/OpenAPI/Ports/fixtures | unknown enum, extra grade, 누락 bbox, DTO 대응 | schema 와 응답 diff 없음 |
| Integration | S3+DDB+SQS+OpenSearch adapters | publish 순서, lease, tenant filters, outbox retry | AWS staging 또는 명시 local fake 와 별도 구분 |
| API | FastAPI+auth |401/403/404/409/412/422/429/503 | contract status/body/권한 일치 |
| Component | React | loading/empty/error, keyboard, draft 보존 | Vitest/Testing Library |
| E2E | browser→upload→run→review→export | 부분실패, 재로그인, 다른 tenant, 동시 review | Playwright screenshot+assert |
| AI evaluation | parser→claim→evidence→grade | 독립 source-anchored gold | 요소/회수/귀속/보증/등급 각각 보고 |
| Load/fault |20동시 조회·2run/tenant, worker kill | SQS duplicate, slow model, DDB throttle | 데이터 손실·결과 덮기0, 지연 실측 |
| Security | tenant leakage, injection, PDF abuse | id 변경, source URL 위조, CSV formula | 타 tenant 접근0, secret log0 |

## 2. Golden fixture 와 실제 골드
`fixtures/rule_cases.json`은 원문 사다리에서 직접 도출한 **합성 계약 테스트**다. 실제 PDF 인식 정확도 gold 가 아니다. `fixtures/edge_cases.json`은 실패 동작의 수용 기준이며 실제 통과 증거는 구현 테스트에서 생성한다. 기존 저장소의5개사180행은 개발 silver 로만 출발한다. 기존 grader replay 와 새 PDF-to-grade 성능을 혼동하지 않는다.

데이터는 company_id 단위로 development/fewshot, validation, holdout 분리하고 보고연도만 다르다고 다른 회사 split 으로 보내지 않는다. 사람이 실제 PDF 의 source span/셀·지표·기간·경계를 독립2인 태깅하고 불일치는 제3자 또는 합의 조정하되 최초 태그를 보존한다. grade 정답은 확정된 요소에 동결 규칙을 적용해 만들며 규칙 gap 사례를 억지로 E-class 에 넣지 않는다.

## 3. 지표 정의
- Claim recall=gold atomic claims 중 매칭된 claim 수/gold claims. 전수 범위·선언 부분 범위를 구분한다.
- Element precision/recall: `(claim_id, element_id, normalized_value, valid_source_binding)` 단위. 존재 여부만 맞고 다른 사업장 수치를 가져오면 오답이다.
- Parsing: 한국어 reading order, table cell tuple(지표/연도/경계/단위/값) exact, coordinate hit, table recall. 구조 F1과 숫자 정확도를 분리한다.
- Retrieval Recall@12: 허용 source gold 가 top12에 있는 비율; global 금지 근거는 hit 로 세지 않는다.
- Assurance: covered 정밀도와 false-covered count, not_covered/undetermined confusion.
- Grade: E0~E3 macroF1/ordinal confusion, 3라벨 macroF1/다수클래스 기준선. 검토 대기 제외 selective metric 과 전체 자동 확정 coverage 를 함께 보고한다.
- Human agreement: ordinal grade weighted kappa 와 요소별 agreement, 최초 독립 태깅 기준. 사람 일치도를 모델의 절대적인 성능 상한이라고 단정하지 않는다.
- Operating: 자동 확정률, 검토자 수정률, 검토시간, doc 당 비용·호출·실패, stage 별 latency.

## 4. P0 엔지니어링 출시 게이트
기계적 게이트: 등급 함수 재현성100% fixture 일치, 잘못된 citation/tenant/bbox 를 accepted 로 publish 한 사례0, 혼합 snapshot0, SQS duplicate 부작용0, 원문 없는 수치 생성0. 이는 범위가 명시된 테스트의 통과 기준이지 실제 전체 PDF 가100% 정확하다는 뜻이 아니다.

실데이터 자동 확정 기능의 초기 목표(새로 제안한 개발 기준): 독립 validation 에서 accepted element precision≥0.98, claim recall≥0.90, grade macroF1≥0.85, critical numeric tuple accuracy≥0.99. 최소 표본은 gold claim100개, element200개, numeric tuple100개, assurance negative50개다. 표본이 작으면95% 신뢰구간을 반드시 병기하며 통계적 보장으로 홍보하지 않는다. 목표 미달 시 domain ladder 를 낮추지 않고 관련 자동 확정 gate 를 닫아 review 로 보낸다. holdout 결과를 보고 threshold 를 맞춘 후 같은 holdout 으로 최종 성능을 주장하지 않는다.

## 5. 회귀·ablation
동일 split 에서 OD-only, OD+표보조, OD+표보조+vision, 전체 binding+review 순서로 비교한다. Docling 기반 두 경로를 독립 표로 세지 않는다. LLM3회 vs1회는 동일 packet 으로 비교하고 정확도뿐 아니라 callcost/reviewload 를 보고한다. tagging/rule/parser 변경마다 해당 단계 입력·출력·version 을 보관한다. 새로운 rulepack 은 기존 태깅으로 replay 할 수 있는 사례와 retag_required 사례를 분리한다.

## 6. 구현 후 실행 계약
현재 로컬 구현에서 실행할 검증 명령은 다음과 같다.

```bash
uv run ruff check packages apps scripts tests evaluation
uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src
uv run pytest tests/unit tests/contracts tests/integration tests/acceptance tests/security -q
uv run python scripts/verify_architecture.py
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
```

브라우저 검증은 `tests/e2e/local_browser_server.py`의 명시적 합성 실행과
`tests/e2e/*_check.mjs`를 사용한다. Orca 브라우저에서 실제 화면·API 요청·경합을
검증한 명령과 결과는 `evidence/local-review-web.md` 등 해당 작업 증거에 기록한다.
Vitest/Playwright 전용 실행 명령은 아직 설치되지 않았으므로 통과했다고 표시하지 않는다.
규칙팩 CLI는 별도 메타데이터 JSON을 필수로 받는다:
`uv run python scripts/verify_rulepack.py --pack <pack.json> --config-dir config`.
저장소의 draft YAML은 승인된 실행 규칙팩이 아니며, CLI의 실제 동작과 거부 사례는
규칙팩 수용 테스트로 검증한다. 메타데이터 없이 CLI를 실행한 오류를 규칙팩 검증 통과로 세지 않는다.
실제 파서 테스트는 Java 21이 필요하다. `PROOFOPS_TEST_JAVA`로 실행 파일을
지정할 수 있으며, CI는 Ubuntu 이미지의 `JAVA_HOME_21_X64/bin/java`를 사용한다.
AWS/LLM 호출 테스트는 비용·동의·환경 승인 없이는 실행하지 않으며 `not_run`으로 남긴다.
`scripts/validate_package.py`는 문서·계약 검사이며 위 앱 테스트를 대신하지 않는다.
