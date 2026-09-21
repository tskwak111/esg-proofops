# A+B 통합 검증 — 2026-09-21

## 이번 결과와 범위

`integration/developer-ab-20260921`은 A의 미커밋 개발 내용을 보존한 스냅샷과
B PR #7 (`55e3e060c2cf0dafa797f2fd43354e264109c483`)을 합친 별도 통합 브랜치다.
기존 A 작업 폴더·브랜치, B 브랜치와 main은 수정하지 않았다. API 키, 실제 보고서,
운영 DB와 비용 원장은 포함하지 않았다. 이번 작업에서 유료 API 호출은 하지 않았다.

A의 주장/근거 흐름과 B의 대조·검토·평가·내보내기 화면을 같은 로컬 API로 실행했다.
아래 브라우저 결과는 **합성 입력**으로 확인한 기능 통합 결과이며 실제 기업 판정 정확도가 아니다.

## 충돌 처리

- `source_verification.py`: A의 정확한 바이트를 유지했다. 이 파일의 해시가 기존 원문 검증
  영수증 정책에 포함되어 있기 때문에 단순 교체도 과거 결과 재생을 막는다.
- `test_native_paragraph_worker.py`: A의 영수증 검사와 B의 충돌 없는 변경을 함께 유지했다.
- B의 Windows 파서 격리, API 구성, 대조 저장소와 React 화면은 통합했다.
- 보관된 reader 2개의 import 순서와 해시 고정 wrapper의 포맷만 스타일 검사에서 예외 처리했다.
  원문 검증/판정 로직 검사나 테스트는 면제하지 않았다.
- 나머지 스타일 오류와 타입 추론 오류는 동작을 바꾸지 않고 정리했다.

## 실행 환경 주의

다른 checkout의 `.venv`를 심볼릭 링크로 공유하면 안 된다. 파서는 Python `-I` 자식
프로세스를 사용하므로 부모의 `PYTHONPATH`를 무시한다. 공유 환경의 editable install이
원래 A 폴더를 가리키면서 B의 `windows_isolation` 모듈을 찾지 못했던 환경 오류를 확인했다.
통합 폴더 전용 interpreter로 같은 테스트 75개가 코드 수정 없이 통과했다.
새 checkout은 자체 환경에서 다음을 실행한다.

```sh
uv sync --locked
pnpm install --frozen-lockfile
pnpm --filter proofops-web build
uv run python -m tests.e2e.local_browser_server --host 127.0.0.1 --port 4198 \
  --origin http://localhost:4198 --database .local/ab-demo.sqlite3 --include-reconciliation
```

`http://localhost:4198/__e2e/login`에서 합성 사례로 진입한다.
**이 서버는 테스트 전용이며 운영 인증·규칙 승인 환경으로 배포하지 않는다.**
Java와 네이티브 원문 reader는 해당 플랫폼 요구사항을 따라 설치해야 한다.

## 확인 결과

| 확인 | 결과 | 의미/한계 |
|---|---|---|
| React 타입 검사·Vite 빌드 | 통과 | 브라우저 배포 산출물 생성 |
| 실제 로컬 HTTP+SQLite 브라우저 경로 | 통과 | C1·C2·C4 완료, 미승인 C3 보류 |
| 결과 내보내기·원문 해시·중복 실행 | 통과 | 이전 revision 불변, 검토 변경 시 오래된 결과 표시 |
| A 기존 실행 재조회 3건 | 통과 | 네이버 10+10, KB 23주장; 인용문·검증 상태 유지 |
| Ruff lint/format | 통과 | 해시 고정 소스 바이트 유지 |
| Mypy | 통과 | 263 소스 파일 |
| 아키텍처 검사 | 통과 | Domain 순수성 및 대조 API 구성 |
| 문서·계약 검사 | 951/951 | 앱 정확도 지표가 아님 |
| 통합 회귀검사 | 최초 3,896 통과 / 11 실패 / 65 제외; 실패 범위 재실행 139 통과 | 아래 실패 원인과 수정 내역 참고 |

기존 실행 재조회: 네이버 R17 verified 2/unverified 8, 네이버 R19 9/1,
KB R17 8/15. 이는 저장된 원문 검증 상태의 호환성 확인이며 등급 산출 성공률이 아니다.
원본 A 스냅샷의 모든 기록 대상 파일 해시와 HEAD가 그대로임을 확인했다.

최초 회귀 11개 실패는 다음과 같이 처리했다. 전체 검사를 반복하는 대신 영향 범위만 재실행했다.

- 6개: 로컬 전용 표 레이아웃/저장 응답 입력 누락. 검사에 필요한 최소 JSON만 추가했다.
  실제 보고서 표 검사는 로컬 PDF 링크로 실행해 통과했다. PDF는 Git에서 제외하며 이 검사만
  보고서가 없는 checkout에서 명시적으로 제외된다. 원래 수치·출처 경계 검증 assertion은 유지했다.
- 4개: CLI의 `native_typography_tolerance=False`와 ParserProfile의 추가 opt-in 필드가
  오래된 테스트 기대값에 빠져 있었다. 기본값과 기존 고정 해시를 그대로 검사하도록 갱신했다.
