# ESG ProofOps 개발 인수인계 — finals v29b

2026-10-16 운영 기준: 백엔드 `6bd7fc3438354369904c978ac5fb8fcd85cea0a8`,
웹 `4fcbaa81297c0a95337a7abb23b7e550b5e662f9`. 공개 release는 이 스냅샷에서
비공개 자료를 제외한 별도 커밋이다. 서버 접속·배포·새 모델 호출 없이 작성했다.

## 제품과 실행 경계

기업 공시 안의 환경 주장을 같은 문서의 근거와 연결하는 발간 전 검토 도구다.
실제 환경성과·진위·위법·면책을 판정하지 않는다. LLM은 추출과 태깅만 수행하고
순수 Python 규칙엔진이 E0–E3와 라벨을 계산한다. E3는 SUBSTANTIATED,
E1/E2는 INCOMPLETE, E0는 UNSUBSTANTIATED이며 보류는 별도 상태다.

현재 hosted 경로는 브라우저 → Vercel 웹의 `/hosted-api` → EC2의 Caddy/FastAPI
→ worker → Upstage 파싱/OCR·OpenAI 추출/태깅이다. SQLite와 비공개 로컬 파일에
원본·상태·체크포인트·비용 영수증을 보존한다. 초기 Master의
S3/DynamoDB/Bedrock/AgentCore 구성은 현재 hosted 배포와 구분한다.

| 위치 | 책임 |
| --- | --- |
| `packages/proofops/domain` | 네트워크·파일·환경변수·SDK 없이 판정과 근거 계약 계산 |
| `packages/proofops/application` | 정책 핀, 고정 근거 패킷, 합의와 게시 orchestration |
| `packages/proofops/adapters` | 파서·OCR·원문 검증·저장·모델 연결 |
| `apps/api/src/proofops_api/hosted_store.py` | 권한·접수·예산·SQLite 상태와 재사용 진입점 |
| `apps/worker`, `apps/agent`, `evaluation/hosted_r108.py` | 파이프라인 실행·중단·추출/태깅 |
| `config`, `contracts`, `prompts` | 규칙·기계 판독 계약·프롬프트 |
| `deploy/ec2`, `deploy/public` | 이미지·배포·drain·운영 계약 |

## 파이프라인

1. 로그인·권리 동의·PDF 보안 검사 후 테넌트, 원본 해시와 문서 버전을 고정한다.
2. 주장 쪽/근거 쪽 후보와 보고기간을 확인하고 유효 분석 범위를 고정한다.
3. 문단·표·OCR을 구조화하고 물리 쪽·좌표·파서 출처를 보존한다.
4. LLM으로 원자 주장과 인용 후보를 추출한다. 추출하지 못한 입력을 가짜 주장으로 만들지 않는다.
5. 인용 문자열·스팬·표 행/열·좌표를 원문과 대조하고 주장 귀속을 검사한다.
6. 동일한 고정 근거 패킷에 대해 독립 replica 3회를 기록한다.
7. 유형 합의, 요소 합의와 충돌을 검사하고 아래 승인된 범위 정책을 적용한다.
8. Python 규칙엔진이 사다리·특칙·미정 규칙을 적용해 등급 또는 보류를 계산한다.
9. 봉인된 결과와 원문 위치를 게시한다. 사람은 태그만 수정하고 `If-Match`를 거쳐
   새 revision을 만든다. 과거 태그·판정·보고서를 덮어쓰지 않는다.

## 승인된 도메인 결정과 현재 구현

원문 v2와 [Master](00_MASTER_SPEC.md)를 기본으로 읽되, 아래는 후속 사용자 승인으로
변경된 범위다. 비공개 결정 로그 자체는 공개 저장소에 포함하지 않는다.

