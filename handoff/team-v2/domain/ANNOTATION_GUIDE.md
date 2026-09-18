# 원문에 연결된 정답 데이터 작성법

## 공통 필드
document_id는 corpus의 같은 문서를 가리킵니다. claim_id는 claims와 나머지 양식의 연결키입니다.
physical_page는 PDF 파일상 1부터 센 페이지입니다. 인쇄된 쪽수와 다르면 notes에 따로 씁니다.
quote는 원문 그대로, statement는 원자 주장 요약입니다. 표 내용을 본문에 있던 문장으로 꾸미지 않습니다.
bbox_json은 표시 페이지 좌상단 원점 PDF point [x0,y0,x1,y1]. 모르겠으면 빈칸, [0,0,0,0] 금지.
char_start/end는 확보한 해당 블록 원문에서 Unicode code point, end는 제외입니다. 위치 추정 금지.
table_id/row/column은 파서가 제공한 ID·인덱스를 사용하고, 미확보면 원문 페이지/quote/설명을 남깁니다.
DART financial_locator는 접수번호와 주석 제목·XML/XBRL locator 등 재현 가능한 위치를 기록합니다.
숫자는 소수 문자열, 실제 누락은 빈칸. '-'를 0으로 바꾸지 않습니다.
날짜는 YYYY-MM-DD, sha256은 원본 파일 64자리 해시, 상태는 아래 영문 값을 사용합니다.
CSV에 고객 비밀·API 키를 넣지 않습니다. 평가용 자료는 승인된 접근 경로로 공유합니다.

## 상태 사전
- track: goal / performance / management / unknown. 하나의 문장에 여러 주장이 있으면 claim 행을 나눕니다.
- element state: present(원문 및 주장 귀속 확인), absent(필요 범위 검색 후 부재 확인), unknown(확인 불가), conflict(근거 충돌), not_applicable(승인된 적용 제외).
- annotation_status: draft / reviewed / adjudicated / unresolved. adjudicated는 불일치 검토를 마친 경우만.
- assurance expected_status: covered / not_covered / undetermined.
- reconciliation expected_status: matched / needs_explanation / not_applicable. 미실행·실패·보류는 빈칸과 expected_execution_state=not_run/blocked.
- corpus split: train / dev / test / challenge. rights_status: pending / approved / restricted.
- rules decision_status: unresolved / proposed / approved / rejected. approved는 이름·날짜·근거·사례가 모두 필요.
- numeric expected_check: consistent / inconsistent / not_comparable / not_computable / unresolved. 이는 주석용 분류이며 엔진 DTO와 직접 같다고 가정하지 않습니다.

## 태깅 순서
1. 원문을 먼저 읽고 E 소주제·주장·근거 영역을 식별합니다.
2. 주장 원문과 페이지를 claims에 기록합니다.
3. element_id는 config/rubric 및 docs/28의 기존 요소명을 사용합니다. 새 이름은 rules에 제안합니다.
4. 요소마다 원문·연도·범위·단위를 확인합니다. 같은 보고서의 비슷한 숫자는 정답이 아닙니다.
5. 각주가 어떤 값/행/열에 적용되는지 binding_reason에 설명합니다.
6. absent는 searched_scope를 작성해야 합니다. 못 읽거나 찾는 도중이면 unknown입니다.
7. 기준이 모호하면 사례를 rules에 연결하고 unresolved로 제출합니다.
8. 검토자의 수정은 원본 행을 덮어쓰지 말고 새 annotation_id와 변경 메모로 남깁니다.

## 수치와 보증
수치 정답은 metric/value/unit/year/boundary/denominator/footnote 전체 조합입니다.
전년 대비 감축률은 기준값과 현재값의 source를 각각 기록합니다. 기준값 0이면 계산 불가입니다.
보증서가 있다는 이유로 covered가 아닙니다. 해당 지표·기간·기업/사업장 경계와 명시 제외를 확인합니다.
표 밖 각주 번호가 연결됐다고 그 조건의 의미까지 승인된 것은 아닙니다.

## 연계 검증
C1에서 사업장 5개와 종속기업 12개는 단위 종류부터 다릅니다. 단순 개수 차이로 설명 보완을 요구하지 않습니다.
설명이 원문에 있어도 다른 기업·기간·차이를 설명하면 정답 근거가 아닙니다.
C3의 미래 약속이 약정 주석에 없다고 문제로 판정하지 않습니다. CAPEX의 계정 정의·기간·임계값 승인이 필요합니다.
회계처리 적정성·손상·충당부채 금액 판단은 하지 않습니다. C5 실행 금지 사례는 별도 challenge입니다.

## 작은 예시 (가상의 문장, gold 아님)
“2024년 국내 사업장의 용수 사용량은 100㎥이다.”
claim: performance. quantitative_value=100, unit=㎥, year=2024, boundary=국내 사업장.
해외 사업장 표의 100㎥는 같은 숫자여도 이 주장의 근거가 아닙니다.
“검증기관 A가 보고서를 검증했다”만으로 위 용수 지표의 assurance를 present로 태깅하지 않습니다.
실제 제출에는 이러한 예시를 복사하지 말고 원본 문서의 문구·위치를 기록합니다.

## 제출 점검
모든 문서/주장 ID가 연결되는가? present에 정확한 quote·page/locator·귀속 이유가 있는가?
absent에 검색 범위가 있는가? 미정 기준을 최종 라벨로 덮지 않았는가?
평가 기업이 개발 데이터에 섞이지 않았는가? 공식 조항은 출처·확인일·권리 상태가 있는가?

## 제출 파일 검사 (A가 실행해도 됨)
```bash
uv run python handoff/team-v2/domain/validate_data.py --self-test
uv run python handoff/team-v2/domain/validate_data.py --folder submissions/my-review
```
8개 CSV가 모두 있어야 합니다. 작성하지 않은 종류는 헤더만 있는 파일로 포함합니다.
형식/ID/일부 상태 검사만 하며 원문 정답의 의미적 정확성은 사람이 확인해야 합니다.
최종 제출 검사에는 --final을 추가합니다. 예제는 rights=pending이므로 --final을 통과시키면 안 됩니다.
