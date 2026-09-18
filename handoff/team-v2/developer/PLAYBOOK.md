# 개발자 B · 상세 구현 방법

## B1. 수집 가용성과 원본 저장
목적: 모델에 재무 수치를 묻는 대신 기업이 공시한 원본을 확보한다.
입력: 회사명만으로 조회하지 말고 corp_code(8자리), FY, 정기보고서 종류, 연결/별도, 접수번호.
초기 3~5개 기업에서 다음 표를 evidence/reconciliation/availability.csv로 작성한다:
company/fy/rcept_no/item/access_method/retrieved/source_hash/locator/issue.
item은 subsidiary_list, capex_accounts, commitment_note, segment_note, period.
access_method는 api/xbrl/document. 미제공과 조회 실패를 구분한다.

절차:
1. 공식 DART 개발가이드에서 공시검색·전체 재무제표·XBRL 원본·공시 원문 경로를 확인한다.
2. report receipt를 먼저 고정하고 필요한 항목만 조회한다. “가장 최신”으로 과거 결과를 덮어쓰지 않는다.
3. raw bytes를 hash와 함께 저장한다. response error code·조회시각을 별도 manifest에 기록한다.
4. 필요한 계정/주석만 정규화한다. 주석이 API에 없으면 XBRL/문서 원문 parser로 fallback한다.
5. 정규화 결과마다 원문 locator를 연결한다. XBRL에 PDF bbox를 만들어 넣지 않는다.
6. timeouts/429/5xx/빈 응답/XML 오류/ZIP 과대 압축은 명시적 수집 오류로 처리한다.

코드 위치: adapters/dart/client.py(HTTP), artifacts.py(파일), normalization.py(변환).
도메인 코드는 이 adapter를 import하지 않는다. 가능한 기존 httpx/stdlib를 사용한다.
최소 테스트: 키 없는 live 거부, 다른 기업 응답 거부, retry 상한, 정정 receipt 보존, 잘못된 ZIP 경로/크기 거부.
키 자체를 포함한 URL을 로그에 남기지 않는다. 예외에도 query 값을 제거한다.

## B2. 공시 패키지와 비교 전제
한 package에는 같은 tenant/company/FY의 문서 버전 목록과 공개시점 기준이 들어간다.
전제: company/corp 일치, 재무 연결기준 확인, 원본 존재, 지정된 FY/문서 버전으로 조회.
보고대상기간을 발간 연도에서 추측하지 않는다. 실제 날짜는 claim/문서 각각 보존한다.
C2는 기간 차이를 조사하므로 날짜가 다르다는 이유만으로 모든 C2를 입구에서 버리지 않는다.
“다른 기업/FY의 잘못된 문서”와 “같은 FY에서 공시된 측정기간 차이”를 구분한다.
기간 대응 자체를 모르면 blocked. 통합보고서도 동일 검증을 한다.
SR 이후 발간된 재무제표 사용 여부는 승인된 as-of 정책을 적용한다. 나중 정정본을 당시 이용가능 자료처럼 보이지 않는다.

## B3. 원문 참조와 설명 검색
입력 packet은 untrusted다. application에서 source_reader로 실제 bytes를 읽어 hash와 locator/quote를 확인한다.
PDF: 해당 page/block/quote와 위치. XBRL/HTML: element/주석 locator와 text.
원본이 없거나 인용 불일치면 source_unverified/blocked이며 단순 문자열 유사도로 승인하지 않는다.
LLM은 지정된 source subset에서 설명 후보 source_id+quote만 돌려준다.
출력 schema에 grade/status를 허용하지 않는다. 찾지 못하면 빈 배열이다.
코드가 원문 실재와 해당 회사·기간·차이의 귀속을 확인한 후 설명으로 채택한다.
`search.state=complete`는 모델의 자신감이 아니다. 승인된 coverage 정책에서 필수 영역을 모두 읽고 검토한 기록이어야 한다.

## B4. C1 조직경계
trigger: organizational_boundary 또는 implementation_scope를 실제 주장하는 claim.
값 형태: entity_set/facility_set 또는 경계 방식 설명. entity와 facility 개수는 비교하지 않는다.
positive: 같은 검증된 entity set → matched. 서로 다른 집합 + 해당 차이 설명 확인 → matched.
negative: 같은 개수지만 다른 집합 → 숫자 개수만으로 matched 금지.
부재: 비교 가능한 차이 + 필요한 영역 search complete + 설명 없음 → needs_explanation.
미확인: 대응 관계 불명/원문 미판독/설명 귀속 불명 → blocked 또는 승인된 not_comparable→not_applicable.
허용 차이 목록은 설명을 찾는 분류 기준이지 자동 통과 목록이 아니다.
같은 entity set과 승인된 집계기준을 확인할 수 없는 “전 사업장”은 빈 집합으로 정규화하지 않는다.

