# 공동 개발 계약 1.1

v1.0 C1/C3 예제를 `v1/`에 보존한다. 새 전체 범위는 C1~C4를 지원하는 1.1로 교환한다.
구버전 packet을 1.1이라고 이름만 바꿔 읽지 않는다. A가 새 필드를 원문에서 확보해 새 packet revision을 만든다.
이 계약은 내부 모듈 교환용이다. 기존 public API/DB contract는 자동 변경되지 않는다.

## 누가 만드는가
A: 검증된 claim·태그·문서 범위로 packet을 구성한다.
B adapter: 재무 원문·계정·주석을 source/fact로 만든다.
B application: raw bytes→hash→locator/quote→귀속→기간·정책을 검증하고 pure engine을 부른다.
B engine: 검증된 입력에 승인 policy를 적용해 status/보류 결과를 반환한다.
A: 반환 hash·identity·출처를 재확인하고 권한·리비전·UI를 연결한다.

## 함수·Port
```python
# 신규 구현 대상; 이 문서가 엔진을 구현하지는 않는다.
def evaluate(packet: dict, policy: dict) -> dict: ...
def reconcile(packet: dict, policy: dict, *, source_reader, explanation_search) -> dict: ...
# source_reader(ref: dict) -> bytes : locator가 속한 원본 immutable artifact
# explanation_search(packet: dict) -> list[dict] : 정본 sources 형식의 후보
```
source_reader를 통해 확보한 실제 bytes의 SHA256이 source.artifact_sha256과 일치해야 한다.
문자 인용과 위치 검증은 format별 reader가 수행한다. byte hash가 같아도 locator·귀속이 틀리면 인정하지 않는다.
raw client packet의 comparability/search_complete를 권위 있는 사실로 신뢰하지 않는다.

## 상태
execution_state = completed / blocked / not_run.
completed이면 status = matched / needs_explanation / not_applicable 중 하나.
blocked/not_run이면 status=null. 네 번째 연계 라벨을 추가하지 않는다.
C5 호출은 내부 NotImplementedError, dispatch는 not_run/stage_disabled 기록. C5를 스키마 허용 item으로 추가하지 않는다.
reason_codes는 기계 판독 사유, review_required는 검토 필요. 사용자 표현은 설명 보완/판단 대기로 제한한다.
원문 인용에는 금지 단어가 있을 수 있다. generated commentary와 구분하여 원문을 삭제/변조하지 않는다.

## 필수 의미 검증 (JSON Schema 이상의 검사)
- 날짜 순서, source ID 유일성·참조 존재, 실제 bytes와 hash·quote·locator 일치.
- tenant/company/FY/접수번호/정정 버전·연결기준·이용가능 시점.
- C1에서 개수가 아닌 집합·대상 종류, C2에서 실제 기간과 수집시차 설명.
- C3에서 Decimal·통화·승인 계정·기간·정책·양수 CAPEX; 부족하면 보류.
- C4에서 해당 분류의 definition와 calculation_basis 두 인용의 귀속.
- complete search에는 coverage_policy/receipt, 필요한 문서 목록, 실패 없음이 필요.
  스키마상 완전해도 실제 전수성은 검증된 coverage receipt로 확인한다.
- synthetic_only policy는 synthetic packet에만 사용. approved boolean만으로 실제 승인을 인정하지 않는다.
  정책 원문·승인자·승인일·hash를 registry에서 대조한다.

## 입력/출력/예제
input.schema.json / policy.schema.json / output.schema.json이 필드 형식 정본.
SCHEMA_GUIDE.md는 해석·null·예제 용도. examples/*.json은 input/policy/expected 묶음이다.
예제 원문과 hash는 합성 placeholder이며 실제 provenance 검증을 통과한 원본이 아니다.
validator 통과는 구조·정합성 확인이고 판정엔진 성능/원문 검증 완료가 아니다.

## 호환성
v1.0 입력에는 기존 reader를 유지하거나 명시적 unsupported_version을 반환한다.
v1.1 enum/identity/source 필드를 구버전 클라이언트 응답에 임의 추가하지 않는다.
결과에 기존 evidence_grade/label 필드는 허용하지 않는다. packet/policy hash 변경은 새 revision.
