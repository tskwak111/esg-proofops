# C1–C4 로컬 검토 경로

원문 수집 → 검토 후보 → 운영자 초안 등록 → 검토자 확인 → 관리자 정책 승인 →
순수 규칙 판정 → 불변 결과 내보내기의 경로다. 실제 회사의 사실관계와 회계 정책을
자동 승인하지 않는다. G/P/M 등급은 기존 경로를 유지한다.

## API 키

저장소 루트의 `.env.dart.local`에 `DART_API_KEY=발급받은키`를 넣는다.
이 파일은 Git에서 제외된다. 키를 코드, 전달 ZIP, 명령 인자에 넣지 않는다.
CLI는 `.env`를 자동으로 읽지 않으므로 다음처럼 명시적으로 주입한다.

```powershell
uv run --env-file .env.dart.local --no-sync python -m evaluation.reconciliation_collect `
  --corp-code 00126380 --fy 2024 --rcept-no 20250311001085 `
  --package-id samsung-2024 --manifest-id samsung-2024-collection-1 `
  --document-version-id samsung-fs-2024-20250311001085 `
  --reprt-code 11011 --fs-div CFS `
  --store .local/dart-example/originals --output .local/dart-example/collection.json
```

접수번호는 회사·연도·정정공시 여부를 확인하여 고정한다. 예시 출력 경로는 아직
존재하지 않는 경로를 사용한다. 기존 수집물이나 결과를 덮어쓰지 않는다.

## 후보 만들기

```powershell
uv run --no-sync python -m evaluation.reconciliation_prepare `
  --manifest .local/dart-example/collection.json --store .local/dart-example/originals `
  --corp-code 00126380 --fy 2024 --rcept-no 20250311001085 `
  --consolidation consolidated --output .local/dart-example/prepared
```

`candidates.json`은 미검토 후보이며 완성된 판정 입력이 아니다. 공시 원본 ZIP,
ZIP 멤버, 파생 텍스트의 해시와 변환 정보를 구분한다. 파생 텍스트의 문자 위치를
원문 PDF/XML의 위치인 것처럼 사용하지 않는다. 후보 개수 제한에 걸린 경우
전체 문서 검색을 완료했다고 간주하지 않는다.

운영자는 `--selections`에 명시적으로 선택한 주장·SR 값·재무 값·기간·문서 식별자와
정책 초안을 제공한다. 누락된 선택은 후보 상태로 남으며 CAPEX 계정, 임계값,
설명 부재, 정책 승인을 추정하지 않는다. SR 원문은 DART 원문과 별도로 제공한다.

SR 입력은 `--sr-sources sr-sources.json`으로 추가한다. 형식은
`reconciliation-sr-sources-1`이며 원본 파일·해시·문서 메타데이터·인용 위치를 포함한다.
선택 파일은 `reconciliation-operator-selections-1` 형식이다.
자세한 필드와 예시는 [후보 준비 인터페이스](../evidence/reconciliation-product/sol/INTERFACE.md)에 있다.
두 파일을 함께 지정해 새 출력 경로로 실행하면 `packet.json`, `policy.json`,
`documents.json`, `artifacts.json`, `coverage.json`, `policies.json`과 원문 사본이 생성된다.
검색 완료와 정책 승인은 자동 부여되지 않는다. 실제 주장 연결 정보는 기존 검증 실행에서 가져온다.

## 기존 실행에 초안 등록

이미 파싱·추출 검증을 통과한 주장과 동일한 회사·문서 버전·주장을 사용해야 한다.
새로운 주장 ID를 임의 생성해 기존 실행에 연결하지 않는다. 서버 파일 접근 권한이
있는 운영자가 실행하는 명령이며 HTTP 파일 업로드로 노출하지 않는다.

```powershell
uv run --no-sync python -m evaluation.reconciliation_import `
  --database .local/state.sqlite3 --bundle .local/prepared-case `
  --artifacts .local/prepared-case/artifacts `
  --tenant-id 실제테넌트UUID --run-id 실제실행UUID --claim-id 실제주장UUID `
  --actor 운영자식별자
```

등록은 `pending`과 정책 미승인 상태로 시작한다. 가져온 승인 레지스트리는 신뢰하지
않는다. 명령이 출력하는 `/runs/{run_id}/claims/{claim_id}/reconciliation` 경로 또는
주장 상세의 **공시 원문 대조 · C1–C4 검토** 링크에서 확인한다.

## 검토 화면

Viewer는 조회·원문 다운로드·결과 내보내기, Reviewer는 사실관계 검토,
Editor는 판정 실행, Admin은 별도 정책 승인을 수행한다. 서버에서 권한·테넌트·
CSRF·Origin을 검증하며 화면에서 버튼을 숨기는 것만으로 권한을 대신하지 않는다.
검토자는 입력 전체와 인용 원문을 확인하고 사유를 기록한다. 검색 범위 확인은
별도 항목이며, 불완전한 검색을 사실 확인만으로 완료 처리하지 않는다.

각 변경은 `If-Match`와 `Idempotency-Key`가 필요하다. 충돌하면 최신 상태를 다시
불러와 검토한다. 과거 결과는 별도 리비전으로 보존된다. 정책 미승인 또는 원문
검증 실패는 HTTP 요청 성공과 별개로 `execution_state=blocked`, `status=null`이다.
`matched`는 공시 값 대조 또는 차이 설명 확인을 뜻하며 회계 적정성 인증이 아니다.
C3 정책에 임계값이나 허용 계정이 없으면 관리자 승인만으로 채워지지 않는다.

