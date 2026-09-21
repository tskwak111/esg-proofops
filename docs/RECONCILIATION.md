# Developer B: C1–C4 reconciliation

이 기능은 공시 간 차이와 설명의 존재를 검토한다. 회계 처리의 적정성,
ESG 점수 또는 기존 G/P/M 증거 등급을 판정하지 않는다.

## 실행 경계

- `proofops.domain.reconciliation.engine.evaluate`: 검증된 입력을 받는 순수 판정 함수.
- `proofops.application.reconciliation.service.reconcile`: 입력 계약, 원문,
  문서 식별자, 승인 정책, 검색 완료 기록을 검증한 뒤 엔진을 호출한다.
- `proofops.adapters.reconciliation.FileSourceReader`: 신뢰된 로컬 원문 목록을
  사용하여 SHA-256, 위치, 정확한 인용문을 확인한다.
- `proofops.adapters.dart`: DART HTTP 수집, 원본 저장, 정규화와 수집 명세서.
- `evaluation.reconciliation_cli`: 검증과 판정을 실행하는 별도 CLI.
- `evaluation.reconciliation_collect`: 접수번호를 고정하여 원본을 수집하는 CLI.

C1은 검증된 조직 집합, C2는 실제 기간, C3은 금액 투자 목표와 CAPEX,
C4는 분류의 정의 및 계산 근거를 다룬다. 미승인 정책이나 불완전한 검증은
`blocked`와 `status: null`이다. C3에는 기본 배수나 임의 계정 매핑이 없다.
`config/accounting/`의 정책 초안은 활성화되지 않는다.
C5는 엔진에서 `NotImplementedError`, CLI에서 별도 dispatch 봉투의
`not_run / stage_disabled`로 처리한다. C5를 결과 계약 1.1에 끼워 넣지 않는다.

## 합성 입력 실행 (PowerShell, 저장소 루트)

프로젝트 Python 환경에 개발 의존성을 설치한 뒤 실행한다. 아래 예시는
`uv`가 프로젝트에 설치된 환경을 사용한다. 실제 외부 API나 모델을 호출하지 않는다.
출력 폴더는 새 경로를 사용한다. 기존 원문과 결과는 덮어쓰지 않는다.

```powershell
$env:PYTHONPATH = 'packages'
uv run python -m evaluation.reconciliation_fixtures --output .local/reconciliation-demo
$case = '.local/reconciliation-demo/c1-same-entities'
uv run python -m evaluation.reconciliation_cli `
  --packet "$case/packet.json" --policy "$case/policy.json" `
  --artifacts "$case/artifacts" --artifact-index "$case/artifacts.json" `
  --documents "$case/documents.json" --policy-registry "$case/policies.json" `
  --coverage-registry "$case/coverage.json" `
  --output "$case/result.json" --projection "$case/presentation.json"
