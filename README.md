# ESG ProofOps

현재 실행·QA 수정 기록: [QA 후속 조치](docs/QA_REMEDIATION.md). AWS 배포는 보류하고 Docling을 유지하며 OpenAI 직접 호출은 `gpt-6-luna`를 사용합니다. 과거 실험 기록은 현재 운영 상태와 구분합니다.

이 폴더는 `esg-proofops-v2`를 보존한 **Windows/Docling 파서 개발용 복사본**입니다.
원본 앱·업무 데이터베이스와 분리되어 있습니다. 실측 API 호출은 중복 예산을 만들지 않도록
원본의 기존 공용 비용 장부를 사용하며, 원본 소스 코드와 원격 배포본은 변경하지 않습니다.

## 현재 구성: Docling 직접 실행 + Upstage 독립 대조 (2026-10-10)

새 실행의 기본 파서는 `docling`입니다. 로컬 기본 프로필은 SSH `parser@gpu.example.internal:22`의
**A100 MIG 3g.40gb**, Docling **2.137.0**, CUDA 16스레드이며,
**OCR OFF / TableFormer ACCURATE / do_cell_matching=True**로 실행합니다.
ODL Java/hybrid는 이 경로에서 호출하지 않습니다. 기존 `local`, `upstage`, `azure`
모드와 저장된 실행의 재생 경로는 이전 결과 보존을 위해 남겨 두었습니다.

1. SSH 작업별 제한 시간 안에 선택한 연속 페이지를 한 번에 파싱하고 완료 결과를 캐시합니다.
2. Docling의 실제 셀 좌표·병합 범위를 직접 보존합니다. 균등한 가상 셀 좌표를 만들지 않습니다.
3. 선택 범위 **모든 페이지**를 Upstage standard로 독립 처리합니다. 전체 보고서 실행은 전체 페이지입니다.
4. 값·머리글·행 범위·원문 위치가 맞는 행에 `합의`를 표시합니다. 합의는 사실 승인과 다릅니다.
5. 불일치/원문 숫자 검증 실패 페이지에만 enhanced를 호출하고, 미해결은 `parse_conflict`로 차단합니다.
6. 출력 숫자를 해당 셀/문단 영역의 PDF 글자와 대조합니다. 다른 페이지나 다른 셀에 있는 같은 숫자는 인정하지 않습니다.
7. 그림/차트 수치는 일반 파싱 결과로 승인하지 않고 기존 비전 검토 경로에 보관합니다.
8. 원본 PDF 해시·설정·후보·API 응답·검토 결과를 저장하고 재검증합니다. 미확인 POST는 자동 재전송하지 않습니다.

빈 텍스트 레이어는 판독불가로 남습니다. 회전/비원점 crop 페이지는 검증되지 않은 좌표 변환을
추측하지 않고 명시적으로 실패합니다. PDF 텍스트에서 값을 가져와도 행·연도 연결 오류는 발생할 수 있습니다.

A100 연결·실행 설정과 217쪽 검증 결과는 [실행 기록](docs/handoff/DOCLING_IMPLEMENTATION.md)을 참고하세요.
기존 CPU 프로필은 `.local/docling-parser-cpu.json`에 보존했습니다. GPU 연결 실패 시 자동 CPU 전환은 하지 않습니다.

```powershell
./scripts/Setup-Docling.ps1
./scripts/Run-ParserLab.ps1 -Action preflight
# 유료 호출 없는 로컬 진단; 이것만으로 독립 대조 완료가 되지는 않습니다.
./scripts/Run-ParserLab.ps1 -Action docling -Pages '100,105'
# 이미 보유한 키 파일/공용 비용 장부 경로를 지정합니다.
./scripts/Run-ParserLab.ps1 -Action docling-crosscheck -Pages '100,105' `
  -KeyFile '../esg-proofops-v2/.env.upstage.local' `
  -Ledger '../esg-proofops-v2/.local/upstage/budget.sqlite3'
./scripts/Run-ParserLab.ps1 -Action test
```