## 검증·호환성

```powershell
uv run --no-sync python scripts/verify_reconciliation.py --output .local/product-check
pnpm --filter proofops-web typecheck
pnpm --filter proofops-web build
```

Windows에서 프로젝트 전체 테스트를 직접 실행할 때는 `$env:PYTHONUTF8='1'`을 먼저
설정한다. 검증기는 하위 프로세스에 UTF-8 환경을 직접 설정한다.

실제 PDF 파서는 Java 21이 필요하다. 테스트에서 다른 Java가 선택되면
`PROOFOPS_TEST_JAVA`에 Java 21 실행 파일의 절대 경로를 설정한다.
Windows에서는 실행 전 Job Object에 파서 프로세스를 넣어 자식 Java 프로세스까지
자원 제한과 종료 처리를 적용한다. 제한 설정 실패는 파싱 실패로 처리한다.
출력 용량과 실행 시간은 부모 프로세스가 감시하며, 이 제한은 OS 전체 파일 접근을
차단하는 보안 샌드박스를 뜻하지 않는다.

```powershell
$env:PYTHONUTF8 = '1'
uv run --no-sync python -m pytest tests/acceptance/test_parsing.py tests/integration/test_local_tag_runner.py -q
```

GitHub CI는 Windows·Linux·macOS 15(Apple Silicon 및 Intel)에서 대조 검증 및
위 실제 Java 파서 회귀 검사를 실행한다. Java 21은 러너 아키텍처에 맞게 설치한다.

### 개발자 A: macOS 시작

Homebrew가 설치된 터미널에서 다음을 실행한다. `brew --prefix`를 사용하므로
Apple Silicon의 `/opt/homebrew`와 Intel의 `/usr/local`을 하드코딩하지 않는다.

```bash
brew install uv node@22 openjdk@21
export PATH="$(brew --prefix node@22)/bin:$PATH"
npm install -g pnpm@10.0.0
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PROOFOPS_TEST_JAVA="$JAVA_HOME/bin/java"
export PYTHONUTF8=1

# 저장소를 받은 뒤 해당 브랜치에서 실행
git fetch origin
git switch feature/developer-b-reconciliation
uv sync --locked
pnpm install --frozen-lockfile
uv run --no-sync python scripts/verify_reconciliation.py --output .local/mac-check-1 --timeout-seconds 600
uv run --no-sync python -m pytest tests/acceptance/test_parsing.py tests/integration/test_local_tag_runner.py -q
pnpm --filter proofops-web typecheck
pnpm --filter proofops-web build
```

검증 출력 경로는 매 실행마다 새 이름을 사용한다. macOS의 zsh/bash에서 위 DART
명령 예시를 실행할 때 PowerShell의 줄 연결 문자(백틱)를 `\`로 바꾸거나 한 줄로
입력한다. `.env.dart.local`은 A의 Mac에서 별도로 생성하고 발급 키를 입력한다.
키 파일을 Git 또는 전달 패키지로 공유하지 않는다. 실제 수집만 키가 필요하며
합성 입력·오프라인 CI는 키 없이 실행한다.
이 경로는 합성 테스트 PDF를 사용하며 API 키나 실제 모델 호출이 필요하지 않다.

실제 HTTP 브라우저 검증은 빌드 후 테스트 전용 서버에 대해 실행한다.
`uv run --no-sync python -X utf8 -m tests.e2e.local_browser_server --port 4193
--host 127.0.0.1 --origin http://localhost:4193 --database .local/browser-new/state.sqlite3
--include-reconciliation`으로 새 데이터베이스를 사용한다.
별도 터미널에서 `node scripts/check_reconciliation_browser.mjs http://localhost:4193
.local/browser-evidence-new`를 실행한다. Playwright는 검증용 환경에 별도 설치하고
`PROOFOPS_PLAYWRIGHT_MODULE`로 모듈 경로를 지정한다. 설치된 Edge 사용 시
`PROOFOPS_BROWSER_CHANNEL=msedge`를 지정한다. 테스트 전용 로그인은 운영 앱에 포함되지 않는다.
이 테스트의 C3는 미승인 정책 차단을 확인하며, 목표 트랙의 C3 임계값 규칙은 별도 도메인 테스트로 검증한다.

검증기는 기존 8개 CLI 사례와 G/P/M 회귀, 후보 및 제품 API/저장소 테스트를 포함한다.
화면 경계 테스트는 `tests/e2e/reconciliation_workspace_check.mjs`이며 제어된 fetch
응답을 사용한다. 실제 HTTP 통합 테스트와 구별해 결과를 기록한다.

입력·정책·판정 계약 1.1은 유지한다. SQLite의 `reconciliation_` 테이블과 버전
메타데이터를 추가하고 기존 G/P/M 기록을 변경하지 않는다. 롤백은 새 API/UI 연결을
제거하고 신규 테이블·불변 원문을 보존하는 방식이다. 모르는 DB 스키마 버전은
거부한다. 클라우드 배포·실제 모델 품질 검증·실제 정책 승인은 별도 게이트다.