## B5. C3 투자 약속
trigger: goal 트랙 + 통화 금액의 투자/지출 약속. 단순 배출량 목표에는 실행하지 않는다.
금액: Decimal 문자열. KRW 억/조 배수는 숫자로 정규화하되 원문 value/unit도 보존한다.
기간: 다년 총액과 연간 CAPEX 비교는 승인 정책의 의미를 그대로 기록한다. 임의 연평균화 금지.
현금흐름 투자활동 총액을 CAPEX로 쓰지 않는다. approved account mapping과 원문 출처가 있어야 한다.
해당 계획이 약정 주석에 정확히 존재하면 matched 경로를 검토한다. 다른 사업 약정은 인정하지 않는다.
약정이 없더라도 즉시 needs_explanation 아님. 양의 유효 CAPEX, 승인된 threshold,
해당 금액 조건, 조달·집행 설명 부재의 coverage까지 충족한 경우에만 정책을 적용한다.
CAPEX=0/음수/결측, 통화 혼합, 미승인 threshold/계정은 blocked. ratio를 infinity/0으로 바꾸지 않는다.
문서의 5배는 예시이며 승인된 기본값이 아니다. synthetic example threshold를 live 정책으로 쓰지 않는다.

## B6. C2 기간
trigger: 정량 성과 주장. sr의 기준일/기간과 해당 FY 재무 결산 기간을 비교한다.
같은 기간 → matched. 기간이 다르지만 그 차이를 설명하는 수집 시차 문구 검증 → matched.
기간 차이 + complete search + 설명 없음 → needs_explanation. 연도/측정기간 불명 → blocked.
명시된 보고기간 밖 활동은 not_applicable/period_out_of_scope.
연간 누적값과 특정일 잔액 비교처럼 measure type이 다르면 억지로 같다고 보지 않는다.
테스트: 비12월 결산, 다년도 표 연도 명시/미명시, 수집 시차 문구, SR 발간 후 재무공시.

## B7. C4 분류 기준
trigger: 친환경 제품 등 매출/비중 주장.
찾는 것은 그 분류의 정의 및 산정 기준이며 “32%=재무표 32%”라는 숫자 일치가 아니다.
해당 분류와 기간에 귀속되는 정의+산정기준 인용이 모두 확인되면 matched.
필요 영역을 다 읽었는데 둘 중 어떤 설명이 없는지는 reason으로 표시하고 승인 정책에 따라 needs_explanation.
주석을 못 읽었으면 blocked. 다른 제품군의 정의·일반적 ESG 방침은 근거 아님.
정의의 품질·회계 분류 타당성은 평가하지 않는다. 확인하는 것은 공시된 설명의 존재다.

## B8. 출력·가드·CLI
도메인 public 함수: evaluate(packet:dict,policy:dict)->dict. engine_version과 결정 hash를 고정한다.
CLI는 --packet, --policy, --output을 받고 결과 JSON을 쓴다. 모든 의미 판정은 exit 0,
잘못된 입력·권한 오류는 exit 2, 수집/내부 오류는 exit 3으로 구분한다(신규 CLI 계약).
blocked/not_applicable는 프로그램 crash가 아니다. CLI 결과에도 synthetic을 보존한다.
C5 직접 호출은 NotImplementedError. UI dispatch는 이를 잡아 not_run/stage_disabled로 별도 기록한다.
금지 문구 필터는 generated explanation에만 적용하고 원문 quote는 변조하지 않는다.

## 반드시 할 테스트 묶음
- 형식: schema_version, null, Decimal, 날짜, source ID 중복, 잘못된 refs.
- identity: tenant/company/FY/문서/정정/연결기준.
- source: 실제 hash/quote/locator, 다른 문구·페이지, 없는 원본.
- C1~C4: positive/negative/boundary/unknown/미정 정책 각 분기.
- safety: C5, 금지 결론, 실제 원문 인용 보존.
- replay: 같은 packet+policy→같은 결과, 기존 grade/label 필드 없음.
- network: DART 실패 재시도, 무제한 호출 금지, 키 비노출.
- evaluation: 정답과 예측 split, 오탐 분모, 보류율 별도.

## 제출해야 할 것
브랜치/commit, 코드·tests, schema version, CLI 실행 예, availability.csv,
판정별 원문 source refs와 hash, 미해결 규칙 목록, 실행한 검사 로그, live/not_run·비용.
A에게 DB dump를 보내는 것이 아니라 input/result JSON과 원본 접근 manifest를 넘긴다.