| 결정 | 의미 및 v29b 적용 |
| --- | --- |
| DEC-85 | `absent_in_scope`를 문서 전체 부재와 구분. 초기에는 범위 재탐색·3/3 미발견을 요구했다. 현재의 추가 허용은 DEC-125/127로 한정한다. |
| DEC-92 | 주변 문맥으로 독립 주장/근거 설명을 구분하고 표의 행/값을 대조한다. 세부 허용은 DEC-93 승인 범위로 구현한다. |
| DEC-93 | AP-03: 선택 범위의 타 문단 기준연도·기준값은 원문 verified 및 동일 주체·지표·단위·경계 결속 시 G2/G3에 연결. AP-06: M1/M4의 원거리 근거는 명시적 주어·활동·대상·기간 연결 필요. 추정 실적을 present로 승격하지 않으며 전망은 전망으로만 유지. 세이프하버는 범주만 표시하고 미승인 등급은 null. 충돌은 보존한다. |
| DEC-123 | 화면은 범위 기준 확정을 일반 “확정”으로 합산·표시한다. API의 범위·정책·원시 근거 필드는 유지한다. |
| DEC-125 | 완료된 3회 중 요소 2/3의 검증된 값·귀속·범위 합의 허용. 검증된 반대 근거나 충돌은 차단한다. 유형은 3/3 유지. 선택 쪽 밖 근거 탐색 확대도 승인되었지만 CF7은 v29b에 통합되지 않았으므로 전체 문서 탐색 완료로 표현하지 않는다. |
| DEC-127 | 3회 태깅 완료 후 분석한 쪽 안에서 검증·연결하지 못한 요소를 `absent_in_scope`로 처리한다. SC1 완전 탐색은 더 이상 선행 조건이 아니다. 문서 자체에 근거가 없다는 뜻이 아니며 시스템 개선 후 새 분석에서 present로 바뀔 수 있다. |

현재 구현은 [CF6 계약](CF6_ELEMENT_CONFIRMATION.md),
`application/tagging/cf6_confirmation.py` 및 `domain/rules/cf6_scope.py`를 함께 확인한다.
`present`에는 검증 원문과 귀속이 필수다. conflict·unreadable·주장 원문 미검증·유형
미합의·등급 차단 GAP·미완료 replica·TIME_BUDGET은 부재로 바꾸지 않는다.
숫자/목표연도의 무조건적인 전역 인정은 금지하며 AP-03의 제한적 기준값 연결과 구분한다.

## 현재 정책과 시간·비용 한계

`finals-unattended-v2`의 기본은 `finals-20261016-v29b`다.
정책 SHA256은 `9fd37ccb4d397e2b3b4c0a468502cca4aed18dbb5d9a0853a72e0d7cae33153d`.
v29에 HF1의 SC1 JSON schema 지시 복원과 HF2의 RB3 v2 시간 정책이 반영된 운영 코드다.
기존 정책 객체·원문 reader·receipt 해시를 스타일 정리로 바꾸지 않는다.

- 최대 분석 시간 2,700초, 신규 추출 투입은 1,500초, 태깅/SC1은 2,400초까지다.
  마지막 300초는 진행 중 작업과 게시 여유다. 더 짧은 부모 제한이 우선하며 입력에 따라
  TIME_BUDGET/부분 완료가 남는다. HF2 모의 결과를 실서버 시간 해결의 증거로 쓰지 않는다.
- 모델 처리 비용은 실행 USD1·일 USD7 코드 상한이다. 일일 상한은 환경값을 높여 우회할 수 없다.
  행사 상한/승인 ceiling은 별도이며 실제 운영값은 비공개 설정을 확인한다.
  전송 전 예약·후정산을 유지하고 미정산 비용을 삭제하거나 자동 재호출하지 않는다.
  이 가드는 인프라 전체 청구액 상한이 아니다.
- CF3는 잘못된 present 후보가 관측되어 미통합, S7은 속도 이득 대비 동결 위험으로 미통합이다.
  CF7도 미통합이다. 해당 브랜치의 성과를 v29b 기능으로 표시하지 않는다.
- DEC-127은 못 찾은 근거를 범위 내 부재로 확정하므로 실제 원문에 근거가 있어도 과소등급이
  생길 수 있다. “확정”은 시스템 규칙 계산의 완료이며 전문가 정답·현실의 진실 보장이 아니다.

## RC1 결과 재사용

[RC1 계약](contracts/rc1-result-reuse-v1.md)과 `hosted_reuse.py`를 확인한다.
키는 요청 PDF 바이트 SHA256 + 실제 배정 정책 + 유효 분석 범위/쪽 + 보고기간이다.
서로 다른 계정도 동일 PDF를 직접 업로드하고 권한·범위 검사를 통과해야 재사용 가능하다.
완료 또는 주장이 있는 partial_blocked의 봉인 revision 1만 대상이며 실패·진행 중·만료·삭제·
변조·미게시·0주장·알 수 없는 정책은 재사용하지 않는다. 과거 partial 결과의 보류도 유지된다.

새 요청자 소유 문서/run으로 복사하고 원본은 요청자의 PDF를 참조한다. 공급자 호출·비용·
예약·일일 실행 수 차감은 0이며 화면에 이전 분석 일시를 표시한다. 사본은 읽기 전용이다.
관리자 `force_fresh=true`만 새 분석을 강제할 수 있고 기존 예산/권한 검사를 그대로 따른다.
코드 플래그 `RC1_RESULT_REUSE_ENABLED`의 기본은 false다. 운영 활성 여부는 관리자가 확인한다.
좌표 일시 경합은 `REUSE_COORDINATES_BUSY`/429와 재시도 안내이며 유료 분석으로 우회하지 않는다.