필요한 키는 Upstage 대조용 `UPSTAGE_API_KEY`, 선택적 차트 비전용 `OPENROUTER_API_KEY`입니다.
Docling은 키가 필요 없습니다. 최초 모델 다운로드 후 캐시를 재사용합니다.
기존 모델 캐시를 쓰려면 `DOCLING_MODEL_CACHE`에 Hugging Face 캐시의 절대 경로를 지정합니다.
키는 Docling 자식 프로세스에 전달하지 않습니다. 기본 앱 의존성 잠금과 별개로
`.local/docling-env` 및 `config/docling-cpu-requirements.txt`를 사용합니다.
설치 전체 버전은 `.local/docling-runtime-freeze.txt`에 기록됩니다.

앱 통합 실행기 `evaluation.local_upstage_pilot`도 새 실행에는 Docling을 기본 선택합니다.
`--docling-python`으로 환경을 바꿀 수 있으며 기본 `.local/docling-env`를 탐색합니다.
기존 실행의 `--resume`은 저장된 설정을 유지합니다. API/worker의
`LOCAL_PARSER_PROFILE_PATH`에는 `parser_mode: docling`, `table_auxiliary: false`,
`docling_python: <실행파일 절대경로>`가 포함된 `ParserProfile.config_snapshot()`을 사용합니다.
Docling은 ODL 전용 표 정책/보조 파서와 함께 구성할 수 없습니다.
이 복사본에서는 바로 사용할 CPU 프로필을 `.local/docling-parser.json`에 생성했습니다.
해당 파일은 로컬 실행파일 경로를 포함하므로 다른 컴퓨터에서는 다시 생성해야 합니다.

단계별 구현·실측·남은 제한은 [Docling 실행 기록](docs/handoff/DOCLING_IMPLEMENTATION.md)을 확인하세요.
이 과거 대사 실험에서는 A100 연결을 제외했습니다. 현재 파서의 GPU 사용은 로컬 설정을 따릅니다. 대사 기능 기본 OFF, 스키마 1.2·보고서 노출은 설계 전용입니다.

아래 OpenDataLoader 내용은 이전 비교 실험 기록입니다. 현재 선택된 파서는 위 Docling 구성입니다.

## 이전 OpenDataLoader 비교 실험 계획 (보존)

사용자 요청에 따라 Azure Document Intelligence 실험을 보류하고 OpenDataLoader PDF v2.0을
평가합니다. Azure endpoint/key는 이번 계획의 선행 조건이 아닙니다. 아래는 수정된 계획이며,
2.0.0 및 하이브리드의 실측 결과가 완료되었다는 뜻이 아닙니다.

현재 의존성·설치 버전은 이미 `opendataloader-pdf==2.5.7`입니다. 다만 이전 NAVER 분석의
실제 실행 기록은 `parser_mode="upstage"`이며 Upstage Document Parse standard/enhanced와
OpenDataLoader·pdfplumber를 결합했습니다. OpenDataLoader 자체의 `hybrid="off"`와
서비스의 Upstage 사용 여부는 다른 설정입니다. 이전 결과를 ODL 단독 결과로 부르지 않습니다.
기존 어댑터는 ODL 버전을 검사하고 `hybrid="off"`로 실행합니다. 따라서 버전·모드와
원문 근거 연결을 나누어 평가합니다. `v2.0`을 정확한 릴리스 `2.0.0`으로 해석한 비교 환경을
별도로 만들고, 본 프로젝트의 잠금 파일과 기존 캐시를 덮어쓰지 않습니다.

