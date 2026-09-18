# Reconciliation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 등급에 영향을 주지 않는 독립 C1/C3 연계 모듈과 CLI.
**Architecture:** 기존 단일 Python 패키지의 순수 domain + application Ports + DART adapter. A가 제품 API/DB/UI를 통합한다.
**Tech Stack:** Python 3.12, 기존 uv lock, pytest/jsonschema; 표준 라이브러리 우선.
**Spec:** ../contract/CONTRACT.md, ../reference/RECONCILIATION_SPEC.md, ../TEAM_PLAN.md.

## Global Constraints
LLM은 설명 후보 탐색만. C5 runtime 차단. label/evidence_grade 변경 금지.
unknown/conflict/unreadable은 부재가 아니다. C3 미승인 임계값 실행 금지.
새 의존성·공유 계약·lock은 A 승인 및 통합 소유. B 경로 밖 변경 금지.

## REC-01 · 입력·출력과 단계 차단
Files: domain/reconciliation/{__init__,engine}.py, tests/reconciliation/test_contract.py.
Consumes: input schema 1.0 + policy.json. Produces: evaluate(packet, policy)->output schema 1.0.
- [ ] 다음 테스트를 먼저 작성하고 함수 미구현으로 실패하는 것을 확인한다.
```python
import copy
import json
from pathlib import Path
import pytest
from proofops.domain.reconciliation.engine import evaluate
ROOT = Path('handoff/2026-09-18/contract')
def test_unapproved_policy_blocks():
    packet = json.loads((ROOT/'example-input.json').read_text())
    policy = json.loads((ROOT/'example-policy.json').read_text())
    policy['approved'] = False
    result = evaluate(packet, policy)
    assert result['execution_state'] == 'blocked'
    assert result['status'] is None
    assert 'policy_unapproved' in result['reason_codes']
def test_stage_two_is_not_executable():
    packet = json.loads((ROOT/'example-input.json').read_text())
    packet['item'] = 'C5'
    with pytest.raises(NotImplementedError):
        evaluate(packet, json.loads((ROOT/'example-policy.json').read_text()))
```
- [ ] `uv run pytest tests/reconciliation/test_contract.py -q`
- [ ] schema 검증·C5 가드·미승인 정책 보류를 구현. 합성 승인 정책을 live 승인으로 사용하지 못하게 한다.
- [ ] 잘못된 status, 추가 grade, 잘못된 hash와 다른 tenant를 거부하는 테스트 추가 후 통과.
- [ ] 파일을 명시해 stage하고 `feat: define isolated reconciliation boundary`로 commit.

## REC-02 · DART 수집과 공시 식별
Files: adapters/dart/{__init__,client,normalization}.py, application/reconciliation/ports.py,
tests/reconciliation/test_dart.py, evidence/reconciliation/availability.md.
Consumes: corp_code, period_start/end, rcept_no, consolidation. Produces: raw artifact + normalized source/facts.
- [ ] fixtures로 HTTP 제한/재시도, 비정상 XML·ZIP, 정정 버전, 다른 기업/기간 응답의 실패 테스트.
- [ ] timeout·응답 크기/압축 해제 크기 상한·허용 host·키 마스킹·명시적 오류를 최소 구현.
- [ ] API key를 fixture/로그/URL 출력에 남기지 않는 테스트를 통과.
- [ ] 허가된 공개 기업 3~5곳의 종속기업·약정·CAPEX 항목 가용성을 실제 조회. 키가 없으면 live=not_run.
- [ ] 조회 완료와 데이터 없음/실패를 구분하고 원본 hash·접수번호·시점을 기록.
- [ ] `uv run pytest tests/reconciliation/test_dart.py -q` 후 commit.
주석이 API에 없으면 XBRL/본문의 해당 영역만 읽고 원문 locator 보존. 파싱 실패를 빈 목록으로 반환 금지.

## REC-03 · C1 + 설명 검증
Files: domain/reconciliation/c1.py, application/reconciliation/{service,explanations}.py,
tests/reconciliation/test_c1.py.
Consumes: verified identity/facts/source refs + approved difference policy. Produces: C1 result.
- [ ] 아래 독립 경계별 실패 테스트를 만든다.
  1. 사업장 수 vs 법인 수 → not_applicable/not_comparable.
  2. 같은 수이지만 법인 목록이 다름 → matched 아님.
  3. 다른 연도의 설명 문구 → 인용 승인 안 됨.
  4. 정확한 차이 설명+원문 검증 → matched.
  5. 설명 null+검색 미완료 → blocked, status null.
  6. 비교 가능한 차이+승인된 coverage 충족+설명 없음 → needs_explanation.
  7. 허위 source_id/quote → blocked, review_required.
- [ ] 비교→설명탐색→실재/귀속 검증→상태 결정을 분리해 최소 구현.
- [ ] `uv run pytest tests/reconciliation/test_c1.py -q` 후 합성/실데이터 결과를 구분해 기록·commit.

## REC-04 · C3 정책과 회계 경계
Files: domain/reconciliation/c3.py, config/accounting/reconciliation_rules.json,
tests/reconciliation/test_c3.py.
Consumes: 승인된 계정·단위·기간·threshold 정책과 원문 약속/약정. Produces: C3 result or blocked.
- [ ] 약정 주석에 없기만 한 사례가 needs_explanation이 되지 않는 테스트를 먼저 작성.
- [ ] CAPEX 결측/0/음수, 통화/기간 불일치, 미승인 임계값은 자동 비율 판정 금지 테스트.
- [ ] 승인 정책이 준비된 branch만 구현. 정책 미정은 보류하고 숫자를 하드코딩하지 않는다.
- [ ] 회계 타당성 평가를 유도하는 최소 10개 사례에서 금지 결론을 내리지 않는 테스트.
- [ ] `uv run pytest tests/reconciliation/test_c3.py -q` 후 commit.

## REC-05 · CLI와 통합 전달
Files: evaluation/reconciliation_cli.py, tests/reconciliation/test_cli.py,
evidence/reconciliation/verification.md.
Consumes: packet/policy JSON. Produces: output JSON + exit code. stdout에 키/원본 덤프 금지.
- [ ] CLI fixture round-trip, 실패 exit code, output schema, 기존 등급 필드 미포함 테스트를 먼저 작성.
- [ ] 기본 offline CLI 구현. 기존 모델 provider를 새로 만들지 않고 설명탐색 Port로 연결한다.
- [ ] 다음 명령 실행·결과 기록:
```bash
uv run python handoff/2026-09-18/contract/validate.py
uv run pytest tests/reconciliation tests/acceptance/test_rules.py -q
uv run ruff check packages/proofops/domain/reconciliation packages/proofops/application/reconciliation packages/proofops/adapters/dart evaluation/reconciliation_cli.py tests/reconciliation
uv run mypy packages/proofops/domain/reconciliation packages/proofops/application/reconciliation packages/proofops/adapters/dart
uv run python scripts/verify_architecture.py
uv build --package proofops
```
- [ ] actual DART/model 미실행은 not_run으로 명시. 회귀·원문·권리·실측 오류와 비용 보고.
- [ ] A에게 PR 제출. 전체 lint/type/unit/integration/contract/build/E2E/security는 A의 통합 게이트에서 실제 실행.
