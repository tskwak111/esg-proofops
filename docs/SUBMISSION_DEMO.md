# 개발자 A 제출용 로컬 실행

개발자 B의 DART·C1~C4 연계 판정은 포함하지 않습니다. 실제 PDF를 입력받아 파싱·주장 추출·근거 검증·모델 태깅을 수행하고, Python 규칙엔진의 판정 또는 보류를 검토·내보내는 로컬 흐름입니다. 승인되지 않은 규칙집으로 최종 등급을 만들지 않습니다.

## 저장된 실제 결과 열기 — API 비용 없음

프로젝트 최상위 `start_submission.command`를 실행합니다. 터미널에서라면:

```bash
cd /Users/ss020/Dev/ESG_ProofOps
./start_submission.command
```

터미널에 출력되는 `http://localhost:8794/__local/...` 주소를 엽니다. 주소는 실행할 때마다 바뀝니다. 종료는 실행한 터미널에서 Ctrl+C입니다. 포트를 이미 사용 중이면 `PROOFOPS_DEMO_PORT=8795 ./start_submission.command`로 실행합니다.

1. **주장**: 추출한 문장과 트랙·판정/보류를 봅니다.
2. 주장을 열고 **원문 위치 열기**: 실제 PDF 페이지를 확인합니다. 검증되지 않은 위치에는 하이라이트를 붙이지 않습니다.
3. **검토 큐**: 게시된 태그와 검토 사유를 확인합니다. 태깅 확정·재채점은 규칙집 승인 후 가능합니다. 현재 초안 규칙집 실행에서는 서버가 수정을 409 RULEPACK_APPROVAL_REQUIRED로 거절하고 화면에서도 안내합니다. 사람이 등급을 직접 지정하지 않습니다.
4. **보고서**: JSON·CSV·HTML을 선택합니다. 미완료·보류가 있으면 **부분 결과 허용**을 선택해야 합니다. 생성 → 다운로드 링크 발급 → ZIP 다운로드 순서입니다. 부분 결과는 최종 판정 보고서가 아닙니다.

실행기는 원본 상태를 `<seed>-demo`로 복사합니다. 같은 실행의 복사본은 재사용하며, 원본·기존 디렉터리를 삭제하지 않습니다. 다시 깨끗한 복사본이 필요하면 아래 명령의 `--demo-state`에 새로운 경로를 지정합니다.

```bash
cd /Users/ss020/Dev/ESG_ProofOps/.local/team-publication-20260918
.venv/bin/python scripts/submission_demo.py \
  --seed /Users/ss020/Dev/ESG_ProofOps/.local/submission-a-20260920/kb-cpu \
  --demo-state /Users/ss020/Dev/ESG_ProofOps/.local/submission-a-20260920/review-copy-2 \
  --port 8795
```

## 새로운 PDF 분석 — 실제 API 호출

프로젝트 최상위의 `analyze_report.command`로 새 보고서를 실행할 수 있습니다. 아래 명령은 **입력 계획만 확인**하며 모델 호출·상태 생성이 없습니다. PDF 경로·물리 페이지·보고기간은 실제 문서에 맞게 입력합니다.

```bash
./analyze_report.command --pdf '/absolute/path/report.pdf' \
  --pages 25,117,138 --report-year 2025 \
  --period-start 2025-01-01 --period-end 2025-12-31
```

실제 분석에는 같은 명령 뒤에 `--invoke`를 붙입니다. 분석 후 검토 화면까지 열려면 `--invoke --serve --port 8797`을 붙입니다. 기본 새 상태는 `.local/report-runs/` 아래에 만들어지고, 기존 내용이 있는 상태 디렉터리는 덮어쓰지 않습니다. 입력 검사는 PDF 페이지 수·날짜·기존 상태 충돌 확인이며, 정식 업로드 보안 검사 통과를 보장하지 않습니다. 기본 추출 상한은 문단 입력 8회, 태깅 호출 상한은 48회인 **제한된 부분 실행**입니다. 선택한 페이지 전체 문장 처리나 전수성을 뜻하지 않습니다. 상세 설정이 필요하면 아래 pilot CLI를 사용합니다.

### 주장 추출 페이지 좁히기 — `--claim-pages` (선택)

`--pages`에 E 본문·환경 데이터·부록을 함께 지정하면 세 영역이 모두 파싱되지만, 주장(claim) 추출도 세 영역 전부에서 일어납니다. 주장 추출을 특정 페이지로 좁히려면 `--pages`의 부분집합으로 `--claim-pages`를 추가합니다.

