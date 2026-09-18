# 기업보고서 50개 — 파싱 수정 후 통합 검증

2026-09-09 KST. 입력 검사와 표 셀 매칭을 수정하고 동일한 50개 원본·동일한
표본 페이지로 실제 로컬 파서를 다시 실행했다. **파싱 반환 문서는 4개 → 13개**다.
이는 표본 실행 도달률이며 텍스트·숫자 정확도 점수가 아니다.

## 변경과 결과

- 공유 PDF 객체를 중복 계산하지 않고 고유 노드 예산으로 검사한다.
- `/AA`·`/OpenAction`의 존재만으로 거부하지 않고 내부 탐색 액션과 체인을 검사한다.
  일반 URI 링크의 비실행 저장 동작, 태그 구조 속성, 숨은 위험 액션 차단을 보존했다.
- 같은 위치의 표 셀은 파서별 행·열 번호가 달라도 다른 명시적 문맥이 같으면 매칭한다.
  숫자를 새로 만들거나 분절된 표·여러 줄 묶음을 임의로 재배열하지 않는다.
- 새 manifest는 `fusion_version=2`를 기록한다. 필드가 없는 기존 산출물은 v1로
  검증·재생하며 알 수 없는 버전을 거부한다. rollback 제약은 docs/27에 기록했다.
- 페이지 밖 좌표의 내부 예외를 기존 `PARSER_GEOMETRY_INVALID` 코드로 정리했다.
  잘못된 좌표를 잘라서 승인하거나 실패 manifest를 게시하지 않는다.

| 결과 | 최초 | 최종 |
|---|---:|---:|
| 각 3개 표본 페이지 파싱 반환 | 4 | 13 |
| PDF_INVALID | 32 | 23 |
| PARSER_GEOMETRY_INVALID | 0 | 8 |
| UPLOAD_LIMIT_EXCEEDED | 11 | 3 |
| PDF_PASSWORD_REQUIRED | 2 | 2 |
| PARSER_INPUT_LIMIT | 1 | 1 |
| 합계 | 50 | 50 |

최종 성공 범위는 **13개 문서, 39개 물리 페이지**다. 기존 성공 4개는 모두 유지했고
9개가 추가됐다. 입력 검사는 선택 페이지와 무관하게 PDF 전체에 적용했다.
기존 제한(100 MiB 입력, 100,000 고유 객체, 75,000,000 decoded bytes 등)은 유지했다.
최종 13개 manifest는 모두 해시 검증 후 다시 읽혔다. 최초 성공 4개 manifest도
원래 graph/quality와 일치하며 파일을 변경하지 않고 재생됐다.
원본 50개 SHA-256을 최초 inventory와 다시 대조해 **50/50 불변**을 확인했다.

파싱 반환 결과에는 `source_unlocated` 146건, `parse_conflict` 32건,
`table_vision_not_run` 80건이 있다. 전부 `fast_preview`이고 검증 완료가 아니다.
표본 수가 달라졌으므로 최초 이슈 건수와 단순 비교해 정확도 개선율로 쓰지 않는다.

## 표 회귀 사례

KOGAS 물리 68페이지가 포함된 기존 3페이지 후보 묶음에서 canonical block은
778 → 663개로 줄었다. **일치하는 셀 후보 115쌍**이 매칭됐으며 원시 후보는
783/783 보존됐다. 파서 간 불일치에 승자를 지정하지 않는다.
겹치는 별도 표와 여러 행을 뭉친 셀은 남아 있다. 헤더·연도·단위 연결 문제를
모두 해결했다는 뜻은 아니다. 상세: `corpus-table-repair.md`.

## 남은 거부 원인과 작업

입력 거부 23개는 추가 읽기 전용 추적으로 첫 거부 원인을 분류했다:

| 첫 거부 원인 | 문서 수 |
|---|---:|
| Named Print / Find / FitPage (현 허용 목록 밖) | 5 / 2 / 2 |
| Hide 액션 | 4 |
| AA를 통한 URI 액션 | 4 |
| GoToR 원격 목적지 액션 | 3 |
| 엄격한 PDF 객체 읽기 오류 | 3 |

허용 목록 밖이라는 사실은 해당 문서가 악성이라는 판정이 아니다. 원본을 수정하거나
검사를 우회하지 않았다. 첫 거부 이후의 모든 문제를 조사했다는 뜻도 아니다.

