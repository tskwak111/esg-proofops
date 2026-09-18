# 개발자 B 시작 안내

당신은 DART 데이터와 검증된 환경 주장 사이의 C1/C3 연계 모듈 담당이다.
판정 질문은 “차이를 설명하는 문구가 있는가”다. 회계 타당성·허위 여부를 판정하지 않는다.

## 준비
Python 3.12, uv, Git 필요. B의 독립 테스트에는 Java·Node·AWS·모델 키가 필요하지 않다.
기존 전체 PDF/웹앱 검증에는 Java 21, Node 22, pnpm 10.0.0이 별도로 필요하다.

```bash
git clone https://github.com/tskwak111/esg-proofops.git
cd esg-proofops
git switch -c feature/reconciliation
uv sync --locked
uv run python handoff/2026-09-18/contract/validate.py
uv run pytest tests/acceptance/test_rules.py -q
```

순서대로 읽기: AGENTS.md → docs/00_MASTER_SPEC.md → sources/PROJECT_DOMAIN_V2_ORIGINAL.md
→ docs/26_LEGACY_REUSE_AUDIT.md → docs/27_PARSING_AND_PROVENANCE.md
→ docs/28_RULE_ENGINE_CONTRACT.md → docs/31_DOMAIN_IMPLEMENTATION_GAPS.md
→ docs/19_IMPLEMENTATION_PLAN.md → 이 패키지 TEAM_PLAN/CONTRACT/IMPLEMENTATION_PLAN.
reference의 v2.2와 모듈 명세는 C군 추가 근거다. 기존 코드가 이미 C군을 구현했다고 가정하지 않는다.
기존 Task-000부터 재구현하지 말고 신규 REC 작업을 진행한다.

## 첫날 완료할 것
1. 계약 validator와 기존 rules 테스트를 실행하고 결과를 남긴다.
2. synthetic packet을 읽고 반환 fixture의 status/review 의미를 설명한다.
3. DART 필요한 주석별 “API 가능 / 원문 읽기 필요 / 미확보” 가용성 표를 만든다.
4. C5 차단과 비교 불가능 사례의 실패 테스트부터 만든다.

## 기존 코드 재사용 위치
- domain/numeric.py: Decimal·수치 및 범위 검증 개념. 네트워크를 끌어오지 않는다.
- domain/provenance.py: canonical_hash.
- application/evidence/retrieval.py: 동일 문서 제한을 유지. 전역적으로 풀지 않는다.
- domain/rules/engine.py: read-only. C군 때문에 grade를 바꾸지 않는다.
- domain/periods.py: 문자열 형식 검사일 뿐 실제 회계연도 대응 승인이 아니다.

## 개발 종료 시 제출
브랜치/commit, CLI 재현 명령, tests/reconciliation 결과, lint/type 결과, 원본·규칙·packet 해시,
실제 DART 제공 범위, 모델 호출 여부와 비용, 남은 규칙 gap을 포함한 PR을 준비한다.
PDF·전체 DART 응답·개인 키·고객정보는 PR에 넣지 않는다.
제품 성능은 별도 gold 평가 결과로 보고한다. 합성 fixture 통과는 성능 수치가 아니다.