| 순서 | 작업 | 단계별 검증 |
| --- | --- | --- |
| 1 | 이전 Upstage 결합 결과를 보존하고 2.5.7 로컬 단독 결과 생성 | PDF 해시, 버전, 설정, 실제 페이지 번호, 처리시간 및 실패 페이지 기록 |
| 2 | 별도 환경에서 정확한 2.0.0 로컬 모드 실행 | 동일 원본·페이지를 사용해 2.5.7과 텍스트·표·좌표·읽기 순서 비교; 기존 어댑터 버전 검사를 우회하지 않음 |
| 3 | 로컬 Docling 하이브리드 후보 평가 | Windows CPU에서 의존성과 실행 가능성 확인 후 소수의 복잡한 표·스캔 페이지 시험; 한국어 OCR은 ko,en; 시간·메모리 측정 |
| 4 | 후보 결과를 원문 근거 그래프에 연결 | PDF 좌표 변환, 한글 오프셋, 표의 연도·단위·행/열 제목·각주 연결, 재생 및 변조 검사 |
| 5 | 주장 추출·근거 검색·DART 대사 연결 보완 | 파싱/추출/검색/대사 오류를 따로 기록; C3/C4 생성기 누락과 정책 승인 미정은 별도로 처리 |
| 6 | NAVER 수동 기준 및 3개 보고서 회귀 평가 | 텍스트 존재와 올바른 근거 연결을 구분; 사실·수치·단위·연도·범위 일치, 미연결·오연결 수, 시간 비교 |

NAVER 우선 평가 페이지는 PDF 기준 `2,99,100,101,105,200,201,209`이며 기존 15개 수동 사례를
사용합니다. 전처리로 페이지를 잘라내는 경우 원본 페이지 매핑을 기록합니다. 기준 사례는
실험용 비교 자료이며 도메인 승인된 정답으로 승격하지 않습니다. 3개 보고서 443페이지의
기존 오프라인 검사 통과는 이번 버전 비교나 의미 정확도 평가를 대신하지 않습니다.

기본 구성은 로컬 파싱과 구조화 JSON입니다. Markdown은 검토용 보조 출력으로 사용합니다.
하이브리드는 복잡한 페이지에서 효과가 확인될 때 채택하며, Windows에서 실행이 막히면
원인을 기록하고 WSL2 대안을 검토합니다. 최초 모델 다운로드와 실제 문서 처리를 구분하고,
로컬 백엔드는 loopback에만 노출합니다. 생성된 설명이나 OCR 결과를 자동으로 검증된 근거로
인정하지 않습니다. 해당 과거 실험에서는 A100 연결을 제외했으며 스키마 1.2와 최종 보고서 노출은 설계 범위입니다.