- 좌표 오류 8개: 입력 검사 통과 후 페이지 밖 bbox 발견. 원시 좌표 체계·CropBox·
  이미지 여백 등을 더 조사하고, 유효하지 않은 위치를 근거로 승인하지 않는 처리가 필요하다.
- 자원 제한 3개: KT 고유 객체 수 초과, 풀무원·하나금융 decoded bytes 초과.
  한도를 올려 통과시키지 않았다.
- 암호화 2개와 100 MiB 초과 1개는 현행 계약대로 차단한다.
- 자동으로 더 진행할 부분: 좌표 오류 처리, 분절 표의 헤더/연도 연결,
  제한된 배치로 전 페이지 범위 확대. 현재 7,454페이지 전수 파싱은 not_run이다.
- 사람·승인 데이터가 필요한 부분: 독립 원문 정답 태깅, 정확도 판정 기준 확정,
  보안·자원 정책을 바꿀지 결정, 실제 모델/AWS 시험 승인과 환경.
  사용자가 보류한 판단·허가는 이번에 새로 요청하지 않았다.

## 실행 검증

| 명령 | 실제 결과 |
|---|---|
| `uv run --no-sync pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q` | 1,378 passed, 2 warnings, 120.44s |
| `uv run --no-sync pytest tests/acceptance/test_upload_security.py -q` | 최종 간접 URI 객체 순서 2가지 보강 후 45 passed |
| `uv run --no-sync ruff check .` | 통과 |
| `uv run --no-sync ruff format --check .` | 210 files 통과 |
| `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py` | 136 files 통과 |
| `uv build --all-packages --out-dir .local/corpus-repair/build` | 4개 패키지 wheel/sdist 빌드 통과 |
| `uv run --no-sync python scripts/validate_package.py` | 705/705 문서·계약 검사 통과; 앱 테스트와 별개 |

전체 suite와 입력 검사 suite는 겹치므로 합산하지 않는다. 전체 실행 후 테스트의
객체 순서 사례 하나를 보강했고 해당 입력 검사 파일을 다시 실행했다. 제품 코드 변경은 없었다.
새 manifest 테스트는 구현 전 `KeyError: fusion_version`로, 좌표 경계 테스트는
구현 전 `DomainValidationError`로 실패함을 확인하고 수정 후 통과했다.
두 경고는 Starlette TestClient의 httpx 사용 및 AnyIO BlockingPortal 별칭 deprecation이다.
실제 모델·AWS·비전·OCR/hybrid는 not_run. 브라우저 UI는 이번 Python 파서 수정에서
재시험하지 않았다. 로컬 HTTP 통합 및 offline staging E2E는 위 suite에 포함된다.

## 재현 파일과 오케스트레이션

- 최초 실행: `.local/corpus-first-pass/` (기존 결과 보존).
- 최종 실행: `.local/corpus-repair/final/run_corpus.py`, `results.json`, `run.log`,
  `artifacts/`, `verification.json`.
- 최종 재생·원본 해시 검사: `.local/corpus-repair/verify_final.py`.
- 이전 manifest 재생: `.local/corpus-repair/verify_legacy.py`, `legacy-replay.json`.
- 추가 입력 원인 추적: `remaining-input-diagnostics.json` (26개 입력/자원 거부),
  `diagnose_remaining.py`. 추적은 진단용이며 앱의 실행 시간 성능 수치로 사용하지 않는다.
- 전체 테스트·빌드·문서 검증 로그: `.local/corpus-repair/`.

Orca run `run_37f538200824`: Kiro Sonnet 5 입력 수정, OpenCode Muse Spark 1.3 Free
표 수정, Muse Spark 1.2 Free 독립 입력 조사. 코디네이터가 코드·집계·호환성을 재검증했다.
Kiro 시작 관찰은 실패로 보고됐지만 실제 작업이 진행돼 중복 실행하지 않았고,
후속 worker_done으로 완료 상태를 확인했다. 3개 작업 모두 completed이며, release가
external_terminal로 남긴 이번 작업 전용 터미널은 정확한 handle로 종료했다.
Antigravity 및 Codex 작업 에이전트로 전환하지 않았다. 우선순위는 AGENTS.md에 저장했다.
새 의존성·DB/API 변경·GitHub push·클라우드 변경은 없다.
