# K9 · v7 요소 귀속 보완

기준은 `874f05f`와 원문 v2 §4.4–4.5, docs/28이다. 사용자 R5 추가 지시의
6요소(POSCO M4·G6·G4·M1, SK M5, NAVER M1)를 대상으로 한다.
M4 구체적 이행과 M2 적용범위를 구분하며 등급·라벨 규칙은 변경하지 않는다.

`FINALS_K9_POLICY`는 명시적 새 pin이다. 기본 `FINALS_I7_POLICY`와 기존
v5/v6/K7/K8/F1 hash는 유지한다. 첫 K9 실측 pin(`FINALS_K9_INITIAL_POLICY`)도
보존하고 K9 v2/v3/v4 측정 pin도 유지한다. 새 사전분류 prompt와 요소 지침 hash,
귀속 정책 hash를 각각 기록한다. 최종 v4는 명시된 설비·혼합 이행 문장에만
분류 지침을, CEO/ESG위원회·직접 감축 계획 등에만 요소 지침을 추가한다.
관련 없는 문장의 provider wire는 v7과 동일하게 렌더한다. 날짜 있는 위원회
운영 지침은 해당 문자·연도 cue가 있는 원문에만 적용한다. 최종 v5는 그 운영
문장의 M5 담당조직을 M4와 독립적으로 태깅하는 짧은 지침을 추가한다.
6개 핵심 회복 문장의 v4 provider wire는 v5에서도 동일하다. v4의 추가 SK
M5 보류는 같은 고정 원문·위치의 별도 3회 실태깅으로 검증하며 과거 checkpoint를
덮어쓰거나 과거 present를 복사하지 않는다.

M4의 로컬 귀속은 검증된 단일 원자 prose 인용 안에 주체와 사건 시점이 같은
문장으로 담긴 경우에만 미정 Scope로 차단하지 않는다. G6 달성수단과 M5 담당
조직은 검증된 단일 원자 안의 해당 요소 태그를 확인한다. 명시된 차원의 원문
위치·상충 검사는 유지하며 모델 unknown을 present로 만들지 않는다.

새 G4 정의 연결 경로는 Scope와 사업장 두 원문 인용이 모두 필요하다.
기존의 다른 G4 경로·표 귀속을 새 보충 검사로 재해석하지 않는다. 같은 canonical 문단에서
`이름(Scope N)`이라는 명시적 정의와 해당 이름으로 시작하는 계획을 연결한다.
문단·불릿 경계, 다른 활동·페이지·기업, 모호한 중복 정의는 거부한다. Scope
정의는 기존 v13 native/glyph/visibility/OCR 검증기를 통과한 정확한 span만
추가한다. 문단 전체를 verified로 승격하지 않는다. 사전분류의 nullable facility를
요소 태깅에서 인용된 로컬 사업장 근거의 부재로 해석하지 않는다. 새 보충 근거의
receipt·원본 hash·페이지·좌표·offset은 tag checkpoint에 남기며 reader가 재검증한다.
이 보충 Scope 인용은 다른 요소·수치·목표연도로 전용하지 않는다.

명명된 설비 적용과 수치 성과를 사전분류에서 구분하고 M1/M5를 독립적으로
태깅한다. SBTi 방법 채택을 G8 검증으로, 일반 개선을 M4 구체적 실적으로
바꾸지 않는다. 세 replica와 원문 가드 뒤 Python 규칙엔진만 등급을 계산한다.

공개 API/DB schema·migration·dependency 변경은 없다. 롤백은 K9 새 pin 배정
중단으로 한다. K9 산출물을 읽을 때는 해당 정책을 지원하는 reader를 유지하고,
미지원 구버전은 새 hash를 거부해야 한다. 과거 revision/report는 덮어쓰지 않는다.
