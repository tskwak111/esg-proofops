# Docling 직접 파서 실행 기록

2026-10-10 · 수정 위치: `esg-proofops-parser-lab` · Windows 클라이언트 + SSH A100

## 최종 실행 대상: A100 (2026-10-10)

- `parser@gpu.example.internal`, SSH 22번, 기존 키 및 known_hosts로 접속 확인.
- CUDA에서 보이는 장치: NVIDIA A100 80GB PCIe **MIG 3g.40gb** 한 개.
  작업 시작 시 A100·단일 장치·40GB 할당을 검사한다. 다른 GPU로 자동 전환하지 않는다.
- 기존 Python `/home/user5/parser-bench/vd/bin/python`: Docling 2.137.0, torch 2.14.1+cu130.
- 시스템 NVML/커널 드라이버 버전 불일치는 기존 `/home/user5/parser-bench/nvlib`를
  작업 명령의 `LD_LIBRARY_PATH`에 지정하여 해결했다. 시스템 드라이버는 변경하지 않았다.
- OCR OFF, ACCURATE, cell matching ON, CUDA 16스레드.
  Markdown은 `traverse_pictures=True`로 그림 내부 텍스트를 포함한다.
  표시용 Markdown에서만 `\x07`을 제거하고 원본 텍스트·좌표는 보존한다.
- `.local/docling-parser.json`과 `.local/docling-parser-a100.json`이 현재 원격 프로필이다.
  기존 CPU 설정은 `.local/docling-parser-cpu.json`에 보존했다.
  신규 로컬 pilot/PowerShell 실행은 기본 프로필의 SSH 대상을 읽는다. 저장된 실행은 기존 설정을 유지한다.
- SSH host key 검증 및 BatchMode를 사용한다. GPU 서버에 API 키를 복사하거나 HTTP 서비스를 열지 않는다.
  PDF와 결과는 `/home/user5/esg-proofops-docling/jobs/<uuid>/`의 비공개 작업 폴더에 남긴다.
  원격 실행 제한은 600초, 전체 문서 출력 한도는 128MiB다.

실제 확인 결과:

| 확인 | 결과 |
| --- | --- |
| NAVER 전체 | 217쪽, 표 127개 |
| 기존 본문 / 표 행 검증 | 15/15, 16/16 |
| 표시 Markdown 제어문자 | `\x07` 0개 |
| 원격 변환 + 글자 좌표 + Markdown | 158.161초 |
| 전송·로컬 검증 포함 전체 | 225.219초 |
| Upstage 실제 교차검증 | 100·105쪽 실행 완료, immutable replay 통과 |
| 관련 자동 테스트 | 101개 통과, lint 및 타입 검사 통과 |

사용자가 측정한 41.9초는 모델 로딩 후 순수 변환 시간이다. 위 158.161/225.219초와
측정 범위가 다르므로 속도 향상·저하 비교에 직접 사용하지 않는다.
217쪽 실행은 **Docling 및 원문 검증만 수행한 진단 실행**이다. 전체 Upstage 대조나
127개 표의 의미 정확도를 승인한 결과가 아니다. 교차검증이 없는 숫자와 미해결 차트는 계속 차단한다.
실제 2쪽 Upstage 대조도 불일치를 남겼으며 재생 성공이 합의 또는 정답을 뜻하지 않는다.

결과: `.local/docling-pilot/a100-full-217/summary.json`,
`.local/docling-pilot/a100-validation.json`, `.local/docling-pilot/a100-crosscheck/summary.json`.
전체 문서 초기 실측 캐시는 integrity 필드 도입 전 기록으로 보존했으며,
현재 캐시는 별도 v2 namespace와 payload digest로 검증한다.

명시적인 원격 진단 실행 예시 (새 출력 폴더 사용):

```powershell
.venv\Scripts\python.exe -X utf8 -m evaluation.docling_pilot `
  --pdf 지속가능경영보고서/NAVER_2024_KOR.pdf --pages 100,105 `
  --ssh-target parser@gpu.example.internal --output .local/docling-pilot/new-a100-run
```

Upstage 대조는 기존 `--invoke-upstage --env-file <키 파일> --ledger <공용 장부>` 옵션을 함께 지정한다.
키는 로컬에서만 읽는다. 아래 CPU 기록은 이전 단계의 실측 이력이다.

## 구현 순서와 범위