RC1은 감사 테이블·인덱스·불변 트리거를 추가하는 idempotent migration이다. 기존 행/결과는
재작성하지 않는다. 알려진 한계로 사본 `duplicate_occurrences`에 원 실행 claim ID가 남을 수
있어 그룹 표시/내보내기 회귀가 필요하다. HO1에서 이를 수정하거나 운영 결과를 재작성하지 않았다.

## 배포와 롤백

배포는 승인된 운영자만 수행한다. 실제 계정·주소·키·초대 코드·쿠키는 이 문서나 Git에 넣지 않는다.
`deploy/ec2`의 공개 계정 값 `000000000000`은 실행 불가능한 자리표시자다. 실제 계정과
일치해야 하는 가드를 삭제하지 말고, 승인된 비공개 배포 사본에서 코드·정책·설정의 계정 핀을
일치시킨다. 공개 템플릿 그대로는 기존 서버에 배포할 수 없다.

1. 승인된 AWS 프로필과 SSM 접속 설정으로 기존 EC2에 접근한다. `deploy/ec2/deploy.sh`의
   실제 전송은 SSH/scp이며 현 운영 환경의 SSM 터널/SSH 설정을 사용한다. 스크립트 자체를
   SSM Run Command 전용이라고 가정하지 않는다. `--apply` 없는 dry-run부터 검토한다.
2. 이전 이미지 digest·코드/정책 핀·`compose.env`·`runtime.env`·override와 데이터/장부를
   비공개로 보존한다. `deploy/ec2/pack.sh`와 `deploy/public/Dockerfile`로 정확한
   아키텍처/잠금 의존성 이미지를 준비한다. 자동 ECR 경로는 [배포 문서](DEPLOYMENT.md)를 따른다.
3. drain → wait-idle → 이미지/설정 교체 → API와 worker health/readiness → resume 순서다.
   wait-idle 실패 시 drain을 유지하고 실행·예약·장부를 지우지 않는다.
4. 운영 `compose.ops2.yaml`을 배포와 롤백 모두 적용한다. 기본 `compose.yaml`의 API는 512MiB이므로
   이를 그대로 시작하면 안 된다. 운영 override의 API `mem_limit`와 `memswap_limit`는
   모두 `1536m`이다. worker 6 CPU/12GiB·tmpfs 512MiB도 기존 운영 설정과 함께 확인한다.
   `deploy.sh`/systemd가 override를 자동 보존한다고 가정하지 말고 실제 unit의 compose 인자를 확인한다.
5. HF2 watchdog과 실제 배정 정책이 함께 v29b인지 확인한다. 기존 명시적 1,800초 설정은
   새 코드 기본값보다 우선하므로 설정만 남기고 이미지 교체를 완료했다고 판단하지 않는다.

```yaml
# 승인된 서버의 compose.ops2.yaml에 필요한 API 자원 부분
services:
  api:
    mem_limit: 1536m
    memswap_limit: 1536m
```

```bash
# 승인된 서버에서 실행할 예시. HO1에서는 실행하지 않았다.
cd /srv/proofops
sudo docker compose --env-file compose.env -f compose.yaml -f compose.ops2.yaml exec -T api python scripts/hosted_control.py drain
sudo docker compose --env-file compose.env -f compose.yaml -f compose.ops2.yaml exec -T api python scripts/hosted_control.py wait-idle --timeout 600
# 검증된 이미지/설정 적용 후 API·worker health와 /v1/health/ready 확인
sudo docker compose --env-file compose.env -f compose.yaml -f compose.ops2.yaml exec -T api python scripts/hosted_control.py resume
```

`runtime.env` 주요 키 **이름만**: `APP_ENV`, `MODEL_ADAPTER`, `APP_ORIGIN`,
`HOSTED_SESSION_SECRET`, `HOSTED_ACCESS_CONFIG`, `HOSTED_LIVE_CONFIG`, `HOSTED_DATA_DIR`,
`HOSTED_EVENT_ID`, `HOSTED_CONSENT_VERSION`, `HOSTED_ACCEPT_UPLOADS`, `R108_ACCEPT_NEW_RUNS`,
`ANALYSIS_BACKEND`, `LIVE_DISABLED`, `HOSTED_ANALYSIS_PROFILE`, `HOSTED_ANALYSIS_TIMEOUT_SECONDS`,
`RC1_RESULT_REUSE_ENABLED`, `HOSTED_RUN_USD`, `HOSTED_DAY_USD`, `HOSTED_EVENT_USD`,
`HOSTED_EVENT_USD_CEILING`, `HOSTED_DAILY_RUNS`, `HOSTED_USER_DAILY_RUNS`, `HOSTED_ACTIVE_DAYS`.
공급자 값과 access 설정은 비공개 파일/운영 환경으로만 제공한다.