공식 참조: [v2.0.0 README](https://github.com/opendataloader-project/opendataloader-pdf/blob/v2.0.0/README.md),
[v2.0.0 배포](https://pypi.org/project/opendataloader-pdf/2.0.0/).
공식 벤치마크 수치는 한국어 지속가능경영보고서에서의 실측 성능으로 간주하지 않습니다.

## OpenDataLoader 실험 실행

복사본 루트에서 실행합니다. 기본 앱 의존성은 2.5.7을 유지하며 실험용 2.0.0은 별도입니다.

```powershell
uv sync --frozen
uv venv .local/odl-2.0-env --python 3.12
uv pip install --python .local/odl-2.0-env/Scripts/python.exe "opendataloader-pdf[hybrid]==2.0.0" "docling[easyocr]==2.137.0"
./scripts/Run-ParserLab.ps1 -Action preflight
./scripts/Run-ParserLab.ps1 -Action odl
./scripts/Run-ParserLab.ps1 -Action odl-2.0
./scripts/Run-ParserLab.ps1 -Action hybrid -Pages '105'
./scripts/Run-ParserLab.ps1 -Action test
```

`odl`은 기존 앱 어댑터의 ODL 2.5.7 + pdfplumber 표 보조를, `odl-2.0`은 별도 환경의
2.0.0 로컬 모드를 실행합니다. `hybrid`는 2.0.0 + Docling을 Windows CPU와 한국어/영어 OCR로
시험합니다. 모델을 처음 받을 때는 인터넷이 필요합니다. 문서는 로컬 `127.0.0.1:5057`로
전달하며 백엔드는 실험 종료 시 정리합니다. 5057 포트가 이미 사용 중이면 실패합니다.
하이브리드 실험은 1페이지부터 시작하고, 최초 모델 다운로드 시간과 후속 추론 시간을
구분해서 읽어야 합니다. 모델 패키지 조합은 `.local/odl-pilot/hybrid-environment.txt`에 기록합니다.
현재 하이브리드 실험은 연속된 페이지 선택만 받습니다. 실측에서 2.0.0이 백엔드에 페이지
범위를 전달하지 않는 경우를 발견했으므로 실험 백엔드는 명시된 범위를 적용하며 그보다
넓은 요청은 거절합니다. `backend-receipt.json`의 실제 처리 페이지·원본 해시·성공 상태와
`docling-document.json`의 해시가 일치해야 성공입니다. Java 출력 파일 생성만으로 AI 처리
성공을 인정하지 않습니다. 이 실험용 보완은 ODL 패키지 자체의 수정이나 앱 배포가 아닙니다.

각 실행 결과는 `.local/odl-pilot/` 아래 새 디렉터리에 저장됩니다. 같은 결과 디렉터리를
덮어쓰지 않습니다. 로컬 앱 어댑터 실험은 검증된 아티팩트 재생도 확인하고, 별도 2.0.0은
아직 앱에 통합하지 않은 raw 실험으로 표시합니다. 지정된 8페이지의 PDF 원본 번호를
유지합니다. 기존 전체 블록 비교의 불일치는 문장 분할 차이일 수 있으므로, 별도로
`evaluation.odl_compare`를 이용해 시각 검토한 15개 인용 구절의 존재와 위치를 비교합니다.
구절·좌표 일치는 의미 검증이나 DART 대사 완료율이 아닙니다.

### 이번 실측에서 확인한 내용

- 이전 NAVER 실행은 Upstage 결합 모드였습니다. 실행 출처는
  `.local/odl-pilot/previous-upstage-provenance.json`에 보존했습니다.
- 2.0.0과 2.5.7 로컬 모드는 선정한 15개 사례의 핵심 구절과 좌표를 모두 출력했습니다.
  같은 8페이지 raw 변환 시간은 각각 약 25.2초와 25.1초입니다. 각 1회 측정이며
  전체 문서 로딩·JVM 시작이 포함되므로 엔진 단독 속도나 통계적 우열을 의미하지 않습니다.
- 로컬 모드만으로 NAVER 105페이지의 표 구조는 복원되지 않았습니다. pdfplumber 보조는
  일부 표 후보를 만들지만 열 잘림과 빈 그래프 영역 검출도 있어 개수만으로 평가하지 않습니다.
- 범위 전달을 보완한 2.0.0 + Docling 2.137.0은 105페이지의 4행·5열 표를 출력했습니다.
  이 페이지의 핵심 7개 구절도 존재합니다. Docling 실제 변환은 약 62.3초였고 모델 초기화가
  포함됐습니다. 백엔드 최대 메모리는 약 2.45GB였습니다. 전체 서비스 지연과는 다릅니다.
- 100페이지의 별도 하이브리드도 성공했고 핵심 8개 구절이 존재했습니다. 실제 Docling
  변환은 약 33.0초였습니다. 100·105페이지 합계 15개 구절의 텍스트·출력 좌표를 확인했지만
  그 좌표가 정확한지는 아래 별도 검사 결과를 따라야 합니다.
- 표의 셀 20개는 Docling 원본 좌표가 그대로 보존되지 않았거나 대응 원본 셀이 없었습니다.
  2025·2030 머리글의 선언된 열 범위도 중복됩니다. 따라서 이 결과는 자동 인용·연도 귀속에
  바로 사용하지 않습니다. `evaluation.odl_table_audit`가 이 상태를 검출합니다.
- 기존 2.5.7 클라이언트로 같은 105페이지를 교차 검사하니 백엔드에 페이지 범위가 정상
  전달됐고 핵심 7개 구절이 존재했습니다. 이 실행에서는 중복 슬롯이 없었지만 19개 셀의
  원본 좌표 보존 문제는 남았습니다. Docling 원본 출력도 실행 간 차이가 있어 머리글 차이를
  클라이언트 버전만의 효과로 단정하지 않습니다. 정확한 2.0.0으로 내리는 이점은 확인하지
  못했으며, 앱 2.5.7 고정을 유지하고 원본 셀 좌표 보존을 먼저 해결하는 편이 적절합니다.
- [원문 위 좌표 비교 화면](.local/odl-pilot/table-geometry-review.html)에서 셀을 선택해
  ODL 출력과 Docling 원본 좌표를 비교할 수 있습니다. 보고서 105페이지 시각 검토용입니다.
- 초기 하이브리드 실행 `hybrid-105`의 종료 코드 0은 실제 AI 성공 증명이 아닙니다.
  페이지 범위 전달 문제를 감지한 `hybrid-105-receipted`는 의도대로 실패했고,
  `hybrid-105-bounded`만 실제 선택 페이지 성공 영수증을 통과했습니다.

전체 보고서 검사(2.0.0 로컬 모드, 의미 정확도 평가와 별도):

| 보고서 | 페이지 | 결과 |
| --- | --- | --- |
| NAVER 2024 | 217 | 기본 예산 실패 후 600초 예산 재시험 완료. raw 변환 약 330.1초 |
| 삼성전자 2025 | 87 | 완료. raw 변환 약 112.9초 |
| 삼성SDI 2025 | 139 | 180초 및 600초 예산 모두 프로세스 실패. 최종 실행 약 586.7초 |

서로 다른 작업이 일부 동시 실행된 환경의 관측값이며 제어된 속도 벤치마크가 아닙니다.
삼성SDI 실패는 페이지별 분할·재시도 또는 대체 파싱 전략이 더 필요함을 의미합니다.
이전 native PDF 443페이지 검사 통과와 이번 ODL 전체 변환 결과는 다른 검사입니다.
기계 판독 가능한 종합 결과는 [results.json](.local/odl-pilot/results.json)에 있습니다.

현재 복사본에 추가한 것은 비교 실행기·실험 백엔드 보완·진단 검사입니다. 앱 기본 파서를
2.0.0 하이브리드로 교체하거나 C3/C4 추출기를 구현한 상태는 아닙니다. 다음 통합에서는
Docling 원본 셀 좌표를 보존하고, 중복 머리글은 검토 상태로 남겨야 합니다. 스키마 1.2와
최종 보고서 노출의 설계 전용 조건도 유지합니다.

## 이전 Azure 실험 실행 절차 (현재 보류)

Azure 구현과 이전 시험 기록은 비교 자료로 보존합니다. 아래 명령은 Azure 재개 시에만
사용하며 기본 `preflight`는 이제 OpenDataLoader 환경을 확인합니다.

1. `.env.azure.local.example`을 참고해 `.env.azure.local`에 Azure Document Intelligence
   endpoint와 key를 저장합니다. 파일은 Git에서 제외되며 브라우저로 전달하지 않습니다.
2. `uv sync --frozen`으로 이 복사본의 가상환경을 설치합니다.
3. PowerShell에서 `./scripts/Run-ParserLab.ps1 -Action azure-preflight`로 Azure 설정을 확인합니다.
4. `./scripts/Run-ParserLab.ps1 -Action azure`는 NAVER의 지정된 8개 페이지만 Azure에
   제출합니다. 페이지 목록은 PDF 실제 페이지 번호입니다. 결과는 `.local/azure-pilot/`입니다.
5. `uv run python -X utf8 -m pytest tests/integration/test_azure_layout.py -q`로 Azure 회귀 검사를 실행합니다.

Azure는 `prebuilt-layout`, API `2024-11-30`, Unicode code point 오프셋을 사용합니다.
재실행은 기존 작업 ID를 조회하거나 검증된 결과를 재생합니다. POST 응답을 잃은 요청은
자동 재제출하지 않습니다. `AZURE_DOCUMENT_INTELLIGENCE_MAX_PAGES`는 해당 SQLite 장부의
누적 제출 페이지 상한(기본 50)이며 금액 견적이 아닙니다. 실제 청구금액 미확정은 null입니다.
장부를 삭제하거나 다른 state 경로를 사용해 미확정 요청을 재제출하지 마세요.

파싱 성공은 주장·태깅·DART 대사 완료가 아닙니다. 원문 좌표가 있는 Azure 후보도 기본
`unverified`이며 기존 검증을 통과해야 합니다. 실제 Azure 응답·정확도·지연 평가는
Azure 실험을 재개할 경우 수행합니다. C3/C4 메인 태그 생성기와 도메인 승인 미비는 별도 차단이며,
스키마 1.2와 최종 보고서 노출은 설계 범위를 유지합니다.

운영 파서 프로필에 `parser_mode: "azure"`, `table_auxiliary: false`, `vision_parse: "off"`를
지정하면 기존 작업자 및 원문 조회 경계가 Azure 어댑터를 사용합니다. Azure에서는 ODL 표 보정
옵션을 사용하지 않습니다. 기존 local/upstage 프로필과 저장된 결과는 그대로 유지합니다.
이 설정만으로 모델 호출 정책·동의·태깅 승인값이 생성되지는 않습니다.

오프라인 상태 진단은 `uv run --no-sync python -X utf8 -m evaluation.pipeline_readiness --help`를
참고하세요. 진단 완료와 실제 분석 준비 완료를 구분하며, `--strict`는 차단 시 실패 코드를 냅니다.

**지속가능성 공시의 환경 주장을 원문 근거와 함께 검토하는 도구입니다.** 보고서의 주장과 근거 위치를 연결하고, 빠진 정보와 사람의 확인이 필요한 항목을 보여줍니다. 기업의 실제 환경성과나 위법 여부를 판정하지 않습니다.

## 작동 방식

```text
PDF → 문단·표 파싱과 위치 보존 → 원자 주장 추출 → 같은 문서의 근거 검색
    → 인용·귀속 검증 → 모델 분류·요소 태깅 → Python 규칙엔진 판정
    → 검토 화면·보고서 → 사람의 태깅 수정과 새 revision
```

Upstage 모델은 추출·분류·태깅에 사용합니다. E0~E3 등급과 라벨은 Python 규칙엔진이 계산합니다. 검증되지 않은 인용을 `present`로 인정하지 않고, `unknown`·`conflict`·`unreadable`을 단순한 근거 부재로 바꾸지 않습니다. 미정 규칙이나 증거 충돌은 보류 또는 등급 범위로 표시합니다. [도메인 계약](docs/00_MASTER_SPEC.md) · [미정 규칙](docs/31_DOMAIN_IMPLEMENTATION_GAPS.md)

## 서비스

<https://esg-proofops.vercel.app>에서 다음 경로를 볼 수 있습니다.

| 경로 | 내용 |
| --- | --- |
| `/` | 제품 소개와 검토 흐름 |
| `/analyze` | 브라우저에서 PDF 지문을 확인하고 분석 결과로 이동 |
| `/analyze/replay` | 저장된 처리 단계 재생 |
| `/demo` | NAVER 2025 선택 페이지의 주장·근거·등급 탐색 |
| `/demo/kia` | 기아 2025 선택 사례와 숫자·보증 확인 |
| `/review/:id` | 선택한 주장에 대한 검토 시뮬레이션 |
| `/report/naver`, `/report/kia` | 브라우저 검토 보고서와 내보내기 |
| `/live` | 한 문장 실시간 분류·태깅·규칙 계산 체험 |

**예비 등급**은 핵심 근거 일부가 확인되기 전의 판정입니다. 분류는 과반수 트랙, 요소 태깅은 단일 패스로 처리하며 검토를 거친 판정은 확정 등급으로 표시합니다. `/live`(문장 분석)는 입력한 주장과 근거 문맥을 분석하며, 제출 양식에 안내된 접근 키가 필요합니다.

## 구성

| 영역 | 기술·위치 |
| --- | --- |
| 웹 화면 | React, TypeScript, Vite · `apps/web/` |
| API·작업 처리 | FastAPI, Python · `apps/api/`, `apps/worker/` |
| 파이프라인·규칙 | Python 도메인·애플리케이션·어댑터 · `packages/proofops/` |
| 모델 연결 | Upstage 추출·태깅 어댑터 · `apps/agent/` |
| 실시간 체험 | 제한된 단일 주장 API · `api/` |
| 계약·검증 | `contracts/`, `tests/`, `scripts/` |
| 데이터·문서 | 공개용 분석 결과 JSON · `apps/web/public/demo/`; 설계 문서 · `docs/` |

로컬 실행 상태는 SQLite와 로컬 객체 저장소에 보관합니다. 문서 버전, 원문 위치, 모델·프롬프트·규칙 해시, 수정 revision을 추적합니다. `config/`에는 고정된 규칙 구성이 있습니다.

## 로컬 실행

Python 3.12, `uv`, Node.js, `pnpm`이 필요합니다.

**웹 화면**은 API 키와 PDF 원본 없이 열 수 있습니다.

```bash
pnpm install --frozen-lockfile
VITE_DEMO_STATIC=true pnpm --filter proofops-web dev
```

**저장된 실제 실행 결과**가 별도로 있다면, `pilot.json`을 포함한 권리 확인된 상태 디렉터리를 복사해 로컬 API와 화면을 엽니다. 공개 저장소에는 그 상태와 보고서 원본이 없습니다.

```bash
uv sync --locked
uv run python scripts/submission_demo.py --seed /path/to/saved-pilot-state --port 8790
```

**새 PDF 분석**에는 사용 권한이 있는 PDF, 로컬 `.env.upstage.local`의 `UPSTAGE_API_KEY`, 이미 승인되어 생성된 `.local/upstage/budget.sqlite3` 예산 장부가 필요합니다. 다음 명령은 입력 계획만 확인합니다. 유료 모델 실행을 명시할 때 `--invoke`를 추가합니다. 선택 페이지를 제한적으로 처리하므로 보고서 전수 분석을 뜻하지 않습니다. [실행 세부사항](docs/SUBMISSION_DEMO.md)

```bash
uv run python scripts/analyze_report.py --pdf /path/to/report.pdf \
  --pages 25,117,138 --report-year 2025 \
  --period-start 2025-01-01 --period-end 2025-12-31
```

## 범위와 권리

공개 결과는 선택 페이지·선택 주장에 한정됩니다. 원문 판독 불가, 근거 귀속 충돌, 미승인 규칙은 보류합니다. 독립 정답 자료에 대한 정확도, 전체 보고서 성능, AWS 운영 배포, 법적 면책 효과는 검증 결과로 주장하지 않습니다.

원본 보고서 PDF와 페이지 이미지는 재배포 권리를 확인하지 못해 저장소에 넣지 않았습니다. 공개 화면에는 짧은 인용, 물리 쪽번호, 공식 보고서 링크와 파생 데이터만 포함합니다. 코드의 별도 `LICENSE` 파일이 없으므로 사용·재배포 허가를 추정하지 마세요.

## 팀

- **Developer A:** 공시 파이프라인과 웹 화면
- **Developer B:** DART·재무 대사(C1–C4)
