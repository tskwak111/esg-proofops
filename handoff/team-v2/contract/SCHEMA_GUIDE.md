# JSON을 처음 쓰는 개발자를 위한 스키마 설명

JSON object는 {키:값}, array는 [값1,값2], null은 미확인/없음이다. 문자열 "null"과 다르다.
숫자 금액은 오차 방지를 위해 "1000000000"처럼 Decimal 문자열로 전달한다.
JSON에는 주석·후행 쉼표를 넣지 않는다. 필드 이름을 한글로 번역하거나 임의 추가하면 검증 실패한다.

## input 주요 필드
| 필드 | 뜻 | 채우는 주체 / 주의 |
|---|---|---|
| schema_version | 계약 버전 "1.1" | A/B 동일 버전 |
| synthetic | 합성 입력 여부 | 실제 자료를 true로 바꿔 보호 검사 우회 금지 |
| identity.tenant_id | 접근권한 소유 조직 | A session에서 가져옴 |
| identity.company_id / dart_corp_code | 내부 기업 ID / DART8자리 | 회사명 유사도로 추정 금지 |
| identity.claim_id / package_id | 주장 / 공시 묶음 ID | 기존 ID를 보존 |
| identity.period_start/end | SR 보고대상기간 | 발간일 아님, 모르면 null |
| identity.financial_period_start/end | 재무 대상기간 | C2는 차이를 검사 가능 |
| identity.financial_fiscal_year | 조회 재무 회계연도 | claim.fiscal_year와 연결 검증 |
| identity.sustainability_document_version / financial_document_version | 두 원문 버전 | 수정되면 새 버전 |
| identity.consolidation | consolidated/separate/unknown | 다른 기준을 섞지 않음 |
| identity.rcept_no | DART 접수번호 | 통합문서 등 없는 경우 null+사유 |
| identity.sr_published_at / financial_published_at / as_of_date | 공개 시점/비교 시점 | 나중 공시를 과거에 존재한 것처럼 사용 금지 |
| claim.track | goal/performance/management/unknown | 주제와 별개 |
| claim.quote / source_id | 주장 인용과 출처 | actual source quote와 대응 |
| claim.trigger_elements | C발동 요소 이름 | 모델의 무근거 present 금지 |
| sources[] | 원본별 출처 배열 | locator/quote/hash, ID 중복 금지 |
| sustainability / financial | 비교 양쪽 fact | raw=원문, normalized=정규화, kind=종류, unit=단위 |
| comparability | comparable/not_comparable/unknown 후보 | B에서 검증, client 확정 아님 |
| explanation | 설명 source_id 또는 null | search_complete는 search.state와 일치 |
| search | coverage정책/문서/읽은 source/실패/receipt | complete를 임의 true로 설정하지 않음 |
| c3_context | C3 통화·기간·계정·약정/조달 source | C3에서 object 필수, 다른 item은 null 가능 |
| c4_context | 분류명·정의/산정기준 source ID들 | C4에서 object 필수 |

fact.kind의 normalized 형식:
- entity_set/facility_set: 정렬된 고유 ID JSON array를 문자열로 직렬화. 법인명 alias 매핑은 원문·승인 기록 필요.
- currency_amount: 단위 승수를 적용한 Decimal 문자열. unit=KRW 등. 원본 단위는 raw에 보존.
- period: YYYY-MM-DD/YYYY-MM-DD. 실제 날짜 유효성·순서는 코드 검증.
- classification: 해당 주장에 연결된 분류 ID/이름. 정의가 옳은 회계분류인지를 평가하지 않음.
- unknown: 값 null. 누락을 "0"/"[]"로 치환하지 않음.

## sources[]
source_id는 packet에서 고유. document_id는 어느 원문 버전인지 나타냄.
artifact_sha256은 원본 bytes 해시. PDF locator에는 physical_page·block/char 또는 표/셀 위치,
XBRL locator에는 fact/context/주석 element, HTML에는 안정된 section/element 위치를 적는다.
예제 locator의 fixture는 실제 DART/PDF locator가 아니다.

## policy
version/source_policy_sha256은 승인 정책 snapshot을 가리킨다.
approved/approved_by/approved_on은 승인 기록을 찾기 위한 정보이고 입력 사용자가 true를 쓴다고 승인되지 않는다.
synthetic_only=true인 예제 정책은 live 금지. current_stage=1이며 C5는 허용하지 않는다.
enabled_items는 승인된 C군 목록. allowed_difference_types는 설명 분류이며 자동 면제 조건 아님.
c3_threshold는 승인 전 null. allowed_capex_account_ids와 c3_account_mapping_approved를 모두 확인.
coverage_policy_id는 어느 영역을 읽어야 부재를 인정할지 정하는 정책.
C2 timing rule은 기간 동일 또는 검증된 차이 설명, C4는 definition+calculation_basis를 요구한다.

## output
| 필드 | 의미 |
|---|---|
| execution_state/status | 계산 수행 상태와 연계 결과 분리 |
| review_required | 원문/규칙 검토 필요 |
| reason_codes | 동일한 오류를 집계할 기계 코드 |
| source_ids/explanation_source_id | 사용한 실제 원문 참조 |
| sustainability_value/financial_value | 화면에 보일 양쪽 원문 표현, 모르면 null |
| packet_sha256/policy_sha256 | 고정된 입력·정책 해시 |
| engine_version | 계산 코드 버전 |
| synthetic | 합성/실제 구분 |

reason 예: same_verified_entity_set, not_comparable, search_incomplete, source_unverified,
policy_unapproved, c3_policy_unapproved, same_period, explanation_not_found, classification_basis_present.
reason은 새 공개 판정 라벨이 아니다. UI는 안전한 한국어 표현으로 mapping한다.

## 재현
```bash
uv run python handoff/team-v2/contract/validate.py
```
PASS는 문서의 예제·스키마와 negative guards가 맞는다는 뜻이다. B 엔진을 만들고 같은 expected와 비교하는 pytest가 별도로 필요하다.

## 기존 태그 → 신규 trigger 변환 (A 소유)
C군 trigger 이름은 기존 primitive와 반드시 같지는 않습니다.
- organizational_boundary: 기존 org_boundary/calculation_boundary의 검증된 조직경계 내용을 확인해 생성.
- implementation_scope: 관리 boundary의 실제 구현 범위. 일반 지역 언급만으로 생성 금지.
- quantitative_value: 기존 quantitative_or_qualified_ordinal 중 실제 숫자 값이 있는 경우만. 범주형 인증등급은 제외.
- currency_amount: goal 트랙의 통화·금액·투자/지출 의미가 원문에서 확인된 경우.
- revenue_share: 매출/비중과 해당 분류가 실제로 명시된 경우.
이 mapping은 태그 이름 문자열 바꾸기만으로 승인하는 절차가 아니다. 원문 fact와 trigger 판정 receipt를 보존한다.
