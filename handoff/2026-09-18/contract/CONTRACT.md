# 연계 모듈 협업 계약 1.0

이 계약은 개발자 간 교환 형식이다. 기존 public API/DB/SourceRef를 변경하지 않는다.
A가 검증된 태그를 변환하고 B가 아래 형식을 소비한다. B는 fixture만으로 독립 개발할 수 있다.

## 진입점 (B가 구현)
```python
# packages/proofops/domain/reconciliation/engine.py
# 순수 함수: 시간·파일·환경변수·네트워크·LLM import 금지
def evaluate(packet: dict, policy: dict) -> dict: ...
# packages/proofops/application/reconciliation/service.py
# schema + 출처/범위 검증 후 evaluate 호출. 공개 요청의 verified 플래그 신뢰 금지.
def reconcile(packet: dict, policy: dict, *, source_reader, explanation_search) -> dict: ...
```
source_reader(ref: dict) -> bytes 는 원본 immutable bytes를 반환한다.
explanation_search(packet: dict) -> list[dict] 는 packet.sources 형식의 후보 refs만 반환한다.
모델 후보는 정본 sources와 실제 인용 대조 후에만 채택한다. 외부에서 제출한 packet을 순수 evaluate로 직접 연결하지 않는다.
CLI: `uv run python -m evaluation.reconciliation_cli --packet INPUT --policy POLICY --output OUTPUT`
기본은 offline. `--live-dart`는 명시적 모드이고 DART_API_KEY 없으면 실패한다. 자동 모델 호출 없음.

## 입력/출력
`input.schema.json`과 `output.schema.json`이 데이터 형식 정본이다. example은 합성 자료다.
- identity: tenant/company/claim/package ID, 기간, 문서 버전. ID는 빈 문자열 금지.
- sources: source_id, document_id, artifact_sha256, locator, quote. PDF는 실제 1-based page/좌표, DART는 접수번호 및 원문/XML fact locator를 locator에 보존한다. 없는 PDF 좌표를 만들어 붙이지 않는다.
- item: C1 또는 C3. C2/C4는 후속. C5가 진입하면 실행 가드에서 예외를 발생시킨다.
- facts: claim/financial 값은 원문 표현과 source_id를 보존. normalized 값은 문자열. C1의 count만으로 집합 동일성을 증명하지 않는다.
- comparability: comparable/not_comparable/unknown. A의 표기를 맹신하지 말고 adapter가 기업·기간·종류·범위로 검증한다.
- explanation: 인용 source_id 또는 null; search_complete는 승인된 검색 coverage 정책을 통과한 경우에만 true.
- policy: 승인 여부·version·hash·활성 items. C3 비율/계정 규칙 미정이면 보류. 예시 5배를 기본값으로 쓰지 않는다.

출력 execution_state = completed / blocked / not_run. 공개 status는 completed일 때만
matched / needs_explanation / not_applicable, 이외 null. 이는 네 번째 연계 판정 상태를 만드는 것이 아니다.
review_required 및 reason_codes로 데이터 실패·미정 정책·출처 실패를 별도로 보존한다.
결과에는 packet·policy 해시와 모든 사용 source_id, 설명 참조, 양쪽 값을 기록한다.
기존 evidence_grade/label 필드는 계약 자체에 없으며 반환하면 schema 오류다.

## 코드와 모델 역할
- 코드: 적용조건, 비교 가능성, 단위/숫자 대조, 허용 차이 정책, 상태 결정.
- 모델: 지정된 공시 묶음 내 설명 후보 탐색만. 관련 없는 운영통제 문구를 보편적 면죄부로 쓰지 않는다.
- 차이 설명을 못 찾더라도 search_complete=false이면 blocked/review. unknown을 설명 부재로 바꾸지 않는다.
- 미래 투자 약속이 약정 주석에 없다는 이유만으로 needs_explanation 금지.
- 회계 판단 금지 문구 필터는 생성된 연계 해설에 적용한다. 증거 원문의 인용은 변조하지 않고 분리 표시한다.
- C5 직접 호출은 예외. 일반 pipeline은 그 항목을 not_run + stage_disabled로 기록한다.
  회계 판단 유혹 사례의 적용성 분류는 not_applicable로 평가하되 C5 엔진을 실행하지 않는다.

## 안정적 반환 예
비교 불가능: completed/not_applicable, reason=not_comparable.
자료 읽기 실패: blocked/null, reason=source_unreadable.
정책 미정: blocked/null, reason=policy_unapproved.
일치 검증 완료: completed/matched.
설명 원문·귀속 검증 완료: completed/matched.
비교 가능한 차이 + 검색 coverage 충족 + 설명 없음: completed/needs_explanation.

## 계약 변경
A가 schema version과 예제를 함께 갱신한다. B는 기존 v1을 조용히 다르게 해석하지 않는다.
합칠 때 A가 packet 저장·hash 재검증·tenant 권한을 적용하고 새 API/DB 계약과 rollback을 작성한다.

C3의 추가 입력 c3_context는 통화, 약속 대상기간, CAPEX 기간, 실제 capex_account_ids,
해당 계획의 약정 source_id와 조달·집행 설명 source_id를 기록한다. C1에서는 null이다.
policy의 c3_account_mapping_approved=true는 위 계정 ID·기간 정책을 승인했다는 뜻이며,
그 승인의 실제 목록과 근거는 policy.version이 가리키는 immutable 정책 원본에 보존한다.
상세 정책팩 없이 boolean만 받은 실행은 blocked다. 임계값은 Decimal 문자열로 파싱한다.
날짜 문법 및 시작≤종료, source_id 존재·해시 일치, approved synthetic_only의 live 사용 금지는
schema 외 application 검증의 필수 항목이다. 스키마 통과만으로 검증된 근거가 되지 않는다.
