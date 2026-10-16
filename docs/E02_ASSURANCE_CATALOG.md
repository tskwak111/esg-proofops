# E02 — 보증 묶음 발견과 승인 대기 catalog

기준은 `bdbe050`와 X7 `CONFIRMATION-SPEC` §2/3/7/8이다. 이 변경은
자동확정 채택 조건을 충족한 제품 정책이 아니다. 원문·귀속·새 독립 3회·DEC-25
해석과 receipt/profile 승인이 완료되지 않은 결과는 계속 `unknown/needs_review`다.

`evaluation.report_scope --ranking-policy E02-v1`을 명시하면 기존 W4 주장 쪽을
유지하고 전체 native text에서 검증서 제목·범위·기준을 탐색한다. 첫 쪽의 서명만으로
끝내지 않고 다음 의견서 또는 명시적 다음 절까지 연속 쪽을 포함한다. native text가
없는 쪽, 끝 미확인, 한 쪽에 여러 의견서가 있는 경우를 숨기지 않는다. 겹치는 쪽의
파싱 선택은 불가분 묶음이며 의견서의 기관·범위·수준을 합치는 의미는 아니다.
비용 cap으로 묶음 전체가 선택되지 않으면 `evidence_bundle_incomplete`를 기록한다.
인쇄 쪽은 추측하지 않으며 발견한 쪽은 물리 쪽이다. GRI 행은 입증 권한이 아니다.

`build_catalog`는 원본 SHA가 동일한 신뢰된 graph와 기존 source verifier가 실제
검증한 SourceRef만 verified로 센다. 일부 verified span이 전체 의견서의 완결성을
보장하지 않는다. `match_m3_candidate`는 한 의견서의 원시 field refs를 기존
`extract_assurance`로 다시 검증하고 `match_assurance`를 실행하는 **shadow 진단**이다.
`candidate_state`는 가정된 차원에 대한 scope 진단이며 태깅 수정 입력이 아니다.
`state=unknown`, `public_auto_confirmed=false`는 고정이다. claim 차원 원문 귀속,
같은 packet, 독립 3개 영수증과 승인 권한을 만들지 않는다. `raw_llm_votes`와
`derived_results`를 분리하고 synthetic 표식을 보존한다.

공개 API/DB 변경과 migration은 없다. 새 JSON은 로컬 불변 산출물로만 사용한다.
기존 `strict-v1`, `partial-facts-v1/v2`, `GRI_ASSURED_PAGE_V1`, rulepack과
source-reader 파일은 변경하지 않는다. E02는 fact-assembly profile로 등록하지
않으므로 생성·재개·reload·검토·export에서 새 자동확정 권한을 얻을 수 없다.
롤백은 E02 scope 생산 중단이며 새 산출물과 과거 revision/report는 보존한다.
이 버전을 모르는 scope reader는 새 scope를 거부한다. 부분 쪽 선택은 새 scope가 필요하다.

결정 요청: 결정론 derived 결과를 DEC-25의 3/3으로 인정할 정확한 벡터,
새 `FactAssemblyReceiptV1`/발행 profile, 원문 활동→검증 범위의 의미 귀속 승인.
승인 전에 raw unknown 3개를 derived present 3개로 복제하거나 모델/API를 호출하여
그 권한을 대신하지 않는다. SIM1은 REPORT/DONE 및 보정 승인 전 사용할 수 없다.