```

생성기는 전달 패키지의 8개 사례를 바탕으로 실제 UTF-8 원문 바이트와 해시를
만든다. 원래 전달 예제의 자리표시자 해시는 원문 검증에 사용할 수 없다.
생성된 승인 기록은 합성 테스트 전용이며 실제 정책 승인을 뜻하지 않는다.

입력 패킷과 **신뢰 자료**를 구분해야 한다. `--documents`, `--artifact-index`,
`--policy-registry`, `--coverage-registry`는 운영자가 통제하는 검증 기록이다.
사용자 제출 패킷에서 이 파일들을 자동 생성하거나 함께 신뢰하면 안 된다.
실서비스에서는 인증된 저장소·추출 검토·정책 승인·검색 실행 기록으로 이 경계를
구현해야 한다. 로컬 파일 인터페이스 자체가 외부 문서의 진실성을 인증하지 않는다.
정확한 레지스트리 필드는
[`INTERFACE.md`](../evidence/reconciliation/sol/INTERFACE.md)를 참고한다.

문서 레지스트리의 `source_bindings`는 인용 위치·문장과 근거 용도를,
`fact_bindings`는 원문에서 검토한 값과 정규화 값을 고정한다.
`decision_binding`은 해당 호출의 claim ID·항목·비교 가능 여부·주장·C3/C4
맥락을 고정한 검토 스냅샷이다. 같은 문서에 주장이 여럿 있으면 호출별로
해당 주장의 검토 스냅샷을 조회해 주입해야 한다. 문서 해시만 같다는 이유로
다른 인용이나 다른 주장에 기존 검토 결과를 재사용하지 않는다.
문서의 `synthetic` 값도 패킷과 같아야 한다. 레지스트리의 정책 범위가 없거나
정책과 다르면 실제 데이터에 적용할 수 있는 승인으로 간주하지 않는다.

Application 결과의 `packet_sha256`과 `policy_sha256`은 **제출된 입력**의
리비전을 가리킨다. 재현에는 같은 입력뿐 아니라 같은 신뢰 레지스트리와
설명 후보 스냅샷을 함께 보관해야 한다. 순수 엔진을 직접 호출하면 엔진에
전달한 검증 완료 패킷·정책을 해시한다.

`--explanations`는 `{ "sources": [...] }` 형식의 후보 목록이다. 후보 역시 원문,
문서 및 해당 주장과의 관련성을 검증해야 하며 모델의 최종 판정을 받지 않는다.
`--projection`은 결과 1.1과 별도의 `reconciliation-presentation-1` 형식이다.
승인된 회계 근거를 임의로 채우지 않으며 `basis`는 빈 목록, `confidence`는 null이다.

판정 CLI 종료 코드: 정상 의미 결과(보류 포함) 0, 잘못된 입력/출력 충돌 2,
수집 또는 내부 실행 오류 3. 입력 JSON은 중복 키와 비유한 수를 거부한다.

## DART 수집

API 키는 환경변수 `DART_API_KEY`로 주입한다. 명령행 인자, 파일 이름, 기록에
키를 넣지 않는다. 아래 값은 형식 예시이며 실행 전에 실제 접수번호를 확인해야 한다.
수집 CLI 실행은 외부 네트워크 요청을 발생시킨다.

```powershell
uv run python -m evaluation.reconciliation_collect `
  --corp-code 00126380 --fy 2024 --rcept-no 20250314000123 `
  --package-id pkg-2024 --manifest-id collection-v1 --document-version-id fs-v1 `
  --reprt-code 11011 --fs-div CFS `
  --store .local/dart-originals --output .local/collection-v1.json
```

기본 수집 대상은 전체 재무제표 JSON, 공시 원문 ZIP, XBRL ZIP이다.
`--kinds statements` 등으로 대상을 제한할 수 있다. 응답을 JSON으로 재직렬화하지
않고 수신한 바이트 그대로 SHA-256 저장한다. 명세서는 `collection-1` 계약을
따르며 회사·사업연도·접수번호·연결 구분·문서 버전·UTC 수집 시점을 남긴다.
자료 없음은 `not_available`, 인증·한도·수집·식별자 오류는 `failed`로 구분한다.
일부 수집 실패도 명세서에 남기며 종료 코드 3을 반환한다.
수집 성공은 원문의 사실 추출, 정책 승인 또는 C1–C4 판정 완료를 뜻하지 않는다.

공식 API 계약:
[전체 재무제표](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020),
[재무제표 원본 XBRL](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019019).

## 검증

개발자 A 인수 절차와 서비스 주입 예시는
[`RECONCILIATION_HANDOFF.md`](RECONCILIATION_HANDOFF.md)를 참조한다.
저장소 루트에서 잠금 의존성을 설치하고 아래 명령 하나로 오프라인 전달 검증을 실행한다.
검증에는 C1–C4/GPM 회귀, lint·format·type·architecture 검사와 실제 CLI 예제 8개가 포함된다.
결과는 새 출력 폴더의 `checks.json`과 단계별 JSON 로그에 남으며 실패가 하나라도 있으면
종료 코드 1이다. 기존 출력 폴더는 덮어쓰지 않고 종료 코드 2로 거부한다.

```powershell
uv sync --locked
uv run --no-sync python scripts/verify_reconciliation.py --output .local/reconciliation-release
```

이 명령은 Windows와 Linux 경로 구분자를 자동으로 처리한다. CI에는 두 운영체제의
동일 검증과 실패 로그를 포함한 artifact 보관을 추가했다. GitHub CI 실행 결과는
로컬 검증과 별도로 확인해야 한다.

개별 회귀 테스트만 실행하려면:

```powershell
$env:PYTHONPATH = 'packages;apps/api/src;apps/worker/src;apps/agent/src'
uv run pytest tests/reconciliation tests/acceptance/test_rules.py -q
```

테스트는 네트워크 없이 합성 원문, 모의 DART 응답, 입력 변조 및 실패 사례를
검증한다. CI에도 이 검증을 추가한다. 실 DART 인증 수집, 실제 기업 문서의 추출
품질 및 미승인 회계 정책의 실무 적합성은 이 테스트의 검증 범위가 아니다.
