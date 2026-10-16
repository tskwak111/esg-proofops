# V1 · R19 활동 범위 연결 / DEC-93 AP-06

기준 코드 `6c6241f`(v24). R19-T01/T07 및 DEC-93 AP-06을 구현하는
`V1_ACTIVITY_POLICY`의 정확한 hash로만 선택한다. 기존 v24 기본값·QT2·SC1
정책·원응답·태깅 revision은 변경하지 않는다. 실제 모델 호출과 배포는 이 작업에 없다.

SC1의 같은 tenant/run/document version/parse manifest/source/graph/선택 쪽
inventory를 `InventoryIndex`에서 한 번 원응답 재생한다. 새 linker는 그 객체를
재사용한다. 같은 candidate의 독립 request/signature/provider ID를 가진 3회
present 및 동일한 속성 인용이 필요하며, 링크 자체가 새로운 합의 표를 만들지 않는다.

M2는 같은 활동의 실제 조직·사업장 경계만 global_bound로 연결한다. 주어와
명명된 활동을 검증한 SourceRef로 묶고, 주장에 명시된 대상/기간은 정확히
일치해야 한다. 주장에 대상이 없을 때 M2 근거의 실제 경계를 인용하되 주장
속성을 채우지 않는다. 양쪽 모두 기간을 명시하지 않은 M2는 기간 credit 없이
허용한다. 한쪽에 연도가 있거나 서로 다른 기간이면 보류한다.

원문 속성은 근거 인용 안에 있거나 동일 graph의 직접 section_parent /
table_parent / same_statement 관계로 결속해야 한다. 기존 동일 문단 인접문장
주어 연속성도 유지한다. 같은 쪽·회사명·연도만으로 연결하지 않는다. 관계가
없는 도식에는 새 graph edge를 만들어 넣지 않으며 retag/reparse가 필요하다.
선택 밖 근거는 not_run이고 전체 PDF 검색을 했다고 표시하지 않는다.

AP-06의 M1/M4는 명시 주어·활동·실제 대상·동일 운영기간이 모두 필요하다.
null 또는 생략된 기간/대상은 보류한다. Scope/연결경계가 실제로 언급되지 않은
비GHG 관리 주장의 선택적 null은 null로 보존한다. 다른 명시 축과 미해결
제품/소재 축은 생략해 통과시키지 않는다. 미래 예정 M4를 실적으로 승격하지 않는다.

M1/M4의 global_bound는 별도 파생 rulepack에만 추가한다. 원본 pack은 보존하고
새 ID·version·content hash·정책 hash와 파생 내용 전체를 scope receipt에 기록한다.
등급 사다리·G/P 수치 scope·M3/DEC43·GAP-001·세이프하버 매핑은 변경하지 않는다.
파생 pack은 기존 pack의 사용 권한을 전제로 한 opt-in 실행용 계약이며 기본
rulepack registry를 활성화하거나 기존 승인자를 새로운 검토자로 표시하지 않는다.

SC1은 기존 raw claim 3회/원문/충돌/세이프하버/추정치/제품/전체 선택 범위 가드를
검사한 뒤 unknown인 M1/M2/M4에만 검증된 링크 사실을 추가한다. 부재는 기존
SC1 검색 증명이 있을 때만 absent_in_scope다. 부분 inventory/실패 replica는
확정을 막는다. 완전 양성 사다리 또는 기존 부재 증명이 닫은 사다리만 Python
엔진으로 ‘분석 범위 기준 확정’을 만든다. M2 회수만으로 M3/E3을 만들지 않는다.
추가 후보의 주어/활동이 null이면 다른 활동이라고 제외할 수 없으며,
unknown/conflict/unreadable을 보존한다. 연결 요소의 미검토 cue도 확정을 막는다.

추가 필드는 sc1_scope_receipt 내부의 v1_activity_links, v1_base_rulepack_sha256,
v1_effective_rulepack, v1_projection이다. 기존 sc1_elements/sc1_confirmation
표시·export 경로를 재사용한다. worker와 tag_store가 같은 정책으로 재계산하여
checkpoint를 검증한다. DB migration은 없다. rollback은 신규 opt-in 배정을
중단하는 방식이며, 이미 생성한 revision을 유지하고 새 reader를 보존한다.

D11 fixture는 반납본 D11-E1=M1, D11-E2=M4를 그대로 복사하고 별도 D11-M2만
추가했다. 전 사업장 단계 원문과 프로세스 연결이 있을 때만 M2이며 4단계 제목만
있으면 보류한다. LG 국내 전 생산사업장/글로벌15·17, 카카오 주요 직접운영
사업장≥95% 등의 한정은 evidence 전체에 보존하고 모든 사업장으로 확대하지 않는다.

검증은 합성 계약 시험과 저장 결과 감사를 구분한다. R17/E14에는 동일 실행의
SC1 inventory가 없어 새 확정은 retag_required다. 저장 원응답을 재포장하여 새
3표로 세지 않는다. DL4 분모는 NAVER71+Kia60=131이며 보류28은 별도다.
홀드아웃160 원자의 추출 평가를 요소/등급 정확도로 바꾸지 않는다.
