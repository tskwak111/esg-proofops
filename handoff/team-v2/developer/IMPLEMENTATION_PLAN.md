# 전체 연계 모듈 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** C1~C4 독립 모듈 및 DART·설명 검증·CLI. C5 실행 차단.
**Architecture:** domain은 순수 함수, application은 검증·Ports, adapters는 I/O. 제품 통합은 A.
**Tech Stack:** Python3.12, 기존 uv lock, jsonschema/pytest/httpx 또는 stdlib.
**Spec:** PLAYBOOK.md, ../contract/CONTRACT.md, ../SCOPE_MATRIX.md.

## Global Constraints
기존 grade/label 불변. source 실재·귀속 검증 필수. unknown은 absent가 아님. live policy 미승인시 보류.

각 REC마다: 아래 의미의 failing test 작성 → 실제 실패 확인 → 최소 구현 → 검사 통과 → commit.
표의 파일은 생성 예정이며 이 패키지가 이미 구현했다는 뜻이 아니다.

| 작업 | 선행 | 파일 | 첫 실패 테스트 | 전달 결과 |
|---|---|---|---|---|
| REC01 | 없음 | domain/reconciliation/engine.py, tests/reconciliation/test_contract.py | C5 직접 호출 예외, 미승인 정책 blocked | evaluate 입출력 |
| REC02 | REC01 | adapters/dart/client.py,normalization.py,artifacts.py; tests/reconciliation/test_dart.py | 다른 회사 응답과 초과 ZIP 거부 | 수집 artifact+source |
| REC03 | REC01 | application/reconciliation/service.py,ports.py; tests/reconciliation/test_identity.py | 다른 tenant/회사/FY 혼입 거부 | 정본 packet 검증 |
| REC04 | REC02,03 | application/reconciliation/explanations.py; tests/reconciliation/test_sources.py | 인용 실재하나 다른 기간이면 거부 | 검증된 설명 후보 |
| REC05 | REC03,04 | domain/reconciliation/c1.py; tests/reconciliation/test_c1.py | 같은 개수 다른 법인 집합이 matched 아님 | C1 |
| REC06 | REC03,04 | domain/reconciliation/c3.py; tests/reconciliation/test_c3.py | 약정 부재만으로 needs_explanation 금지 | C3/정책 보류 |
| REC07 | REC03,04 | domain/reconciliation/c2.py,c4.py; tests/reconciliation/test_c2_c4.py | 기간 시차 설명 인정, 다른 분류 정의 거부 | C2/C4 |
| REC08 | REC05,06,07 | evaluation/reconciliation_cli.py; tests/reconciliation/test_cli.py | JSON roundtrip와 grade 유입 거부 | CLI·검증 보고 |

테스트 시작 예 (아직 함수가 없으므로 처음에는 import 오류로 실패):
```python
import json
from pathlib import Path
import pytest
from proofops.domain.reconciliation.engine import evaluate
ROOT = Path('handoff/team-v2/contract')
def test_unapproved_policy_blocks():
    p = json.loads((ROOT/'example-input.json').read_text())
    r = json.loads((ROOT/'example-policy.json').read_text())
    r['approved'] = False
    result = evaluate(p, r)
    assert result['execution_state'] == 'blocked'
    assert result['status'] is None
    assert 'policy_unapproved' in result['reason_codes']
def test_stage_guard():
    p = json.loads((ROOT/'example-input.json').read_text())
    p['item'] = 'C5'
    with pytest.raises(NotImplementedError):
        evaluate(p, json.loads((ROOT/'example-policy.json').read_text()))
```
가드 순서: 내부 직접 C5 진입 차단 → schema 검증 → 정책/원문/적용성 → 해당 엔진.
HTTP에서 malformed 입력은 4xx로 변환하고 traceback/키를 노출하지 않는다.

완료 명령:
```bash
uv run python handoff/team-v2/contract/validate.py
uv run pytest tests/reconciliation tests/acceptance/test_rules.py -q
uv run ruff check packages/proofops/domain/reconciliation packages/proofops/application/reconciliation packages/proofops/adapters/dart evaluation/reconciliation_cli.py tests/reconciliation
uv run mypy packages/proofops/domain/reconciliation packages/proofops/application/reconciliation packages/proofops/adapters/dart
uv run python scripts/verify_architecture.py
uv build --package proofops
```
