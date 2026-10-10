# 개발자 B 실행 기록

2026-10-09 · `dart-dev` · 기준 커밋 `ebec0a5498da569811481b79f9b4e7004cf0c5fb`

## 범위와 단계

사용자 요청에 따라 C1~C4를 단계별 구현·검증한다. D-13 스키마 1.2와 D-15
보고서 노출은 설계만 작성한다. 실기업/사업연도/정책 승인자/정답 승인자는
미정이며 승인값을 만들지 않는다. 보고서 PDF는 공식 사이트에서 내려받아
로컬 출처 검증에 사용한다. 원격 push·배포·실제 DART 평가를 완료했다고
간주하지 않는다.

| 단계 | 과제 | 검증 경계 |
| --- | --- | --- |
| 1 | D-01~04: 기준선, 회사 연결, 메인 계약, 접수번호 pin | 기존 행 보존, 테넌트/권한, 마이그레이션, 오프라인 DART |
| 2 | D-05~08: 운영자 생성, HTTP 연결, 기능 플래그, 정책 초안 | 현재 태그 결속, 원문 검증, G/P/M 불변, 승인 전 blocked |
| 3 | D-09~12/14/16: 설명·coverage·기간·평가·한도 | 누락/상한/변조 거부, 기간 불일치, gold 분모 |
| 4 | D-13/15 설계, D-17 CI/문서, 실제 PDF smoke | 1.1 유지, 린트/타입/회귀/빌드, 원문 3종 |

## 과제별 산출물

| ID | 산출물과 완료 경계 |
| --- | --- |
| D-01 | 기준선 검증 기록, 로컬 dart-dev 체크아웃 |
| D-02 | 스키마 v2 회사 연결/감사 테이블, link_company CLI, 마이그레이션/권한 테스트 |
| D-03 | 메인 private API와 현재 태그 head의 동작 계약 테스트; 메인 API 재설계 없음 |
| D-04 | 정기/정정 목록, as_of 필터, 원본 응답 해시, 명시적 pin과 보존 이력 |
| D-05 | 주장 기반 운영자 생성 CLI, 공유 초안 binding, pending 등록, 현재 head CAS |
| D-06 | HTTP 연결 스모크와 G/P/M·기존 export 불변 검사; 합성 경계와 실기업 평가 구분 |
| D-07 | 백엔드/프런트 기본 OFF 플래그, OFF 테이블/라우터 미생성 검증 |
| D-08 | 1.1 미승인 정책 생성 도구, C3 수치·계정 허용목록 미설정 |
| D-09 | 등록된 범위 내 결정적 설명 후보 검색, 사람의 정확한 차이 결속 검증 |
| D-10 | 페이지/주석 coverage sidecar, 누락·판독불가·검토미완료 거부 |
| D-11 | 후보 상한 truncation의 prepare/store/service/UI 전파 |
| D-12 | C2 사실 기간 및 C4 정의/분모 기간 결속, 보고서 연도 자동 전용 없음 |
| D-13 | 별도 1.2 매핑/다년 CAPEX 설계만 작성; 실행 스키마 미변경 |
| D-14 | gold manifest 평가 및 명시적 열 이름을 받는 CSV 어댑터; 실제 전문가 CSV 미제공 |
| D-15 | 독립 대사 부록/옵트인 설계만 작성; 기존 export 코드 미변경 |
| D-16 | 요청/재시도 집계, 429/020 일시중단·재개 진단, 키 마스킹 |
| D-17 | dart-dev CI 트리거, 새 모듈/계약 회귀 검사 포함, 문서와 로컬 검증 기록 |

## 운영자 도구

저장소 루트에서 `uv run --no-sync python -X utf8 -m <모듈> --help`로
필수 인자를 확인한다. 아래 도구는 로컬 운영자용이며 사용자 HTTP 입력의
파일 경로를 신뢰하는 기능이 아니다.

| 모듈 | 역할 |
| --- | --- |
| `evaluation.reconciliation_link_company` | tenant/company와 corp_code 연결 및 감사 |
| `evaluation.reconciliation_filings list` | 명시적인 네트워크 허용 하에 정기·정정 목록 수집 |
| `evaluation.reconciliation_filings pin` | 목록 중 운영자가 고른 접수번호를 새 스냅샷에 고정 |
| `evaluation.reconciliation_prepare` | 기존 후보 목록에서 운영자가 고른 초안 생성 |
| `evaluation.reconciliation_from_claim` | 현재 검증된 주장/태그와 준비 초안으로 pending 케이스 등록 |
| `evaluation.reconciliation_policy_draft` | 값·승인을 만들지 않는 1.1 정책 초안 |
| `evaluation.reconciliation_eval_kia` | 명시적 gold manifest 비교 및 선택적 전문가 CSV 결합 |
| `evaluation.reconciliation_report_smoke` | 로컬 PDF 전체 추출·출처/변조/페이지 검증·대표 렌더 |

서버 `ENABLE_RECONCILIATION=true`, 프런트 `VITE_ENABLE_RECONCILIATION=true`를
명시해야 대사 기능이 노출된다. 기본 OFF다. 환경 파일의 API 키는 문서·로그에
복사하지 않는다. DART 목록 조회만 DART_API_KEY를 사용하며, 이번 오프라인
검증과 다운로드한 PDF 테스트에는 API 키가 필요하지 않았다.

실행 순서: 회사 연결 → 목록/운영자 pin → 기존 후보 prepare → from_claim →
인증된 reviewer 검토 → admin 정책 승인 → evaluate → 고정 revision/원문 조회.
정책·금액 기준·근거가 부족하면 계속 blocked로 남는다. C3/C4에 필요한 메인
태그 생성기가 없는 경우 B가 임의 태그를 만들어 이 경계를 우회하지 않는다.

