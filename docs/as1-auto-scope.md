# AS1 자동 범위 제안 계약

2026-10-09 AS1 및 coordinator 추가 결정에 따른 로컬 opt-in이다.
`evaluation/report_scope.py`의 AS1-v1은 `report_sections.py` v11 및 기존 해시
`d757a32350d49e0bf3edd88184a0d66431aa3cdd6b887c2e709c1c92e94f405e`를 변경하지 않는다.
기존 수동 선택과 `--auto-scope` 기본 동작은 유지한다. API/DB migration은 없다.

## 범위와 실패

- 앞쪽 20쪽의 CEO 제목/물리 목적지 및 본문을 확인한다. 목차·반복 메뉴는 제외한다.
  CEO 최대 2쪽 + 환경 밀도 순위 본문 기본 K=8쪽, **주장 전체 최대 10쪽**이다.
- M=30은 **주장 쪽을 포함한 근거 검색 쪽의 합집합 상한**이다.
  검증의견서·GRI·환경 데이터·부록을 우선 선택하고 주장 추출에는 넣지 않는다.
  명시된 데이터/부록/Policy Book의 환경 하위 제목도 근거 전용이다.
- 원본 물리 쪽 번호, 원본 SHA-256, 정책/원래 section map/계획/선택 해시,
  분류·이유·native 텍스트 스니펫·텍스트 해시와 모든 제외 쪽을 JSON에 보존한다.
- 기존 unknown/conflict 목록은 보존한다. Introduction/CEO 목차 계층 충돌만 실제
  큰 CEO 제목과 일치하는 경우 범위 분류로 해석하고 별도 resolved 목록에 기록한다.
  원문 사실의 conflict를 해소하거나 SourceRef·입증·라벨을 승인하지 않는다.
- 기존 section reader 실패는 오류 유형과 전체 unknown을 남기고 원본 native
  주 제목/밀도로 별도 제안한다. 회사 개요 안의 작은 환경 소제목만으로 환경 본문이
  되지 않는다. 입력 한도·암호화·원본 변경 실패는 우회하지 않는다.
- 읽을 수 있는 환경 본문이 없으면 status=failed,
  NO_READABLE_ENVIRONMENTAL_NARRATIVE와 앞쪽 1~3쪽 제안만 남긴다.
  CEO만으로 성공하거나 전체 PDF로 확대하지 않으며 유료 호출을 하지 않는다.
- 항상 declared_subset이다. 처리하지 않은 쪽과 unknown/conflict/unreadable을
  근거 부재로 만들거나 보고서 전체 분석 완료라고 표시하지 않는다.

## 무료 실행과 편집

```sh
uv run python -m evaluation.report_scope --pdf REPORT.pdf --output NEW_PLAN.json
uv run python scripts/analyze_report.py --pdf REPORT.pdf --auto-scope \
  --auto-scope-policy bounded-v1 --report-year 2025 \
  --period-start 2024-01-01 --period-end 2024-12-31 --state NEW_STATE
```

두 번째 명령은 dry plan이며 모델을 호출하지 않는다. K/M은 각각
`--auto-scope-environment-pages`, `--auto-scope-evidence-pages`로 명시한다.
K는 1..10, M은 10..500이며 주장 hard cap 10은 변경할 수 없다.
운영 채택 제안은 K=8/M=30이다. 숫자 0 등의 잘못된 입력은 기본값으로 바꾸지 않는다.

`NEW_PLAN.json`의 `selected_claim_pages`와 `selected_evidence_pages`만 편집하고
`--scope-plan NEW_PLAN.json`을 사용한다. 원본·정책·불변 제안 해시를 확인하고,
정렬·유일성·실제 쪽 범위·주장⊆근거·상한·근거 전용의 주장 전환 금지를 재검증한다.
선택 변경은 새 selection 해시/별도 artifact로 고정하고 기존 계획을 덮어쓰지 않는다.
불명확/판독 불가 쪽은 자동 계획의 읽을 수 있는 쪽으로 위장하지 않는다.
범위 JSON은 standalone CLI의 출력이다. launcher가 저장하는 wrapper의 `proposal`을
추출할 수도 있다. 새 정책 rollback은 opt-in 중단이며 기존 산출물은 보존한다.

## 혼합 파싱의 현재 상태와 USD 0.50

무료 native 후보/ODL은 가능하지만 **현재 런타임의 페이지별 혼합 파싱은 미구현**이다.
`ParserProfile`(`application/ingest/graph_fusion.py`)은 실행당 parser_mode 하나이다.
`adapters/parsing/opendataloader.py`는 ODL 선택 쪽을 먼저 읽지만 Upstage 모드에서는
전체 selected를 유료로 호출하고 local 후보를 전부 비운다. 동일 파일의
`load_verified` 및 manifest parser/config 검증도 단일 모드를 가정한다.
`adapters/parsing/upstage_document.py`, `apps/worker/.../local_runner.py`,
`evaluation/local_upstage_pilot.py`의 profile 설정·재생 경로를 함께 바꿔야 혼합이 가능하다.
원본 tenant/version/물리 쪽 매핑·표 검증·source admission은 그대로 유지해야 한다.

AS1은 혼합 파싱을 활성화하거나 public worktree/배포를 수정하지 않는다.
Upstage 근거 전용 쪽 제외의 비용 절감 추정은 가능하지만 native/ODL 표 출력은
검증된 입증 근거가 아니다. 스캔·문자층 불량은 무료 텍스트 파싱으로 해결되지 않는다.
10쪽 × 기존 SK 2쪽 USD0.10 선형 추정은 USD0.50이지만 보수적 범위는 초과할 수 있다.
쪽 상한은 금액 가드가 아니며 public의 실행별 예약/정산 cap을 계속 적용해야 한다.

## W4-v2 선택 순위 (2026-10-11)

공개 child의 새 제안과 standalone `evaluation.report_scope`는 W4-v2를 사용한다.
환경 본문 후보의 목표연도·환경 수치/단위(값 앞/뒤 단위)·수치 표 행·구체적 실행·
명명된 수단·섹션/소제목을 NFKC 정규화된 native 본문에서 점수화한다. 수치와 실행
신호는 주변 120자의 환경 문맥이 있을 때만 세고, 반복 횟수별 상한을 둔다.
동점이면 기존 환경 밀도·환경 그룹·키워드 수·물리쪽 순서를 적용한다.
회사명·정답쪽 번호는 점수 입력이 아니며, 이 점수는 추출/입증/등급 판정이 아니다.

기본 환경 본문 8·CEO 최대 2·주장 최대 10·주장 포함 근거 합집합 최대 30쪽은 유지한다.
부록/보증/GRI는 근거 전용, unknown/conflict/unreadable와 모든 기존 가드는 유지한다.
새 plan은 `version=W4-v2`, 별도 `policy_sha256`, 페이지별 점수/신호를 보존한다.
API/DB 구조 변경이나 migration은 없다. 기존 AS1-v1 제안·선택 해시와 revision은
재작성하지 않으며 두 버전의 불변 제안 검증을 지원한다.

로컬 launcher는 `--auto-scope-policy bounded-v2`로 선택한다. 기존 명시적 bounded-v1과
finals 프로필의 기본 선택은 AS1-v1로 보존한다. 과거 계획은 `--scope-plan`으로 재생한다.
롤백/비교: `inspect_streaming(..., ranking_policy="AS1-v1")` 또는 standalone
`--ranking-policy AS1-v1`; 새 제안을 이전 코드에서 읽는 것은 지원하지 않는다.
클라우드 배포·모델 호출은 W4에서 수행하지 않는다.