- 1개: macOS 27 Apple Vision이 합성 PDF의 `tCO2e`를 `tCo2e`/`tC02e`로 읽었다.
  성공 사례는 명확한 `Page 1 emissions 1234` 영역을 사용했다. 실제 OCR 실행,
  틀린 숫자·표 관계·위조 영수증·다른 테넌트 거절 assertion은 그대로 유지했다.
  **OCR의 해당 문자 오독 자체는 해결하지 않았고 정확 일치 기준도 완화하지 않았다.**

최종 checkout은 공유 `.venv` 링크를 제거하고 `uv sync --locked`로 전용 환경을 생성했다.
그 환경에서 실패 범위와 파서 연결을 포함한 139개가 모두 통과했다.
로그: `.local/ab-failed-scope-rerun.log`. 최초 65개 제외에는 로컬 자료/플랫폼 요구 조건이
있는 검사가 포함된다. GitHub의 Linux/Windows/macOS CI 결과는 PR에서 별도로 확인한다.

회귀 실행:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py
uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/reconciliation tests/e2e/test_staging_gate.py -q
```

브라우저 자동 확인은 기존 `scripts/check_reconciliation_browser.mjs`를 사용했다.
로컬 상세 로그·화면은 `.local/ab-browser-evidence/`, 회귀 로그는 `.local/ab-tests.log`,
기존 실행 재조회 집계는 `.local/old-run-replay-results.json`에 있다.
운영 상태나 전체 보고서를 GitHub에 올리기 위해 복사하지 않았다.

## PR #8 CI 복구 (2026-09-21)

최초 GitHub 실행 `35607412390`의 Python 실패 2건은 로컬 보고서/실행 기록 의존성이었고,
Windows 실패는 공통 worker의 import 경로가 Unix 전용 `fcntl`을 즉시 읽어서 발생했다.
`fcntl`은 실제 유료 태깅 호출 안에서만 읽도록 옮겼다. 기존 POSIX 잠금은 그대로이며,
잠금 모듈이 없는 플랫폼에서는 유료 호출·예약·영수증 생성 전에 거절된다.
이는 Windows 오프라인 대조 경로의 복구이며 Windows 유료 태깅 지원 추가가 아니다.

실보고서 5개사의 기존 assertion은 유지하고 해당 로컬 기록이 없는 checkout에서만
그 역사적 사례 검사를 제외한다. 별도 임시 PDF/JSON으로 `missing`/`parse_only`/`ok`,
미실행 단계, 페이지 중복 이력, 실제 해시 계산과 파일 변경·삭제 거절을 검사한다.
표 격자 오류 검사는 생성한 PDF를 사용하여 기존 10개 오류 assertion을 CI에서도 실행한다.
원문 검증기·규칙·API/DB 계약과 기존 결과는 변경하지 않았다.

관련 검사 67개 통과(태깅·복구·잠금 부재/경합·임시 입력), 변경 파일 lint/format 및
태깅 transport type 검사 통과. 로그는 `.local/ci-recovery-20260921/`에 보관한다.
Python CI와 같은 범위의 로컬 실행은 382 통과/45 제외였다(로컬 실자료 사례 포함).
기존 FastAPI/Starlette deprecation warning 2건은 남아 있다. 실행 명령:

```sh
uv run pytest tests/unit/test_pipeline_recovery.py tests/unit/test_tagging_platform.py tests/unit/test_reviewed_multi_level_header_table.py::test_span_and_unit_source_guards_fail_closed tests/integration/test_upstage_tagging.py tests/integration/test_tag_recovery.py -q
DEVELOPER_DIR=/Library/Developer/CommandLineTools uv run pytest tests/unit tests/contracts tests/e2e/test_staging_gate.py -q
uv run ruff check apps/agent/src/proofops_agent/upstage_tagging.py tests/unit/test_pipeline_recovery.py tests/unit/test_tagging_platform.py tests/unit/test_reviewed_multi_level_header_table.py tests/integration/test_upstage_tagging.py
uv run ruff format --check apps/agent/src/proofops_agent/upstage_tagging.py tests/unit/test_pipeline_recovery.py tests/unit/test_tagging_platform.py tests/unit/test_reviewed_multi_level_header_table.py tests/integration/test_upstage_tagging.py
uv run mypy apps/agent/src/proofops_agent/upstage_tagging.py
```

## 남은 제한

- 데이터 담당자의 최종 기준·크로스워크와 C3 임계값/계정 매핑은 아직 확정되지 않았다.
  승인 없는 항목은 계속 보류하며, 임의 기준으로 판정을 통과시키지 않는다.
- 현재 실제 보고서 실행에는 원문 불일치·트랙 미확정 등 보류가 남아 있다.
  이번 통합은 그 정확도 병목을 해결했다고 주장하지 않는다.
- 실제 기업 DART 수집→보고서 대조의 정확도 평가, 전체 보고서 완주,
  독립 gold 평가, 운영 배포는 이번 범위에서 실행하지 않았다.
- PR은 검토 가능한 Draft이며 main 병합은 별도 단계다. B PR #7을 중복 병합하기 전에
  이 통합 PR에 해당 커밋이 포함되어 있음을 확인한다.