from_claim은 업로드 계약에 발행일이 없을 때 `--sr-published-at YYYY-MM-DD`로
운영자의 명시적 제안을 받는다. 생략하면 발행일 누락으로 blocked다.
`--coverage-proposal FILE`의 JSON은 `search`와 `coverage` 두 키로 구성하며,
새로 만드는 packet의 정확한 문서/source ID, 해시와 전체 페이지/주석을 가리켜야
한다. 이를 전달해도 검토 전에는 신뢰하지 않는다. 사실별 기간은 draft의
`fact_bindings` sidecar에 명시한다(C2 SR 기간은 인용에 결속된
`--c2-period-context`에서 검증). 기존 upload 시간이나 보고서 전체 기간으로
누락값을 채우지 않는다.

## 실제 보고서 검증

로컬 폴더: `지속가능경영보고서/` (PDF와 원문 텍스트는 Git 제외).
정확한 URL/크기/SHA256은 그 폴더의 `sources.json`에 기록한다.

| 보고서 | 총 페이지 | 텍스트 추출 페이지 | 추출 텍스트 없는 페이지 |
| --- | ---: | ---: | --- |
| NAVER 2024 통합보고서 | 217 | 215 | 1, 217 |
| 삼성전자 2025 지속가능경영보고서 | 87 | 86 | 87 |
| 삼성SDI 2025 지속가능경영보고서 | 139 | 138 | 139 |

총 443페이지 중 439페이지에서 텍스트가 추출됐다. 추출 예외 0건,
각 PDF의 실제 인용/바이트 변조/인용 변조/범위 밖 페이지 검증 12건 통과.
각 3페이지 대표 렌더를 시각 검사했다. 삼성SDI는 비치명적 xref 보정 경고와
추출 제어문자가 있어 기록에 남겼다. 이는 OCR 품질이나 의미 정확도 평가가
아니며 빈 텍스트 페이지를 자동으로 판독 완료로 처리하지 않는다.

근거: `.local/report-smoke/summary.json`, `validation.json`,
`visual_inspection.json`, `report.txt`, 각 보고서 하위 폴더.
`semantic_evaluation=not_run`, `semantic_gold=null`, `policy_approval=null`을 유지한다.

## 검사 기록

- D-01 기준선: `.local/d01-baseline-20261009-1/checks.json` 15/15,
  기준선 pytest 880개 및 프런트 빌드 통과.
- 회사 연결/기존 저장소 단계: 87개 통과.
- 접수번호/한도/기존 DART 경계 단계: 100개 통과.
- 검색·검토·HTTP·저장소 통합 단계: 124개 통과.
- 기능 플래그 및 제품/API 연결: 132개 통과. 추가 기존 API/인증/업로드/규칙 회귀
  347개 통과, 선택적 로컬 저장 상태 검사 1개 skip.
- CSV/gold 평가 단계: 29개 통과.
- 실제 PDF smoke 및 source reader 단계: 15개 통과.
- 기존 주장/태그 연결 통합: 13개 통과, 환경 조건 1개 skip.
  skip은 선택적 `.local/r24-cli-rereview` 저장 상태가 없기 때문이다.
- 배포 준비 검사 회귀: 48개 통과 (새 회사 연결 테이블의 불변성 검사 포함).
- 브라우저 React 화면: 16개 검사 통과, `.local/browser-tools/result.json`.
  통제된 HTTP 응답을 사용하는 컴포넌트 검사이며 실제 서버 E2E와 구분한다.
- 전체 Linux 대상 mypy: 299개 파일 통과. Windows 기본 대상의 기존 POSIX
  resource/flock 코드 9개 타입 오류는 변경 범위 밖이며, B 신규 모듈 타입 검사는 통과.
- 아키텍처 검사와 프런트 production build 통과.
- 최종 주장 생성/실제 HTTP 연결 집중 검사: 31개 통과. 근거가 완비된 합성 C2는
  검토·정책 승인 이후 `completed/matched`, 다른 테넌트·페이지 누락·상한초과·
  coverage 미확인은 blocked. 원래 G/P/M head와 export 불변도 검증했다.

위 숫자는 단계별 중복 테스트를 포함하므로 합산한 고유 테스트 수가 아니다.
최종 통합 검사(2026-10-09)는 15/15 통과했다. pytest는 1,080개 통과,
선택적 로컬 데이터가 필요한 1개 skip이며, 린트·포맷·대사/제품 타입 검사·
아키텍처·fixture 생성·8개 CLI 시나리오가 모두 통과했다.
재현 명령: `uv run --no-sync python -X utf8 scripts/verify_reconciliation.py --output <새 증거 폴더> --timeout-seconds 600`.
최종 증거: `.local/developer-b-final-20261009/checks.json` 및 같은 폴더의
검사별 JSON(특히 `01_pytest.json`). 원격 CI 실행 결과와는 구분한다.

## 외부 조건과 설계 범위

- 실제 기업의 corp_code/사업연도/pin/정책/정답은 아직 승인하지 않았다.
- 전문가 원본 CSV 8행이 제공되지 않아 합성 CSV로 어댑터를 검증했다.
  임의 정답이나 coverage 영수증을 생성하지 않는다.
- CI에는 dart-dev 트리거와 Ubuntu/Windows/macOS 검사를 구성한다.
  push 전이므로 원격 CI 성공 여부는 미실행이다.
- 스키마 1.2·보고서 노출: [설계안](DART_DESIGN_1_2_AND_EXPORT.md).
- `validate_package.py`는 현재 체크아웃에 없으므로 해당 검사를 실행하지 않는다.
