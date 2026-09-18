# 개발자 B · 처음부터 따라가기

전체 담당은 DART 수집 + 공시 대응 + C1/C2/C3/C4 + 설명 원문 검증 + 독립 CLI입니다.
C1/C3부터 구현하지만 C2/C4를 삭제하지 않습니다. C5는 실행 차단 기능만 만듭니다.
이 패키지는 실서비스 엔진 구현물이 아니라, 만들 기능의 계약·예제·검증 도구입니다.

## 0. 용어
- claim: 검증 가능한 하나의 주장. 한 문장에 여러 claim이 있을 수 있음.
- packet: 한 claim을 판단할 때 필요한 입력을 JSON으로 고정한 묶음.
- source_ref: 어떤 원본의 어디에서 읽었는지를 가리키는 참조.
- policy: 사람이 승인한 비교/적용 규칙. 모델이 생성하는 답이 아님.
- adapter: 외부 API·파일을 읽어 내부 형식으로 바꾸는 코드.
- pure function: 같은 입력이면 같은 출력. 함수 안에서 네트워크·시간·파일을 읽지 않음.
- fixture: 코드 검사용 고정 예제. synthetic fixture는 실제 정답 데이터가 아님.
- blocked: 판단에 필요한 자료·규칙을 확인 못함. 틀린 주장이라는 뜻이 아님.

## 1. 설치와 첫 검증
Git, Python3.12, uv를 설치하고 버전을 확인합니다. 전체 웹은 Node22/pnpm10.0.0, PDF 파서는 Java21이 추가로 필요하지만 B offline 계약 검사는 필요 없습니다.
```bash
git clone https://github.com/tskwak111/esg-proofops.git
cd esg-proofops
git switch -c feature/reconciliation
uv sync --locked
uv run python handoff/team-v2/contract/validate.py
uv run pytest tests/acceptance/test_rules.py -q
```
첫 검증은 schema/예제 검사입니다. B 엔진은 아직 없으므로 `reconciliation_cli`가 실행되지 않는 것은 정상입니다.
설치가 막히면 명령·exit code·오류를 기록합니다. uv.lock을 지우거나 버전을 임의로 바꾸지 않습니다.
기존 README의 기본 로그인은 미설정시 503입니다. B는 앱 로그인 없이 JSON으로 일합니다.

## 2. 읽기 순서
TEAM_PLAN → SCOPE_MATRIX → 이 문서 → PLAYBOOK → contract/CONTRACT → SCHEMA_GUIDE.
AGENTS와 docs/00,27,28,31은 금지사항·원문 검증 원칙입니다. reference 원문 2개는 업무 배경입니다.
IMPLEMENTATION_PLAN의 REC 번호는 작은 commit 순서이고 PLAYBOOK은 각 기능의 상세 동작 설명입니다.

## 3. 첫 구현
`domain/reconciliation/engine.py`에 evaluate(packet, policy)를 만듭니다.
먼저 stage/C5·schema 오류·미승인 정책을 거부하는 실패 테스트를 씁니다.
이후 C1→C3→C2→C4 순으로 독립 함수를 추가합니다. HTTP를 이 파일에 import하지 않습니다.
DART 코드는 adapters/dart에 넣고 tests에서 HTTP 응답을 고정 fixture로 대체합니다.

## 4. 키와 실행
실제 DART 키는 운영체제 환경변수 `DART_API_KEY`에 설정합니다. 명령 결과·스크린샷·Git에 키를 남기지 않습니다.
.env 파일은 Python이 저절로 읽지 않습니다. adapter가 환경변수를 읽도록 하고, 파일 로더는 A가 승인한 기존 방식을 재사용합니다.
실제 모델은 새로 구매/연결하지 않습니다. 설명검색 Port를 먼저 fixture로 구현하고 A의 Upstage 호출 경로와 연결합니다.

## 5. 매 작업의 끝
1. 실패를 보여주는 테스트를 작성·실행.
2. 최소 구현 후 같은 테스트 통과.
3. 계약 validator + 해당 회귀 검사.
4. source/hash/receipt 확인.
5. 작은 commit, 완료·실패·not_run 목록 제출.