```bash
./analyze_report.command --pdf '/absolute/path/report.pdf' \
  --pages 25,117,138 --claim-pages 25 --report-year 2025 \
  --period-start 2025-01-01 --period-end 2025-12-31
```

- **필드 계약**: `--claim-pages`는 `--pages`의 비어 있지 않은 정규(오름차순·중복 없음·1-based 정수) 부분집합입니다. 범위를 벗어나거나 중복·비정수·빈 값이면 거절합니다. CLI는 중복 입력을 정규화합니다.
- 파싱·근거(evidence)·검색(retrieval) 범위인 `selected_pages`는 그대로 넓게 유지됩니다. `--claim-pages`는 **주장 발견 범위만** 좁히고 전체 파싱 그래프나 근거는 좁히지 않습니다.
- 프리즌된 실행의 `extraction_limits.claim_pages`에 기록되어 불변 입력 해시에 포함됩니다. RunService와 워커/재생 신뢰 경계에서 모델 호출 전에 검증합니다.
- `--claim-pages`를 생략하면 기존 동작·해시·재생이 정확히 그대로 유지됩니다. `--resume`은 저장된 `claim_pages`를 복원하며 다른 값으로 덮어쓰지 않습니다.
- 좁힌 실행에서도 커버리지는 선택하지 않은 페이지까지 추출했다고 주장하지 않습니다(`chunks_processed < chunks_discovered`).


서로 다른 보고서를 처음 등록할 때는 아래 **CLI**로 문서별 권리·동의·실행 구성을 만듭니다. 이미 승인된 동일 PDF의 새 분석은 `start_analysis.command`의 웹 업로드에서 시작할 수 있습니다. 워커 없이 저장된 결과만 여는 모드에서는 새 분석이 비활성화됩니다. 아래의 문서 경로·연도·기간·페이지를 해당 보고서에 맞게 바꾸고, 항상 새 상태 디렉터리를 사용합니다. 페이지는 인쇄 쪽번호가 아닌 PDF의 물리 페이지입니다. E 본문, 환경 데이터, 부록 관련 페이지를 함께 지정합니다. 선택하지 않은 페이지까지 분석했다고 주장하면 안 됩니다.

```bash
cd /Users/ss020/Dev/ESG_ProofOps/.local/team-publication-20260918
.venv/bin/python -m evaluation.local_upstage_pilot \
  --pdf '/absolute/path/report.pdf' \
  --state '/absolute/path/new-report-state' \
  --key-file /Users/ss020/Dev/ESG_ProofOps/.env.upstage.local \
  --pages 30,100,120 --report-year 2025 \
  --period-start 2024-01-01 --period-end 2024-12-31 \
  --verify-paragraphs --verify-claim-spans --verify-merged-tables \
  --repair-table-headers --model solar-pro3 --max-calls 8 \
  --live-tagging --tagging-max-calls 48 --invoke --serve --port 8795
```

pilot CLI도 동일한 `--claim-pages`(선택, `--pages`의 부분집합)를 받아 주장 추출 범위만 좁히고 파싱·근거는 넓게 유지합니다. 생략하면 기존 동작이 그대로입니다.

`--invoke`가 유료 실행을 명시합니다. 기존 누적 USD20 예산 장부를 사용하며 미정산 예약액을 지우지 않습니다. `--resume --invoke`는 거절합니다. 재시작은 `--resume --state ... --serve`만 사용하고, 새 분석과 재열람을 구분합니다.

### 웹에서 새 분석 시작 — `--serve-worker` (선택, 유료)

프로젝트 최상위에서 `./start_analysis.command`를 실행하고 출력되는 로그인 주소를 엽니다(기본 포트 8796). **새 분석 → 기존 회사·권리·동의·실행 환경 선택 → 동일한 승인 PDF 등록 → 분석 페이지 확인 → 사전 점검 후 분석 시작** 순서입니다. 기본 예시는 KB 보고서 물리 페이지 30입니다. 초안 규칙집으로는 추출·태깅과 부분 보고서를 볼 수 있지만 등급 확정과 검토 수정은 보류됩니다. 이 버튼은 실제 API 비용을 사용합니다.

웹의 문서 업로드·RunForm에서 만든 **새로 대기열에 오른 실행**을 같은 프로세스에서 자동으로 진행하려면 `--serve`에 `--serve-worker`를 함께 지정합니다. 이 플래그는 유료 신규 실행을 구동하는 명시적 동의이며, 읽기 전용 `--resume` 재열람과 구분됩니다. `--serve-worker`는 `--serve`를 요구합니다.