| 단계 | 구현 | 검증 |
| --- | --- | --- |
| 1 | 직접 Docling 2.137.0, OCR OFF, ACCURATE, PDF 셀 텍스트 매칭 | 실제 NAVER 100/105쪽, 원래 셀 좌표 보존, 별도 Python 환경 |
| 2 | 모든 선택 페이지 Upstage standard, 불일치 페이지 enhanced, 미해결 차단 | 실제 보고서 3종 및 값·부호·연도·좌표·비독립 파서 거부 테스트 |
| 3 | 숫자 영역 검증, 차트 분리, immutable manifest 재생 | 변조 거부, 재시도 중복 호출 방지, 실제 worker 저장/재조회 |
| 4 | 기본 실행 설정·검토 화면·실행 스크립트·문서 | 기존 모드 회귀, 타입/린트/아키텍처, 웹 빌드 |

`OpenDataLoaderParser`의 공개 진입점은 기존 호출자 호환을 위해 남겨 두고
`parser_mode=docling`에서 직접 `DoclingParser`로 위임한다. 이 분기에서는
ODL 버전 검사, Java 실행, ODL hybrid, pdfplumber 보조 표 파싱을 하지 않는다.
Upstage 후보의 원문 위치 확인에 쓰는 PDF reader는 독립 모델로 세지 않는다.
Docling과 Upstage standard/enhanced의 가족은 각각 `docling`, `upstage-document-parse`다.
standard/enhanced를 독립 모델 두 개로 세지 않는다.

## 근거 보존과 차단 기준

- 셀 박스는 Docling `table_cells[].bbox`의 실제 좌표를 사용한다. 병합 셀을 균등 분할하지 않는다.
- 숫자는 부호·소수점·천 단위 구분자·백분율을 유지해 **해당 영역 안의 PDF 글자**와 비교한다.
- 합의는 행의 셀 값, 첫 머리글 행, 병합 범위, 페이지와 영역이 함께 맞아야 한다.
  구조가 다르거나 후보가 모호하면 합의를 만들지 않는다. 정밀도 우선의 보수적 기준이다.
- 기존 의미 검증/원문 승인 단계를 생략하지 않는다. `parser_consensus`는 정보성 `resolved`
  항목이며 SourceRef를 `source_verified`로 승격하지 않는다.
- 미해결 블록은 `winner=None`, `quality=conflicted`, `parse_conflict`로 남아 선택된 원문을 내보내지 않는다.
- enhanced가 처리한 페이지의 standard는 원본 receipt에 보존하고 활성 그래프에서는 제외한다.
- 머리말·꼬리말은 본문 숫자 주장과 분리한다. 빈 텍스트 레이어는 `unreadable`이다.
- 모델이 만든 숫자뿐 아니라 잘못 붙은 값도 거부할 수 있지만, 검증된 모든 숫자가
  의미적으로 정확하다는 보장은 없다. 별도 사람 검토와 도메인 검증이 필요하다.

## 실제 보고서 실험

| 보고서 | 물리 페이지 | 최초 대조 실행 | 캐시 재검증 |
| --- | --- | ---: | ---: |
| NAVER 2024 | 2, 99, 100, 101, 105, 200, 201, 209 | 456.703초 | 68.719초 |
| 삼성전자 2025 | 10, 36, 60 | 230.734초 | 19.766초 |
| 삼성SDI 2025 | 12, 40, 80 | 161.562초 | 26.110초 |

총 **대표 14페이지**다. 전체 443페이지의 Docling 대조를 완료했다는 뜻이 아니다.
CPU 파싱·기존 캐시·원문 검증·API 대기·저장/재생이 포함된 벽시계 시간이며
일부 실행은 다른 회귀 검사와 겹쳤다. 동일 하드웨어의 통제된 속도 벤치마크가 아니다.

NAVER 105쪽은 OCR을 끄고도 2025/2030 머리글의 병합 범위 겹침이 관측됐다.
PDF 텍스트에 있던 제어문자도 남았다. 실제 좌표 보존은 해결했지만 머리글 해석을
자동으로 정답 처리하지 않았다. 많은 행/문단이 서로 다른 범위로 나뉘어 불일치로
남는다. 이번 결과로 기존 Upstage보다 의미 정확도가 높아졌다고 주장하지 않는다.

최종 근거:

- `.local/docling-pilot/results.json`: 보고서별 입력 해시, 페이지, 검증 상태, 수치, 제한
- `.local/docling-pilot/naver-final/review.html`: 원문·파서·행/열·좌표·상태 검색
- `.local/docling-pilot/naver-anchors.json`: 기존 수동 15개 인용의 텍스트/좌표 존재 비교
- `.local/docling-pilot/*-final/summary.json`: 각 실행과 immutable manifest 경로
- `.local/docling-artifacts/`: 원본 응답·후보·검토/라우팅·해시·페이지 캐시

이 비교의 기준 인용은 실험용 자료다. 전문가 승인 gold나 전체 보고서 재현율이 아니다.
NAVER의 고정 15개 인용은 모두 원문 텍스트와 파서 좌표가 발견됐다(15/15).
이는 해당 값의 연도·범위·의미 연결이 승인됐다는 뜻이 아니다.

## API 비용과 실패 처리

기존 공용 Upstage 장부의 한도 안에서 실제 API를 호출했다. 별도 장부를 새로 만들어
기존 예산 한도를 초기화하지 않았다. NAVER 최초 receipt는 standard 8쪽 $0.088,
enhanced 8쪽 $0.264였다. 캐시 재검증은 이 receipt를 재사용하며 같은 금액이
다시 청구됐다는 뜻이 아니다. 다른 보고서 비용은 `receipts.json`에서 확인한다.

각 POST 전 `.pending`에 원본/페이지/모드와 로컬 요청 ID를 먼저 남긴다.
요청이 전송됐는지 불확실하면 재전송하지 않고 운영자 확인을 요구한다.
명확한 `BUDGET_EXHAUSTED` 예약 거부는 전송 전 실패이므로 이후 예산 확보 시 재시도할 수 있다.
사용된 키는 파일·로그·Docling 자식 프로세스에 복사하지 않는다.

차트 비전은 실제 실행했으나 **OpenRouter HTTP 402 / Insufficient credits**였다.
키 확인 API는 200을 반환했으며, 실제 이미지 요청의 응답은 계정에 크레딧 구매 이력이
없다는 내용이다. 키 교체 또는 계정 크레딧 준비가 필요하다. 결제는 수행하지 않았다.
`vision-diagnostic.json`, `vision-request-diagnostic.json`에 비밀 값 없는 진단이 있다.
모델 ID 자체는 [OpenRouter 공식 모델 목록](https://openrouter.ai/google/)에서 확인했다.
실패 시에도 파싱·대조 근거는 보존되고 차트는 검토 대상으로 차단된다.

## 개발자 B 나머지 단계

기존 D-01~12/14/16/17 구현은 대사 회귀 검사로 확인했다. 회사 연결, 접수번호 pin,
운영자 초안 생성, 출처/기간/coverage, 정책 미승인 차단 및 기본 OFF 조건을 유지한다.

현재 외부 의존 사항:

1. 메인 태그 생성기의 `currency_amount` / `revenue_share` producer 부재.
   C3/C4 엔진 구현과 메인 producer 연동은 다른 단계다. 임의의 확정 태그로 우회하지 않았다.
   관련 계약: `packages/proofops/application/linkage_exchange.py` 및 `DART_IMPLEMENTATION.md`.
2. 실제 기업·사업연도·접수번호·연결/별도 구분·정책/정답 승인자 미정.
   오프라인 계약 검증을 실제 기업의 승인된 대사 결과로 바꾸지 않았다.
3. OpenRouter 크레딧 부족으로 실제 차트 비전 검증 미완료.
4. A100 연결은 위 최종 실행 대상에 반영했다. 스키마 1.2와 보고서 노출은
   `DART_DESIGN_1_2_AND_EXPORT.md`의 설계만 유지한다.

## 검사 기록

- 신규 경계/재생/worker 테스트: `docling-tests.xml` **20 passed**.
- 대사·기존 런타임·Azure·그래프 회귀: `regression-utf8.xml` **925 passed**.
  이 묶음에는 당시 신규 테스트 15개가 포함돼 있으므로 두 수를 합산하지 않는다.
- 추가 파서/파일럿 회귀: `parser-regression-final.xml` **100 passed** (신규 20개 포함).
- Ruff, 신규 모듈 4개 mypy, `verify_architecture.py`, `pnpm --filter proofops-web build` 통과.
- Windows 테스트/실행은 `PYTHONUTF8=1` 또는 `python -X utf8`를 사용한다.
  기본 cp949로 실행한 첫 전체 검사 실패는 별도 로그로 보존했다.

원격 배포와 push는 수행하지 않았다. A100 SSH 접속과 실제 Docling 실행은 완료했다.