롤백은 직전 승인 이미지와 대응 정책을 **새 작업에** 배정한다. v29 계열 정책이나 RC1 사본을
구버전 reader로 읽게 하지 않는다. v28 fallback `e6b1a8f`는 RC1 이전이므로 먼저 재사용을
중지하고 RC1 사본은 호환 reader에서 유지해야 한다. 시간 제한·API1536MiB override도 함께
복원한다. 데이터/비용 장부 삭제, 과거 revision 덮어쓰기, 임의 down/prune은 롤백이 아니다.

## 검증 재사용과 공개 checkout의 제약

기존 I29 검증: 전체 pytest 8,560 통과·2 실패·90 생략 후 잘못된 CF1 오류 주입을 수정하고
해당 파일 11개 통과. 전체 재실행은 없었다. RC1 통합 후 lint/format/type과 로컬 이미지
smoke는 통과했다. HF2(`6bd7fc34`)는 집중 44개·replay 48개, lint/format/변경 type,
Linux arm64 이미지와 네트워크 차단 LG13 모의 파이프라인을 통과했다.
이는 실모델 정확도·운영 대용량 완료·현재 release 전체 테스트 통과의 주장이 아니다.

공개 release는 내부 보고서·결정 로그·평가 원시자료·PDF·개인 경로·실제 계정 식별자를 제외한다.
평가 도구 및 회귀 테스트 코드는 보존한다. 일부 테스트가 읽는 private fixture는 별도 공급이
필요하므로 공개 checkout만으로 전체 테스트가 통과하지 않는다. 테스트를 삭제/skip하거나
기대값을 낮추지 않는다. 병합 전 조정자는 비공개 fixture 공급 방식을 정하고 해당 CI를 확인해야 한다.
공개 main의 기존 이력에 이미 포함된 자료는 이 release에서 지워도 과거 이력에 남는다.

HO1에서는 정리 브랜치의 Ruff와 빌드만 실행하며 전체 테스트·AWS·실모델 호출은 `not_run`이다.
검사 명령/결과와 공개 PR 초안은 별도 비공개 인수인계 산출물에 기록한다.

### 비공개 fixture 공급

권한 있는 개발자는 원본 SHA·사용 권한을 확인하고 비공개 자료를 아래 원래 상대 경로로
공급한다. 공개 PR의 비신뢰 코드에 비공개 코퍼스/자격 증명을 자동 제공하지 않는다.
`git add -f`로 제외 자료를 되돌리지 않는다.

| 필요한 자료 | 관련 검사 예시 |
| --- | --- |
| `tests/fixtures/fx6b/*.pdf` | `tests/test_upload_fx6b.py` |
| `tests/fixtures/k7`, `tests/fixtures/k8`의 PDF | K7/K8 원문 검증 회귀 |
| `tests/fixtures/pa9/*.pdf`, `tests/fixtures/pb4/*.pdf` | PA9/PB4 원문 레이아웃 회귀 |
| `tests/fixtures/predeploy/` | `tests/test_predeploy_gate.py` |
| `tests/fixtures/qt1/`, `tests/fixtures/w9/` | QT1/W9 파싱·표 회귀 |
| `tests/integration/hx1_lgchem_failure.json` | `tests/integration/test_hx1_elements.py` |
| `tests/fixtures/pipeline/live-extraction/extraction-year-abbreviation/`의 packet/raw response | 해당 추출 연도·원문 재생 회귀 |

## 다음 개발자가 먼저 할 일

1. 공개 PR은 비공개 fixture 공급 및 이미 공개된 자료의 이력 처리 검토 후 병합한다.
2. 대표 고정 입력의 parse/extract/tag/publish 시간을 측정한다. 원문 검증/receipt 재생과 게시
   비용을 먼저 분리하고, S7은 결과 동일성·보류/오확정 변화·실측 이득을 확인하기 전 통합하지 않는다.
3. 실제 근거가 있는 과소등급 표본으로 검색·패킷 누락을 개선한다. present의 원문/귀속 가드를
   완화하거나 unknown을 조용히 바꿔 성과를 만들지 않는다. 새 정책과 새 revision으로 검증한다.
4. 프런트에서 CF6 확정/보류·SC1 범위·RC1 읽기 전용/분석 일시·중복 주장 그룹을 확인한다.
   모바일·원문 PDF 좌표·내보내기·세션 만료/재접속을 실제 API와 함께 검사한다.