```bash
.venv/bin/python -m evaluation.local_upstage_pilot \
  --resume --state '/absolute/path/existing-state' \
  --key-file /Users/ss020/Dev/ESG_ProofOps/.env.upstage.local \
  --serve --serve-worker --port 8795
```

- 워커는 이 로컬 테넌트의 새 대기열 실행만 parse·extract·tag로 진행합니다. 기존에 완료된 시연 seed 실행은 다시 실행하지 않습니다.
- `failed`·`discarded`·`cancelled` 결과는 그 실행을 중단하며 재호출하지 않습니다. `retry`·예외가 발생한 실행은 해당 서버 세션에서 다시 호출하지 않습니다. 서버 재시작 시 이미 대기/처리 중이던 실행도 자동 재개하지 않습니다. 원인을 확인한 뒤 새 분석을 명시적으로 시작해야 합니다. 다른 리스가 점유한 상태(`deferred`)는 건너뜁니다.
- `--serve-worker`는 `--invoke`와 같은 누적 USD20 장부·동의·권리·런타임 바인딩을 사용하며 새 권한을 만들거나 예약액을 지우지 않습니다. 문서 SHA에 묶인 동의·권리 범위 밖의 PDF는 계속 거절합니다.
- `--serve-worker` 없이 `--serve`(또는 `--resume --serve`)만 실행하면 워커는 시작되지 않고 저장된 결과만 재열람합니다. 이때 `/local/submission`의 `worker_enabled`는 `false`이며 웹에서 유료 분석 시작이 비활성화됩니다.

정확한 실행 명령: `uv run python -m evaluation.local_upstage_pilot --resume --state <상태디렉터리> --key-file <키파일> --serve --serve-worker --port <포트>`

## 실행 환경과 보류

- macOS에서 설치된 Command Line Tools를 해당 프로세스에만 선택합니다. 시스템 Xcode 선택이나 라이선스 동의를 변경하지 않습니다.
- Apple Vision 원문 OCR은 CPU 경로를 사용합니다. OCR 실행 실패를 문서 근거 부재로 바꾸지 않습니다.
- OCR/검증기 버전 해시가 다른 예전 실행은 재검증에 실패할 수 있습니다. 기존 데이터를 수정하거나 검증을 우회하지 말고, 새 상태로 분석합니다. 이미 내보낸 ZIP은 불변 결과로 남습니다.
- 미승인 규칙집, 원문 미검증, 태깅 불일치는 보류 사유입니다. 보류를 0점이나 허위 확정 등급으로 바꾸지 않습니다.
- 서버는 127.0.0.1에만 연결합니다. 로그인 URL은 프로세스별 임시 비밀값이며 `browser.json`에 0600 권한으로 저장됩니다. CSRF·If-Match와 원문 해시 검증을 유지합니다.
- 제출용 로컬 실행이며, 외부 배포·전체 보고서 자동 범위 선택·전문가 정확도 검증의 완료를 뜻하지 않습니다.

실행 결과와 확인한 제한은 프로젝트 최상위 `outputs/submission-a-20260920/RESULTS.md`를 참고합니다.

## 로컬 웹 워커 연결 계약 (추가)

`GET /local/submission`은 로컬 pilot에서만 제공하는 인증된 읽기 경로입니다. 기존 세션의 테넌트와 pilot 테넌트가 일치해야 합니다. 응답은 `worker_enabled: boolean`, `candidate_rule_pack_id: UUID | null`, `selected_pages: positive integer[]`입니다. 비밀키·파일 경로·새 권한은 제공하지 않습니다. 워커가 없으면 `worker_enabled=false`이며 웹에서 유료 분석 시작을 비활성화합니다. 초안 ID는 기존 run snapshot에서 가져온 태깅 참고용 ID이고 규칙집 활성화가 아닙니다.

기존 `/v1/runtime-options`, `/v1/preflight`, `/v1/runs` 계약은 유지합니다. 일반 서버의 해당 local 경로는 404이며 기존 활성 규칙집 화면으로 동작합니다. DB 변경·migration은 없습니다. 되돌릴 때는 로컬 워커 플래그를 끄면 됩니다. 문서 SHA에 묶인 기존 동의·권리 범위 밖의 PDF는 계속 거절합니다.
